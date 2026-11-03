"""Point facts from an existing diagnosis SQLite index, read only and chunk by chunk (Phase 4-K).

Supported layout: ``hererisk-flood-diag-v0.1`` (Phase 4-D; the layout carries no hazard meaning):

* ``comps``      one row per component: ``zone_ref``, bounding box, ``rings`` (packed per ring: hole flag,
                 signed-area sign, interior side, segment count)
* ``chunks``     consecutive vertices of one ring (``ring``, ``chunk_no``), float64 lon / lat; a chunk's
                 last vertex is the next chunk's first, so no segment is counted twice; ``chunk_rtree``
* ``defects``    the component's defect points and kinds (touch / touch_on_edge / overlap / crossing)

``Reader.point_facts(zone_ref, lat, lon)`` reads only the chunks the R-tree returns for (1) the box of
``boundary_search_m`` around the point and (2) the box of the ray, one row at a time (nothing is
concatenated), and returns ``hererisk.common.polygon.facts`` plus the component's defect kinds. Limits:
``max_chunks`` chunk rows and ``budget_s`` seconds (also enforced inside SQLite by a progress handler
on this reader's own connection); when one is reached, or on any read error, the result is
``complete: false`` with no facts (never a partial count, never "outside").

The index is opened read only and its format is not changed. Whether the index belongs to the data a
Provider serves (``meta.derived_from``) is the Provider's check; this reader only requires
``status: complete`` and the supported format. One reader per thread (one connection, one deadline).
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import numpy as np

from hererisk.common.polygon.facts import RayCounter, ray_direction, scale

SUPPORTED_FORMATS = ("hererisk-flood-diag-v0.1",)
RING_DTYPE = np.dtype([("hole", "i1"), ("area_sign", "i1"), ("inner_left", "i1"), ("segments", "<i4")])
MAX_CHUNKS = 200_000
BUDGET_S = 1.0


class ReaderError(Exception):
    """The index cannot be used (missing, unreadable, incomplete, unsupported). Fixed messages."""


class _Stop(Exception):
    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


class Reader:
    def __init__(self, path: Path) -> None:
        path = Path(path)
        if not path.is_file():
            raise ReaderError("index not found")
        self.db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        try:
            self.meta = {k: json.loads(v) for k, v in self.db.execute("SELECT key, value FROM meta")}
        except (sqlite3.DatabaseError, ValueError) as exc:
            self.db.close()
            raise ReaderError("index cannot be read") from exc
        if self.meta.get("status") != "complete":
            self.db.close()
            raise ReaderError("index is incomplete")
        if self.meta.get("diag_format") not in SUPPORTED_FORMATS:
            self.db.close()
            raise ReaderError("index format is not supported")
        self._deadline = 0.0
        self.db.set_progress_handler(lambda: 1 if self._deadline and time.monotonic() > self._deadline else 0, 1000)

    def close(self) -> None:
        self.db.close()

    def _component(self, zone_ref: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT id, minx, miny, maxx, maxy, rings FROM comps WHERE zone_ref = ?", (zone_ref,)).fetchone()
        if row is None:
            return None
        return {"id": row[0], "bbox": tuple(row[1:5]), "rings": np.frombuffer(row[5], RING_DTYPE)}

    def _chunks(self, comp_id: int, box: tuple, budget: dict):
        minx, miny, maxx, maxy = box
        cur = self.db.execute("SELECT ring, coords FROM chunks WHERE comp = ? AND id IN (SELECT id FROM chunk_rtree "
                              "WHERE minx <= ? AND maxx >= ? AND miny <= ? AND maxy >= ?)",
                              (comp_id, maxx, minx, maxy, miny))
        for ring, blob in cur:                      # one row at a time
            budget["chunks"] += 1
            if budget["chunks"] > budget["max_chunks"]:
                raise _Stop("limit_exceeded")
            if time.monotonic() > self._deadline:
                raise _Stop("timeout")
            yield int(ring), np.frombuffer(blob, "<f8").reshape(-1, 2)

    def point_facts(self, zone_ref: str, lat: float, lon: float, *, boundary_search_m: float = 1.0,
                    max_chunks: int = MAX_CHUNKS, budget_s: float = BUDGET_S) -> dict[str, Any]:
        base = {"zone_ref": zone_ref, "index_format": self.meta.get("diag_format"), "index_built_at": self.meta.get("built_at")}
        budget = {"chunks": 0, "max_chunks": max_chunks}
        t0 = time.monotonic()
        self._deadline = t0 + budget_s
        try:
            comp = self._component(zone_ref)
            if comp is None:
                return {**base, "status": "not_found", "complete": False}
            rings = comp["rings"]
            way, ray_box = ray_direction(comp["bbox"], lat, lon)
            counter = RayCounter(lat, lon, way, len(rings), boundary_search_m=boundary_search_m)
            kx, ky = scale(lat)
            dx, dy = boundary_search_m / kx, boundary_search_m / ky
            for ring, v in self._chunks(comp["id"], (lon - dx, lat - dy, lon + dx, lat + dy), budget):
                if not 0 <= ring < len(rings):
                    raise _Stop("failed")
                counter.add_boundary_piece(v)
            for ring, v in self._chunks(comp["id"], ray_box, budget):
                counter.add_ray_piece(ring, v)
            kinds = dict(self.db.execute("SELECT kind, COUNT(*) FROM defects WHERE comp = ? GROUP BY kind", (comp["id"],)))
            facts = counter.result(rings["area_sign"], rings["hole"] == 1)
        except _Stop as stop:
            return {**base, "status": stop.status, "complete": False, "chunks_read": budget["chunks"]}
        except sqlite3.OperationalError as exc:
            return {**base, "status": "timeout" if "interrupt" in str(exc).lower() else "failed", "complete": False}
        except (sqlite3.Error, ValueError):
            return {**base, "status": "failed", "complete": False}
        finally:
            self._deadline = 0.0
        return {**base, "status": "complete", "complete": True, **facts,
                "component_defect_kinds": kinds, "chunks_read": budget["chunks"],
                "seconds": round(time.monotonic() - t0, 6)}
