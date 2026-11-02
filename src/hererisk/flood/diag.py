"""Offline preprocessing and a light local search for invalid flood polygons (Phase 4-D, PoC).

    python -m hererisk.flood diag build   --regions <regions.json> --flood-index <index.sqlite> --output <diag.sqlite>
    python -m hererisk.flood diag point   --diag-index <diag.sqlite> --point LAT,LON [--settings S] [--flood-index I]
    python -m hererisk.flood diag compare --diag-index <diag.sqlite> --baseline <4-C report dir> [--report-dir DIR]
    python -m hererisk.flood diag bench   --diag-index <diag.sqlite> --points <bench-points.json> [--repeat N]
    python -m hererisk.flood diag cases   --diag-index <diag.sqlite> --cases <cases.json>

Diagnosis only: nothing here changes the official ZIPs, the flood index, the Flood Provider or the
Location API, and no result is an official depth. ``--diag-index`` defaults to ``$HERERISK_FLOOD_DIAG_INDEX``.

Build (offline, once per flood index): the pending rows of the flood index (``usable = 0``: the
components the Provider answers ``unknown`` for; Phase 4-B checked every index row against the official
ZIPs) are prepared with the Phase 4-C method (``local_analysis.Prepared``): segments in ring order, the
orientation of each ring, and every defect with its kind. Stored in SQLite:

* ``comps``   one row per component (zone_ref, source, river, depth class, rings, counts) + R-tree
* ``chunks``  64 consecutive segments of one ring as packed float64 vertices + R-tree
* ``defects`` defect points with their kind (touch / touch_on_edge / crossing / overlap) + R-tree
* ``meta``    format, method version, the flood index it was derived from, the ZIP SHA-256 values
  (re-hashed at build time and required to equal the flood index's), registration, checks, status

The file is written to a temporary name and renamed when complete; a failed build leaves the previous
file untouched. ``status`` must be ``complete`` and the format/method must match, or the file is refused.

Lookup (online-equivalent, ``DiagIndex``): no ZIP, no shapely, nothing loaded up front. Per component
and radius it reads only the chunks and defects in the radius box, then, when the side of the nearest
boundary is known, the chunks on one ray (the shortest way out of the component's bounding box) to
count the winding number of the whole component. Same rules and arithmetic as Phase 4-C.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import resource
import sqlite3
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from hererisk.flood.errors import DiagIndexError
from hererisk.flood.settings import load_settings, radii as setting_radii

DIAG_FORMAT = "hererisk-flood-diag-v0.1"
METHOD = "local-contour-winding-v1 (Phase 4-C local_analysis)"
CHUNK = 64
M_PER_DEG = 111320.0
ON_BOUNDARY_M = 0.001
TIE_M = 1e-6
DECIDED = ("inside", "outside")
KIND_ORDER = ("touch", "touch_on_edge", "overlap", "crossing")   # worst last
RING_DTYPE = np.dtype([("hole", "i1"), ("area_sign", "i1"), ("inner_left", "i1"), ("segments", "<i4")])


def _scale(lat: float) -> tuple[float, float]:
    return M_PER_DEG * math.cos(math.radians(lat)), M_PER_DEG


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _rss_bytes() -> int:
    v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(v if platform.system() == "Darwin" else v * 1024)


# --- build (offline) ---------------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE comps (id INTEGER PRIMARY KEY, zone_ref TEXT NOT NULL UNIQUE, source_id TEXT NOT NULL,
  product_ref TEXT NOT NULL, feature_index INTEGER NOT NULL, polygon_index INTEGER NOT NULL, reason TEXT NOT NULL,
  river_code TEXT NOT NULL, river_name TEXT NOT NULL, manager TEXT NOT NULL, depth_class TEXT NOT NULL,
  minx REAL NOT NULL, miny REAL NOT NULL, maxx REAL NOT NULL, maxy REAL NOT NULL, valid INTEGER NOT NULL,
  defects_unlocated INTEGER NOT NULL, segments INTEGER NOT NULL, defects INTEGER NOT NULL,
  zero_area_rings INTEGER NOT NULL, rings BLOB NOT NULL);
CREATE VIRTUAL TABLE comp_rtree USING rtree(id, minx, maxx, miny, maxy);
CREATE TABLE chunks (id INTEGER PRIMARY KEY, comp INTEGER NOT NULL, ring INTEGER NOT NULL, chunk_no INTEGER NOT NULL,
  coords BLOB NOT NULL);
CREATE UNIQUE INDEX chunks_key ON chunks (comp, ring, chunk_no);
CREATE VIRTUAL TABLE chunk_rtree USING rtree(id, minx, maxx, miny, maxy);
CREATE TABLE defects (id INTEGER PRIMARY KEY, comp INTEGER NOT NULL, x REAL NOT NULL, y REAL NOT NULL,
  kind TEXT NOT NULL, same_ring INTEGER NOT NULL);
CREATE INDEX defects_comp ON defects (comp);
CREATE VIRTUAL TABLE defect_rtree USING rtree(id, minx, maxx, miny, maxy);
"""


def _ring_vertices(prep: Any) -> list[np.ndarray]:
    """The closed vertex array of each prepared ring (consecutive repeats already removed)."""
    out = []
    for k in range(len(prep.area_sign)):
        m = prep.ring == k
        x1, y1, x2, y2 = prep.x1[m], prep.y1[m], prep.x2[m], prep.y2[m]
        out.append(np.vstack([np.stack([x1, y1], 1), [[x2[-1], y2[-1]]]]))
    return out


def _defect_kinds(prep: Any) -> tuple[np.ndarray, list[str], list[int]]:
    """The defects of ``prep`` (same points, same order) with their worst kind and whether the two
    segments are on the same ring."""
    import shapely
    segs = shapely.linestrings(np.stack([np.stack([prep.x1, prep.y1], 1), np.stack([prep.x2, prep.y2], 1)], 1))
    i, j = shapely.STRtree(segs).query(segs, predicate="intersects")
    keep = (i < j) & (prep.next[i] != j) & (prep.prev[i] != j)
    i, j = i[keep], j[keep]
    kinds: dict[tuple[float, float], str] = {}
    same: dict[tuple[float, float], int] = {}
    if len(i):
        inter = shapely.intersection(segs[i], segs[j])
        for a, b, g in zip(i, j, inter):
            ends_a = {(prep.x1[a], prep.y1[a]), (prep.x2[a], prep.y2[a])}
            ends_b = {(prep.x1[b], prep.y1[b]), (prep.x2[b], prep.y2[b])}
            if g.geom_type in ("LineString", "MultiLineString", "GeometryCollection"):
                kind = "overlap"
            else:
                p = (g.x, g.y)
                kind = "touch" if p in ends_a and p in ends_b else "touch_on_edge" if p in ends_a or p in ends_b \
                    else "crossing"
            for x, y in shapely.get_coordinates(g):
                key = (round(float(x), 12), round(float(y), 12))
                if key not in kinds or KIND_ORDER.index(kind) > KIND_ORDER.index(kinds[key]):
                    kinds[key] = kind
                same[key] = max(same.get(key, 0), int(prep.ring[a] == prep.ring[b]))
    pts = prep.defects
    keys = [(round(float(x), 12), round(float(y), 12)) for x, y in pts]
    return pts, [kinds.get(k, "touch") for k in keys], [same.get(k, 0) for k in keys]


def _flood_identity(meta: dict[str, Any]) -> dict[str, Any]:
    return {k: meta.get(k) for k in ("index_format", "built_at", "zip_sha256")}


def build(regions_file: Path, flood_index: Path, output: Path, *, log=lambda m: None) -> dict[str, Any]:
    import shapely
    from hererisk.flood.index import read_meta
    from hererisk.flood.local_analysis import Prepared
    from hererisk.flood.registry import load_flood_sources, registration_view
    started = time.time()
    meta = read_meta(flood_index)
    regs = load_flood_sources(regions_file)
    if [registration_view(r) for r in regs] != meta.get("registration"):
        raise DiagIndexError("the flood index was built from another registration")
    for r in regs:                                     # the official ZIPs now == when the index was built
        for f in r["files"]:
            if _sha256(f["path"]) != meta["zip_sha256"].get(f["file_name"]):
                raise DiagIndexError(f"ZIP SHA-256 differs from the flood index: {f['file_name']}")
    output = Path(output)
    tmp = output.with_name(output.name + f".tmp-{os.getpid()}")
    tmp.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{flood_index}?mode=ro", uri=True)
    db = sqlite3.connect(tmp)
    try:
        db.executescript(SCHEMA)
        counts = Counter()
        kinds = Counter()
        prep_s = 0.0
        rows = src.execute("SELECT zone_ref, source_id, product_ref, feature_index, polygon_index, reason, river_code, "
                           "river_name, manager, depth_class, wkb FROM components WHERE usable = 0 ORDER BY rowid")
        for n, r in enumerate(rows, start=1):
            g = shapely.from_wkb(r[10])
            t0 = time.perf_counter()
            prep = Prepared(g)
            pts, kind, same = _defect_kinds(prep)
            prep_s += time.perf_counter() - t0
            rings = np.array([(k > 0, prep.area_sign[k], prep.inner_left[k], np.sum(prep.ring == k))
                              for k in range(len(prep.area_sign))], dtype=RING_DTYPE)
            minx, miny, maxx, maxy = g.bounds
            cid = db.execute("INSERT INTO comps (zone_ref, source_id, product_ref, feature_index, polygon_index, reason, "
                             "river_code, river_name, manager, depth_class, minx, miny, maxx, maxy, valid, "
                             "defects_unlocated, segments, defects, zero_area_rings, rings) "
                             "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (*r[:10], minx, miny, maxx, maxy, int(prep.valid), int(prep.defects_unlocated),
                              prep.segments, len(pts), int(np.sum(rings["area_sign"] == 0)), rings.tobytes())).lastrowid
            db.execute("INSERT INTO comp_rtree VALUES (?,?,?,?,?)", (cid, minx, maxx, miny, maxy))
            for k, v in enumerate(_ring_vertices(prep)):
                for c in range(math.ceil((len(v) - 1) / CHUNK)):
                    part = v[c * CHUNK: c * CHUNK + CHUNK + 1]
                    hid = db.execute("INSERT INTO chunks (comp, ring, chunk_no, coords) VALUES (?,?,?,?)",
                                     (cid, k, c, part.astype("<f8").tobytes())).lastrowid
                    db.execute("INSERT INTO chunk_rtree VALUES (?,?,?,?,?)",
                               (hid, float(part[:, 0].min()), float(part[:, 0].max()),
                                float(part[:, 1].min()), float(part[:, 1].max())))
                    counts["chunks"] += 1
            for (x, y), kd, sr in zip(pts, kind, same):
                did = db.execute("INSERT INTO defects (comp, x, y, kind, same_ring) VALUES (?,?,?,?,?)",
                                 (cid, float(x), float(y), kd, sr)).lastrowid
                db.execute("INSERT INTO defect_rtree VALUES (?,?,?,?,?)", (did, float(x), float(x), float(y), float(y)))
                kinds[kd] += 1
            counts["comps"] += 1
            counts["segments"] += prep.segments
            counts["defects"] += len(pts)
            counts["defects_unlocated"] += int(prep.defects_unlocated)
            if n % 500 == 0:
                log(f"diag build: {n} components")
        pending = src.execute("SELECT COUNT(*) FROM components WHERE usable = 0").fetchone()[0]
        checks = _check_roundtrip(db, src)
        if counts["comps"] != pending or checks["ring_mismatches"]:
            raise DiagIndexError("the prepared data does not match the flood index")
        index_meta = {
            "diag_format": DIAG_FORMAT, "method": METHOD, "chunk_segments": CHUNK,
            "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "derived_from": {"flood_index": _flood_identity(meta), "flood_index_sha256": _sha256(flood_index)},
            "zip_sha256": meta["zip_sha256"], "registration": meta["registration"],
            "counts": {**counts, "pending_rows_in_flood_index": pending, "defect_kinds": dict(kinds)},
            "checks": checks, "prepare_seconds": round(prep_s, 1),
            "program": {"python": platform.python_version(), "shapely": shapely.__version__,
                        "geos": shapely.geos_version_string, "numpy": np.__version__},
            "diagnosis_only": True,
            "notes": ["derived from the flood index pending rows (checked against the official ZIPs in Phase 4-B)",
                      "not a Publish / Dataset Registry generation; no switch, no publication"],
        }
        for k, v in index_meta.items():
            db.execute("INSERT INTO meta VALUES (?, ?)", (k, json.dumps(v, ensure_ascii=False)))
        db.execute("INSERT INTO meta VALUES ('status', '\"complete\"')")   # last: an interrupted build has none
        db.commit()        # append-only file: no VACUUM (it needs temporary space the read-only container lacks)
        db.close()
        src.close()
    except BaseException:
        db.close()
        src.close()
        tmp.unlink(missing_ok=True)
        raise
    os.replace(tmp, output)
    return {**index_meta, "seconds": round(time.time() - started, 1), "file_bytes": output.stat().st_size,
            "peak_rss_bytes": _rss_bytes()}


def _check_roundtrip(db: sqlite3.Connection, src: sqlite3.Connection) -> dict[str, Any]:
    """Every stored ring, reassembled from its chunks, equals the flood index geometry's ring
    (consecutive repeated vertices removed)."""
    import shapely
    from hererisk.flood.local_analysis import _ring_coords
    bad = rings = 0
    wkb = {r[0]: r[1] for r in src.execute("SELECT zone_ref, wkb FROM components WHERE usable = 0")}
    for cid, ref in db.execute("SELECT id, zone_ref FROM comps").fetchall():
        g = shapely.from_wkb(wkb[ref])
        want = [c for c in (_ring_coords(r) for r in [g.exterior, *g.interiors]) if len(c) > 1]
        got: dict[int, list[np.ndarray]] = defaultdict(list)
        for ring, blob in db.execute("SELECT ring, coords FROM chunks WHERE comp = ? ORDER BY ring, chunk_no", (cid,)):
            got[ring].append(np.frombuffer(blob, "<f8").reshape(-1, 2))
        for k, w in enumerate(want):
            rings += 1
            parts = got.get(k, [])
            v = np.vstack([parts[0]] + [p[1:] for p in parts[1:]]) if parts else np.zeros((0, 2))
            bad += not np.array_equal(v, w)
        bad += len(got) != len(want)
    return {"rings_checked": rings, "ring_mismatches": bad}


# --- lookup (online-equivalent) ----------------------------------------------------------------------
class DiagIndex:
    """Read-only; nothing is loaded up front."""

    def __init__(self, path: Path, *, flood_index: Path | None = None) -> None:
        path = Path(path)
        if not path.is_file():
            raise DiagIndexError("diagnosis index not found")
        self.db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        try:
            self.meta = {k: json.loads(v) for k, v in self.db.execute("SELECT key, value FROM meta")}
        except sqlite3.DatabaseError as exc:
            raise DiagIndexError("diagnosis index cannot be read") from exc
        if self.meta.get("status") != "complete":
            raise DiagIndexError("diagnosis index is incomplete")
        if self.meta.get("diag_format") != DIAG_FORMAT or self.meta.get("method") != METHOD:
            raise DiagIndexError("diagnosis index has another format or method version")
        self.chunk = int(self.meta["chunk_segments"])
        if flood_index is not None:
            from hererisk.flood.index import read_meta
            derived = self.meta.get("derived_from")
            if not isinstance(derived, dict) or _flood_identity(read_meta(flood_index)) != derived.get("flood_index"):
                raise DiagIndexError("diagnosis index was derived from another flood index")

    # components
    _COLS = ("id, zone_ref, source_id, river_code, river_name, manager, depth_class, minx, miny, maxx, maxy, valid, "
             "defects_unlocated, segments, defects, zero_area_rings, rings, feature_index, polygon_index, reason")

    def _comp(self, row: tuple) -> dict[str, Any]:
        keys = [k.strip() for k in self._COLS.split(",")]
        c = dict(zip(keys, row))
        c["rings"] = np.frombuffer(c["rings"], RING_DTYPE)
        c["depth_class"] = json.loads(c["depth_class"])
        return c

    def candidates(self, lat: float, lon: float) -> list[dict[str, Any]]:
        rows = self.db.execute(f"SELECT {self._COLS} FROM comps WHERE id IN (SELECT id FROM comp_rtree WHERE "
                               "minx <= ? AND maxx >= ? AND miny <= ? AND maxy >= ?) ORDER BY id", (lon, lon, lat, lat))
        return [c for c in map(self._comp, rows) if c["minx"] <= lon <= c["maxx"] and c["miny"] <= lat <= c["maxy"]]

    def by_refs(self, refs: list[str]) -> list[dict[str, Any]]:
        out = []
        for ref in refs:
            row = self.db.execute(f"SELECT {self._COLS} FROM comps WHERE zone_ref = ?", (ref,)).fetchone()
            out.append(None if row is None else self._comp(row))
        return out

    # geometry reads
    def _segments_in(self, comp: dict[str, Any], minx, miny, maxx, maxy) -> dict[str, np.ndarray]:
        x1, y1, x2, y2, ring, k = [], [], [], [], [], []
        for r, c, blob in self.db.execute(
                "SELECT ring, chunk_no, coords FROM chunks WHERE comp = ? AND id IN (SELECT id FROM chunk_rtree WHERE "
                "minx <= ? AND maxx >= ? AND miny <= ? AND maxy >= ?)", (comp["id"], maxx, minx, maxy, miny)):
            v = np.frombuffer(blob, "<f8").reshape(-1, 2)
            x1.append(v[:-1, 0]), y1.append(v[:-1, 1]), x2.append(v[1:, 0]), y2.append(v[1:, 1])
            ring.append(np.full(len(v) - 1, r)), k.append(c * self.chunk + np.arange(len(v) - 1))
        if not x1:
            return {}
        return {"x1": np.concatenate(x1), "y1": np.concatenate(y1), "x2": np.concatenate(x2), "y2": np.concatenate(y2),
                "ring": np.concatenate(ring), "k": np.concatenate(k)}

    def _vertex(self, comp: dict[str, Any], ring: int, i: int, cache: dict) -> tuple[float, float]:
        nseg = int(comp["rings"][ring]["segments"])
        c = min(i // self.chunk, math.ceil(nseg / self.chunk) - 1)
        key = (ring, c)
        if key not in cache:
            blob = self.db.execute("SELECT coords FROM chunks WHERE comp = ? AND ring = ? AND chunk_no = ?",
                                   (comp["id"], ring, c)).fetchone()[0]
            cache[key] = np.frombuffer(blob, "<f8").reshape(-1, 2)
        v = cache[key][i - c * self.chunk]
        return float(v[0]), float(v[1])

    def defect_distance_m(self, comp: dict[str, Any], lat: float, lon: float, within_m: float | None = None) -> tuple[float | None, str | None]:
        """(nearest defect distance, its kind); with ``within_m`` only defects in that box are searched."""
        if not comp["defects"]:
            return None, None
        kx, ky = _scale(lat)
        s = within_m if within_m is not None else 50.0
        while True:
            rows = self.db.execute("SELECT x, y, kind FROM defects WHERE comp = ? AND id IN (SELECT id FROM defect_rtree "
                                   "WHERE minx <= ? AND maxx >= ? AND miny <= ? AND maxy >= ?)",
                                   (comp["id"], lon + s / kx, lon - s / kx, lat + s / ky, lat - s / ky)).fetchall()
            if rows:
                d = np.hypot((np.array([r[0] for r in rows]) - lon) * kx, (np.array([r[1] for r in rows]) - lat) * ky)
                n = int(np.argmin(d))
                if within_m is not None or d[n] <= s:
                    return float(d[n]), rows[n][2]
            elif within_m is not None:
                return None, None
            s *= 4
            if s > 4e6:
                rows = self.db.execute("SELECT x, y, kind FROM defects WHERE comp = ?", (comp["id"],)).fetchall()
                d = np.hypot((np.array([r[0] for r in rows]) - lon) * kx, (np.array([r[1] for r in rows]) - lat) * ky)
                n = int(np.argmin(d))
                return float(d[n]), rows[n][2]

    def winding(self, comp: dict[str, Any], lat: float, lon: float) -> tuple[int, int]:
        """(normalised winding number, ray crossings) on the shortest ray out of the component's box."""
        kx, ky = _scale(lat)
        ways = {"east": (comp["maxx"] - lon) * kx, "west": (lon - comp["minx"]) * kx,
                "north": (comp["maxy"] - lat) * ky, "south": (lat - comp["miny"]) * ky}
        way = min(ways, key=ways.get)
        box = {"east": (lon, lat, comp["maxx"], lat), "west": (comp["minx"], lat, lon, lat),
               "north": (lon, lat, lon, comp["maxy"]), "south": (lon, comp["miny"], lon, lat)}[way]
        s = self._segments_in(comp, *box)
        nrings = len(comp["rings"])
        if not s:
            return 0, 0
        u1, v1, u2, v2, u0, v0 = {"east": (s["x1"], s["y1"], s["x2"], s["y2"], lon, lat),
                                  "west": (-s["x1"], -s["y1"], -s["x2"], -s["y2"], -lon, -lat),
                                  "north": (s["y1"], -s["x1"], s["y2"], -s["x2"], lat, -lon),
                                  "south": (-s["y1"], s["x1"], -s["y2"], s["x2"], -lat, lon)}[way]
        up = (v1 <= v0) & (v2 > v0)
        dn = (v2 <= v0) & (v1 > v0)
        i = np.nonzero(up | dn)[0]
        ui = u1[i] + (v0 - v1[i]) * (u2[i] - u1[i]) / (v2[i] - v1[i])
        right = ui > u0
        raw = np.bincount(s["ring"][i][right].astype(int), weights=np.where(up[i][right], 1, -1), minlength=nrings)
        rings = comp["rings"]
        w = float(np.sum(raw * rings["area_sign"] * np.where(rings["hole"] == 1, -1, 1)))
        return int(round(w)), int(right.sum())

    def _side(self, comp, ring: int, k: int, t: float, lat: float, lon: float, cache: dict) -> bool | None:
        kx, ky = _scale(lat)
        n = int(comp["rings"][ring]["segments"])

        def xy(seg: int, end: int) -> tuple[float, float]:
            x, y = self._vertex(comp, ring, seg + end, cache)
            return (x - lon) * kx, (y - lat) * ky

        def left(p, q) -> bool | None:
            v = (q[0] - p[0]) * (0 - p[1]) - (q[1] - p[1]) * (0 - p[0])
            return None if v == 0 else v > 0
        if 0 < t < 1:
            on_left = left(xy(k, 0), xy(k, 1))
        else:
            s_in, s_out = (k, (k + 1) % n) if t >= 1 else ((k - 1) % n, k)
            a, v, b = xy(s_in, 0), xy(s_in, 1), xy(s_out, 1)
            l_in, l_out = left(a, v), left(v, b)
            turn = (v[0] - a[0]) * (b[1] - v[1]) - (v[1] - a[1]) * (b[0] - v[0])
            if l_in is None or l_out is None or turn == 0:
                return None
            on_left = (l_in and l_out) if turn > 0 else (l_in or l_out)
        if on_left is None:
            return None
        return on_left == bool(comp["rings"][ring]["inner_left"])

    def _nearest(self, comp: dict[str, Any], lat: float, lon: float, r: float):
        """(segments in the box, t, distances, nearest distance) or None when no segment is in the box."""
        kx, ky = _scale(lat)
        rx, ry = r / kx, r / ky
        s = self._segments_in(comp, lon - rx, lat - ry, lon + rx, lat + ry)
        if not s:
            return None
        m = (np.maximum(s["x1"], s["x2"]) >= lon - rx) & (np.minimum(s["x1"], s["x2"]) <= lon + rx) \
            & (np.maximum(s["y1"], s["y2"]) >= lat - ry) & (np.minimum(s["y1"], s["y2"]) <= lat + ry)
        if not m.any():
            return None
        s = {k: v[m] for k, v in s.items()}
        ax, ay = (s["x1"] - lon) * kx, (s["y1"] - lat) * ky
        bx, by = (s["x2"] - lon) * kx, (s["y2"] - lat) * ky
        dx, dy = bx - ax, by - ay
        t = np.clip(-(ax * dx + ay * dy) / (dx * dx + dy * dy), 0.0, 1.0)
        d = np.hypot(ax + t * dx, ay + t * dy)
        return s, t, d, float(d.min())

    def edge_distance_m(self, comp: dict[str, Any], lat: float, lon: float, r: float) -> float | None:
        near = self._nearest(comp, lat, lon, r)
        return None if near is None or near[3] > r else near[3]

    def evaluate(self, comp: dict[str, Any], lat: float, lon: float, r: float) -> dict[str, Any]:
        """The Phase 4-C rule at one radius; ``defect_m`` only when a defect is within r."""
        if comp["defects_unlocated"]:
            return {"outcome": "defect_location_unknown"}
        dd, kind = self.defect_distance_m(comp, lat, lon, within_m=r)
        if dd is not None and dd <= r:
            return {"outcome": "defect_within_radius", "defect_m": round(dd, 2), "defect_kind": kind}
        near = self._nearest(comp, lat, lon, r)
        if near is None:
            return {"outcome": "no_boundary_within_radius"}
        s, t, d, dmin = near
        out: dict[str, Any] = {"edge_m": round(dmin, 3)}
        if dmin > r:
            return {**out, "outcome": "no_boundary_within_radius"}
        if dmin < ON_BOUNDARY_M:
            return {**out, "outcome": "on_boundary"}
        near = list(np.nonzero(d <= dmin + TIE_M)[0])
        if any(comp["rings"][int(s["ring"][n])]["area_sign"] == 0 for n in near):
            return {**out, "outcome": "orientation_unknown"}
        cache: dict = {}
        sides = {self._side(comp, int(s["ring"][n]), int(s["k"][n]), float(t[n]), lat, lon, cache) for n in near}
        if None in sides or len(sides) != 1:
            return {**out, "outcome": "ambiguous_nearest"}
        inner = sides.pop()
        w, crossings = self.winding(comp, lat, lon)
        out.update(local_side="inside" if inner else "outside", winding=w, parity_inside=bool(crossings % 2))
        if (inner and w == 1) or (not inner and w == 0):
            return {**out, "outcome": "inside" if inner else "outside"}
        return {**out, "outcome": "inconsistent_winding"}

    def analyze(self, comp: dict[str, Any], lat: float, lon: float, radii: list[float], *,
                all_radii: bool = False) -> dict[str, Any]:
        """Staged over ``radii`` (stops at the first conclusion), or every radius with ``all_radii``."""
        evals = []
        for r in radii:
            e = self.evaluate(comp, lat, lon, r)
            evals.append({"radius_m": r, **e})
            if not all_radii and e["outcome"] != "no_boundary_within_radius":
                break
        final = next((e for e in evals if e["outcome"] != "no_boundary_within_radius"), None)
        if final is None:
            final = {**evals[-1], "outcome": "no_boundary_within_max_radius", "radius_m": radii[-1]}
        far = final
        if final["outcome"] == "no_boundary_within_max_radius":
            w, crossings = self.winding(comp, lat, lon)
            if comp["defects_unlocated"]:
                far = {**final, "outcome": "defect_location_unknown", "winding": w}
            elif comp["zero_area_rings"]:
                far = {**final, "outcome": "orientation_unknown", "winding": w}
            elif w in (0, 1) and bool(crossings % 2) == (w == 1):
                far = {**final, "outcome": "inside" if w == 1 else "outside", "by": "far_winding", "winding": w}
            else:
                far = {**final, "outcome": "inconsistent_winding", "winding": w}
        return {"per_radius": evals, "local": final, "local_plus_far": far}

    def diagnose(self, lat: float, lon: float, radii: list[float], targets: list[tuple[str, str | None, list[str]]],
                 *, identity_ok: bool) -> list[dict[str, Any]]:
        """Phase 4-E: classify the Provider's unknowns, ``targets`` = [(source_id, service region relation,
        unknown zone_refs)]. Only these components are diagnosed; nothing is added from the index."""
        from hererisk.flood.adoption import classify
        out = []
        for sid, relation, refs in targets:
            for ref, comp in zip(refs, self.by_refs(refs)):
                t0 = time.perf_counter()
                analysis = None
                if comp is not None:
                    comp = {**comp, "ring_count": len(comp["rings"])}
                    if comp["source_id"] != sid:
                        comp = None                   # another source's component: not this unknown
                if comp is not None:
                    analysis = self.analyze(comp, lat, lon, radii)
                    dd = self.defect_distance_m(comp, lat, lon, within_m=radii[-1])
                    analysis["defect_within_max"] = dd if dd[0] is not None and dd[0] <= radii[-1] else None
                c = classify({"status": self.meta.get("status"), "identity_ok": identity_ok, "in_provider_unknowns": True,
                              "service_region_relation": relation}, comp, analysis)
                out.append({"source_id": sid, "zone_ref": ref, "method": self.meta["method"], **c,
                            "depth_class_in_source": None if comp is None else comp["depth_class"],
                            "seconds": round(time.perf_counter() - t0, 6)})
        return out

    def lookup(self, lat: float, lon: float, radii: list[float], *, zone_refs: list[str] | None = None,
               all_radii: bool = False) -> dict[str, Any]:
        """Diagnosis of the invalid components at a point: those named (e.g. the Provider's unknowns),
        else every prepared component whose bounding box holds the point. Never an official depth."""
        comps = self.candidates(lat, lon) if zone_refs is None else [c for c in self.by_refs(zone_refs) if c]
        out = []
        for c in comps:
            a = self.analyze(c, lat, lon, radii, all_radii=all_radii)
            out.append({"zone_ref": c["zone_ref"], "source_id": c["source_id"], "river_code": c["river_code"],
                        "river_name_in_source": c["river_name"], "depth_class_in_source": c["depth_class"],
                        "reason": c["reason"], **a})
        return {"diagnosis_only": True, "not_an_official_depth": True, "lat": lat, "lon": lon, "radii_m": radii,
                "components": out}


# --- comparison with Phase 4-C ----------------------------------------------------------------------
def _baseline(report_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    report_dir = Path(report_dir)
    summary = json.loads((report_dir / "summary.json").read_text(encoding="utf-8"))
    points = [json.loads(line) for line in open(report_dir / "points.jsonl", encoding="utf-8")]
    return summary, points


def _r(v: Any, nd: int) -> Any:
    return None if v is None else round(float(v), nd)


def compare(diag: DiagIndex, report_dir: Path, *, log=lambda m: None) -> dict[str, Any]:
    """Every invalid (point, component) pair of a Phase 4-C report, analysed again from the diagnosis
    index only, field by field; then the A (make_valid vs even-odd) and B (decided, then a defect at a
    larger radius) case classes."""
    summary, points = _baseline(report_dir)
    radii = setting_radii(summary["inputs"]["local_analysis"])
    fields = Counter()
    mism: list[dict[str, Any]] = []
    cand = Counter()
    pairs = 0
    case_a, case_b, regress = [], [], []
    phase_4c_rule = Counter()
    for n, pt in enumerate(points):
        lat, lon = pt["lat"], pt["lon"]
        base = [p for p in pt["pairs"] if not p["control"]]
        for p in pt["pairs"]:     # the Phase 4-C count (decided, then a defect at the next radius), with controls
            o = [e["outcome"] for e in p["per_radius"]]
            if any(x in DECIDED and y == "defect_within_radius" for x, y in zip(o, o[1:])):
                phase_4c_rule["valid control pairs" if p["control"] else "invalid pairs"] += 1
        got_refs = {c["zone_ref"] for c in diag.candidates(lat, lon)}
        want_refs = {p["zone_ref"] for p in base}
        cand["equal" if got_refs == want_refs else "superset (outside the service region test)" if got_refs >= want_refs
             else "MISSING"] += 1
        comps = dict(zip([p["zone_ref"] for p in base], diag.by_refs([p["zone_ref"] for p in base])))
        for p in base:
            pairs += 1
            c = comps[p["zone_ref"]]
            if c is None:
                fields["zone_ref missing"] += 1
                mism.append({"lat": lat, "lon": lon, "zone_ref": p["zone_ref"], "field": "zone_ref"})
                continue
            a = diag.analyze(c, lat, lon, radii, all_radii=True)
            dd, kind = diag.defect_distance_m(c, lat, lon)
            want = {"per_radius": [e["outcome"] for e in p["per_radius"]], "local": p["local"]["outcome"],
                    "radius_m": p["local"]["radius_m"], "edge_m": p["local"].get("edge_m"),
                    "defect_m": _r(p["local"].get("defect_m"), 2), "local_winding": p["local"].get("winding"),
                    "local_plus_far": p["local_plus_far"]["outcome"], "far_winding": p["local_plus_far"].get("winding"),
                    "defects": p["defects"], "segments": p["segments"], "source_id": p["source_id"],
                    "rank": p["rank"], "river": p["river"]}
            got = {"per_radius": [e["outcome"] for e in a["per_radius"]], "local": a["local"]["outcome"],
                   "radius_m": a["local"]["radius_m"], "edge_m": a["local"].get("edge_m"),
                   "defect_m": _r(dd, 2), "local_winding": a["local"].get("winding"),
                   "local_plus_far": a["local_plus_far"]["outcome"], "far_winding": a["local_plus_far"].get("winding"),
                   "defects": c["defects"], "segments": c["segments"], "source_id": c["source_id"],
                   "rank": c["depth_class"]["class_code"], "river": c["river_name"]}
            bad = [k for k in want if want[k] != got[k]]
            for k in want:
                fields[k + (" differs" if k in bad else " equal")] += 1
            if bad:
                mism.append({"lat": lat, "lon": lon, "zone_ref": p["zone_ref"], "fields": bad,
                             "phase_4c": {k: want[k] for k in bad}, "phase_4d": {k: got[k] for k in bad}})
            base_case = {"lat": lat, "lon": lon, "category": pt["category"], "zone_ref": p["zone_ref"],
                         "source_id": p["source_id"], "river": p["river"], "rank": p["rank"], "reason": p.get("reason"),
                         "reads": p.get("reads"), "winding": p["winding"], "parity_inside": p["parity_inside"]}
            reads = p.get("reads") or {}
            if reads and reads["make_valid"] != reads["even_odd"]:
                edge = diag.edge_distance_m(c, lat, lon, radii[-1])
                case_a.append(_class_a({**base_case, "edge_m": None if edge is None else round(edge, 4),
                                        "nearest_defect_m": _r(dd, 2), "nearest_defect_kind": kind,
                                        "local": a["local"]["outcome"]}))
            outs = [e["outcome"] for e in a["per_radius"]]
            first = next((i for i, o in enumerate(outs) if o in DECIDED), None)
            later = next((i for i, o in enumerate(outs) if first is not None and i > first and o == "defect_within_radius"), None)
            if first is not None and later is not None:
                e = a["per_radius"][later]
                case_b.append(_class_b({**base_case, "decided": outs[first], "decided_at_m": radii[first],
                                        "edge_m": a["per_radius"][first].get("edge_m"), "defect_enters_at_m": radii[later],
                                        "defect_m": e.get("defect_m"), "defect_kind": e.get("defect_kind"),
                                        "per_radius": outs}))
            regress.append({"lat": lat, "lon": lon, "zone_ref": p["zone_ref"], "per_radius": got["per_radius"],
                            "local_plus_far": got["local_plus_far"]})
        if (n + 1) % 100 == 0:
            log(f"diag compare: {n + 1}/{len(points)} points")
    return {"baseline": {"report": str(report_dir), "poc_version": summary.get("poc_version"),
                         "seed": summary["inputs"]["seed"], "radii_m": radii, "points": len(points)},
            "pairs_compared": pairs, "pairs_mismatched": len(mism), "fields": dict(sorted(fields.items())),
            "mismatches": mism[:50], "candidates_vs_baseline": dict(cand),
            "case_a": case_a, "case_a_summary": _summarize_a(case_a),
            "case_b": case_b, "case_b_summary": {**_summarize_b(case_b), "phase_4c_count_668": dict(phase_4c_rule),
                                                 "note": "Phase 4-C counted valid control pairs too; their contacts are "
                                                         "legal shell/hole touches and GEOS contains decides them"},
            "regression_cases": regress,
            "bench_points": [{"lat": pt["lat"], "lon": pt["lon"], "category": pt["category"],
                              "zone_refs": [p["zone_ref"] for p in pt["pairs"] if not p["control"]]}
                             for pt in points if any(not p["control"] for p in pt["pairs"])]}


def _class_a(c: dict[str, Any]) -> dict[str, Any]:
    """Why make_valid and the even-odd rule read the point differently."""
    w, parity = c["winding"], c["parity_inside"]
    if c["edge_m"] is not None and c["edge_m"] < ON_BOUNDARY_M:
        cls = "on_boundary: the point lies on the ring; GEOS contains excludes the boundary, the even-odd ray counts it"
    elif w not in (0, 1) or bool(w % 2) != parity:
        cls = "self_overlap: the ring covers the point more than once (winding number not 0/1)"
    else:
        cls = "near_defect: the readings split at a defect close to the point"
    return {**c, "class": cls, "machine_rule": "local outcome is undetermined" if c["local"] not in DECIDED
            else "LOCAL DECIDED (review)"}


def _class_b(c: dict[str, Any]) -> dict[str, Any]:
    reads = c.get("reads") or {}
    want = c["decided"] == "inside"
    agree = all(v == want for v in reads.values()) if reads else None
    core = reads.get("make_valid") == want and reads.get("even_odd") == want and (c["winding"] == 1) == want
    return {**c, "all_readings_agree_with_first": agree, "core_readings_agree_with_first": core,
            "readings_disagreeing": sorted(k for k, v in reads.items() if v != want),
            "defect_to_edge_ratio": None if not c.get("edge_m") else round(c["defect_m"] / c["edge_m"], 1)}


def _summarize_a(cases: list[dict[str, Any]]) -> dict[str, Any]:
    return {"pairs": len(cases), "by_class": dict(Counter(c["class"].split(":")[0] for c in cases)),
            "by_local_outcome": dict(Counter(c["local"] for c in cases)),
            "by_defect_kind": dict(Counter(c["nearest_defect_kind"] for c in cases)),
            "machine_undetermined": sum(c["local"] not in DECIDED for c in cases),
            "components": len({c["zone_ref"] for c in cases})}


def _summarize_b(cases: list[dict[str, Any]]) -> dict[str, Any]:
    def keep_rule(c):    # a candidate condition to keep the first result (not adopted)
        return c["defect_kind"] == "touch" and c["all_readings_agree_with_first"]
    return {"pairs": len(cases), "components": len({c["zone_ref"] for c in cases}),
            "by_decided": dict(Counter(c["decided"] for c in cases)),
            "by_defect_kind": dict(Counter(c["defect_kind"] for c in cases)),
            "by_first_and_defect_radius": dict(Counter(f"{c['decided_at_m']}->{c['defect_enters_at_m']}" for c in cases)),
            "all_readings_agree_with_first": dict(Counter(str(c["all_readings_agree_with_first"]) for c in cases)),
            "agree_by_defect_kind": dict(Counter(f"{c['defect_kind']} agree={c['all_readings_agree_with_first']}" for c in cases)),
            "would_keep_if_touch_and_all_agree": sum(keep_rule(c) for c in cases),
            "core_readings_agree_with_first (make_valid, even_odd, winding)": sum(c["core_readings_agree_with_first"] for c in cases),
            "readings_disagreeing": dict(Counter(",".join(c["readings_disagreeing"]) or "none" for c in cases)),
            "exterior_only_disagrees_by_decided": dict(Counter(c["decided"] for c in cases if "exterior_only" in c["readings_disagreeing"])),
            "defect_to_edge_ratio": _dist([c["defect_to_edge_ratio"] for c in cases if c["defect_to_edge_ratio"]]),
            "defect_to_edge_ratio_below_2": sum(1 for c in cases if c["defect_to_edge_ratio"] and c["defect_to_edge_ratio"] < 2),
            "defect_m": _dist([c["defect_m"] for c in cases])}


# --- regression cases and performance ------------------------------------------------------------------
def replay(diag: DiagIndex, cases: list[dict[str, Any]], radii: list[float]) -> dict[str, Any]:
    bad = []
    for c in cases:
        comp = diag.by_refs([c["zone_ref"]])[0]
        if comp is None:
            bad.append({**c, "got": "zone_ref missing"})
            continue
        a = diag.analyze(comp, c["lat"], c["lon"], radii, all_radii=True)
        got = {"per_radius": [e["outcome"] for e in a["per_radius"]], "local_plus_far": a["local_plus_far"]["outcome"]}
        if got != {k: c[k] for k in got}:
            bad.append({**c, "got": got})
    return {"cases": len(cases), "failed": len(bad), "examples": bad[:10]}


def _dist(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    v = sorted(values)
    return {"n": len(v), "median": round(statistics.median(v), 3), "p95": round(v[int(0.95 * (len(v) - 1))], 3),
            "max": round(v[-1], 3)}


def bench(index: Path, points: list[dict[str, Any]], radii: list[float], *, repeat: int = 3,
          same_point_repeat: int = 200) -> dict[str, Any]:
    """The light search alone (run it in its own process): open, then staged lookups."""
    rss0 = _rss_bytes()
    t0 = time.perf_counter()
    diag = DiagIndex(index)
    open_ms = (time.perf_counter() - t0) * 1000
    rss_open = _rss_bytes()
    passes = []
    for rep in range(repeat):
        times = []
        for p in points:
            t = time.perf_counter()
            diag.lookup(p["lat"], p["lon"], radii, zone_refs=p["zone_refs"])
            times.append((time.perf_counter() - t) * 1000)
        passes.append(_dist(times))
    given = next((p for p in points if p.get("category") == "given"), points[0])
    same = []
    for _ in range(same_point_repeat):
        t = time.perf_counter()
        diag.lookup(given["lat"], given["lon"], radii, zone_refs=given["zone_refs"])
        same.append((time.perf_counter() - t) * 1000)
    cand = []
    for p in points:
        t = time.perf_counter()
        diag.lookup(p["lat"], p["lon"], radii)
        cand.append((time.perf_counter() - t) * 1000)
    return {"points": len(points), "components_per_point": _dist([float(len(p["zone_refs"])) for p in points]),
            "rss_before_open_bytes": rss0, "open_ms": round(open_ms, 2), "rss_after_open_bytes": rss_open,
            "lookup_ms_first_pass": passes[0], "lookup_ms_later_passes": passes[1:],
            "lookup_ms_same_point": {**_dist(same), "point": [given["lat"], given["lon"]]},
            "lookup_ms_bbox_candidates": _dist(cand),
            "peak_rss_bytes": _rss_bytes(), "index_file_bytes": Path(index).stat().st_size,
            "note": "peak RSS of this process only: Python, numpy, SQLite page cache; no ZIP, no shapely"}


# --- CLI -----------------------------------------------------------------------------------------------
def _write(directory: Path, name: str, doc: Any) -> Path:
    path = Path(directory) / name
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def main(argv: list[str]) -> int:
    import argparse
    from hererisk.flood.settings import FloodSettingsError
    parser = argparse.ArgumentParser(prog="python -m hererisk.flood diag")
    sub = parser.add_subparsers(dest="cmd", required=True)
    default_index = os.environ.get("HERERISK_FLOOD_DIAG_INDEX")
    b = sub.add_parser("build", help="prepare the invalid components of a flood index (offline)")
    b.add_argument("--regions", type=Path, required=True)
    b.add_argument("--flood-index", type=Path, required=True)
    b.add_argument("--output", type=Path, default=default_index, required=default_index is None)
    for name, hlp in (("point", "diagnose points (diagnosis only)"), ("compare", "compare with a Phase 4-C report"),
                      ("bench", "measure the light search alone"), ("cases", "replay saved cases")):
        p = sub.add_parser(name, help=hlp)
        p.add_argument("--diag-index", type=Path, default=default_index, required=default_index is None)
        p.add_argument("--settings", type=Path)
        p.add_argument("--flood-index", type=Path, help="refuse a diagnosis index derived from another flood index")
        if name == "point":
            p.add_argument("--point", action="append", required=True, metavar="LAT,LON")
            p.add_argument("--zone-ref", action="append", default=None)
        if name == "compare":
            p.add_argument("--baseline", type=Path, required=True, help="a flood-local-analysis-* report directory")
            p.add_argument("--report-dir", type=Path)
        if name == "bench":
            p.add_argument("--points", type=Path, required=True, help="bench-points.json written by compare")
            p.add_argument("--repeat", type=int, default=3)
        if name == "cases":
            p.add_argument("--cases", type=Path, required=True, help="regression-cases.json written by compare")
    args = parser.parse_args(argv)
    try:
        radii = setting_radii(load_settings(getattr(args, "settings", None))["local_analysis"])
    except FloodSettingsError as exc:
        sys.stderr.write(f"flood diag: {exc}\n")
        return 2
    log = lambda m: sys.stderr.write(m + "\n")    # noqa: E731
    try:
        if args.cmd == "build":
            r = build(args.regions, args.flood_index, args.output, log=log)
            print(json.dumps({k: r[k] for k in ("built_at", "counts", "checks", "prepare_seconds", "seconds",
                                                "file_bytes", "peak_rss_bytes")}, ensure_ascii=False, indent=1))
            return 0
        diag = DiagIndex(args.diag_index, flood_index=args.flood_index)
        if args.cmd == "point":
            for p in args.point:
                try:
                    lat, lon = (float(v) for v in p.split(","))
                except ValueError:
                    sys.stderr.write("flood diag: --point must be LAT,LON\n")
                    return 2
                print(json.dumps(diag.lookup(lat, lon, radii, zone_refs=args.zone_ref), ensure_ascii=False, indent=1))
            return 0
        if args.cmd == "compare":
            base_radii = setting_radii(_baseline(args.baseline)[0]["inputs"]["local_analysis"])
            if base_radii != radii:
                sys.stderr.write("flood diag: the radii differ from the baseline report's settings\n")
                return 2
            t0 = time.time()
            rep = compare(diag, args.baseline, log=log)
            rep["seconds"] = round(time.time() - t0, 1)
            print(json.dumps({k: rep[k] for k in ("baseline", "pairs_compared", "pairs_mismatched", "fields",
                                                  "candidates_vs_baseline", "case_a_summary", "case_b_summary",
                                                  "seconds")}, ensure_ascii=False, indent=1))
            if args.report_dir:
                stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                out = Path(args.report_dir) / f"flood-diag-compare-{stamp}"
                out.mkdir(parents=True, exist_ok=False)
                _write(out, "summary.json", {k: v for k, v in rep.items() if k not in
                                             ("case_a", "case_b", "regression_cases", "bench_points")}
                       | {"diag_index_meta": diag.meta})
                _write(out, "cases-a-make_valid-vs-even_odd.json", rep["case_a"])
                _write(out, "cases-b-radius-dependence.json", rep["case_b"])
                _write(out, "regression-cases.json", rep["regression_cases"])
                for tag, cases in (("a", rep["case_a"]), ("b", rep["case_b"])):
                    keys = {(c["lat"], c["lon"], c["zone_ref"]) for c in cases}
                    _write(out, f"regression-cases-{tag}.json", [c for c in rep["regression_cases"]
                                                                  if (c["lat"], c["lon"], c["zone_ref"]) in keys])
                _write(out, "bench-points.json", rep["bench_points"])
                print(f"report: {out}")
            return 1 if rep["pairs_mismatched"] or rep["candidates_vs_baseline"].get("MISSING") else 0
        if args.cmd == "bench":
            points = json.loads(args.points.read_text(encoding="utf-8"))
            diag.db.close()
            print(json.dumps(bench(args.diag_index, points, radii, repeat=args.repeat), ensure_ascii=False, indent=1))
            return 0
        if args.cmd == "cases":
            r = replay(diag, json.loads(args.cases.read_text(encoding="utf-8")), radii)
            print(json.dumps(r, ensure_ascii=False, indent=1))
            return 1 if r["failed"] else 0
    except DiagIndexError as exc:
        sys.stderr.write(f"flood diag: {exc}\n")
        return 3
    except Exception as exc:    # noqa: BLE001
        sys.stderr.write(f"flood diag: ERROR ({type(exc).__name__}: {exc})\n")
        return 3
    return 2
