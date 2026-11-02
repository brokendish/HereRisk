"""FloodProvider (Phase 4-A): the Location API ``hazards.flood`` section from registered official
flood inundation data (国土数値情報 A31a), searched per source and independently.

Start-up (any failure -> the server does not start; nothing is served from unverified data):

* the registration (``flood_sources`` in the regions file) must equal the one the index was built
  from (``python -m hererisk.flood build``); each registered ZIP and N03 file must have the SHA-256
  recorded in the index
* the service region of each source is the union of its prefectures' N03 polygons

Per point (Flood Official Data Presentation contract chapters 6-8; Flood API MVP contract 5-6):

* the point's relation to each source's service region: ``inside`` / ``boundary`` (within 10 m of
  the region's outer edge, either side) / outside. Sources whose region is far are not listed
* every listed source is searched on its own; nothing is compared, merged, ranked or reduced
* ``zones``: usable components that contain the point (each one separately, its source class kept)
* ``boundary_contacts``: usable components whose edge the point lies on (not a confirmed match)
* ``unknowns``: pending components (invalid / involved in a feature-level invalidity) whose bounding
  box contains the point, boundary included (L1). They are never dropped and never read as "no zone"

Location API status:

    no listed source                     -> not_available (outside_service_region)
    a source has zones                   -> available (results = every zone of every source)
    no zones; unknowns / boundary_contacts / region boundary -> unknown (reasons listed)
    every listed source searched, inside, nothing found      -> no_match (NOT a statement of safety;
                                                                A31a has no assessed extent)
    the answer would exceed MAX_ITEMS    -> error (flood_response_limit_exceeded), never a partial list

A search failure of one source raises, so the whole section becomes ``error`` (no partial success).
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
from pathlib import Path
from typing import Any

import shapely

from hererisk.data_inventory.inventory import DEFAULT_LEDGER, load_ledger
from hererisk.flood import a31a
from hererisk.flood.errors import FloodIndexError
from hererisk.flood.index import LIMITATIONS, read_meta
from hererisk.flood.registry import CATEGORIES, SCENARIO_LABELS, load_flood_sources, registration_view
from hererisk.location.address_regions import load_regions
from hererisk.location.model import AVAILABLE, NO_MATCH, NOT_AVAILABLE, UNKNOWN, error_section
from hererisk.location.n03_municipality import BOUNDARY_TOLERANCE_M, _read_file as read_n03

MAX_ITEMS = 500
NO_MATCH_SCOPE_NOTICE = ("登録されている浸水想定区域に該当しませんでした。原典は評価済みの範囲を示していないため、"
                         "浸水しないことを意味しません。登録されていない公式情報（内水・高潮・他の想定等）もありえます。")
DATA_USE_NOTICE = "公式データの利用条件は確認中です。ローカルでの検証に限ります（一般公開の承認はありません）。"


def _tol_deg(lat: float) -> float:
    return BOUNDARY_TOLERANCE_M / (111320.0 * max(0.01, math.cos(math.radians(lat))))


class _Region:
    def __init__(self, polygons: list[Any]) -> None:
        self.geom = shapely.union_all(polygons)
        self.edge = self.geom.boundary
        shapely.prepare(self.geom)
        shapely.prepare(self.edge)

    def relation(self, pt: Any, lat: float) -> str | None:
        tol = _tol_deg(lat)
        if not shapely.dwithin(self.geom, pt, tol):
            return None
        if self.geom.contains(pt) and not shapely.dwithin(self.edge, pt, tol):
            return "inside"
        return "boundary"


_COLUMNS = "zone_ref, reason, product_ref, river_code, river_name, manager, depth_class"


class _Source:
    """One registered source. In memory: usable geometries (STRtree), pending bounding boxes and the
    index row ids. The attributes of a hit are read from the read-only index (a few rows per point)."""

    def __init__(self, reg: dict[str, Any], db: "_Index", ledger: dict[str, dict[str, Any]], region: _Region) -> None:
        self.reg, self.region, self._db = reg, region, db
        self.public = {"source_id": reg["source_id"], "organization": reg["organization"], "title": reg["title"],
                       "category": reg["category"], "category_label": CATEGORIES[reg["category"]],
                       "scenario": reg["scenario"], "scenario_label": SCENARIO_LABELS[reg["scenario"]],
                       "data_version": reg["data_year"], "attribution": {"text": a31a.ATTRIBUTION}}
        usage = [((ledger.get(f["ledger_entry"]) or {}).get("usage_terms") or {}) for f in reg["files"]]
        statuses = sorted({u.get("status", "unknown") for u in usage})
        approved = all(u.get("status") == "approved" and u.get("approval_ref") for u in usage)
        self.data_use = {"scope": "local_verification_only", "usage_terms": statuses[0] if len(statuses) == 1 else statuses,
                         "public_approval": "approved" if approved else "unconfirmed"}
        self._ids: list[int] = []
        self._geoms: list[Any] = []
        self._pending: list[tuple[int, float, float, float, float]] = []
        cursor = db.conn.execute("SELECT rowid, usable, minx, miny, maxx, maxy, wkb FROM components "
                                 "WHERE source_id = ? ORDER BY rowid", (reg["source_id"],))
        while batch := cursor.fetchmany(5000):
            wkb = []
            for rowid, usable, minx, miny, maxx, maxy, blob in batch:
                if usable:
                    self._ids.append(rowid)
                    wkb.append(blob)
                else:
                    self._pending.append((rowid, minx, miny, maxx, maxy))
            if wkb:
                self._geoms.extend(shapely.from_wkb(wkb))
        self._tree = shapely.STRtree(self._geoms)
        self._ptree = shapely.STRtree([shapely.box(*r[1:]) for r in self._pending])

    def search(self, pt: Any, x: float, y: float, relation: str) -> dict[str, Any]:
        zones, contacts, unknowns = [], [], []
        for i in self._tree.query(pt):
            g = self._geoms[int(i)]
            if g.contains(pt):
                zones.append(self._ids[int(i)])
            elif g.intersects(pt):
                contacts.append(self._ids[int(i)])
        for i in self._ptree.query(pt):
            rowid, minx, miny, maxx, maxy = self._pending[int(i)]
            if minx <= x <= maxx and miny <= y <= maxy:     # boundary included
                unknowns.append(rowid)
        rows = self._db.rows(zones + contacts + unknowns)
        key = lambda z: z["zone_ref"]   # noqa: E731
        return {**self.public, "service_region_relation": relation, "assessed_extent_relation": "unknown",
                "data_use": self.data_use,
                "zones": sorted((_item(rows[r]) for r in zones), key=key),
                "unknowns": sorted(({**_item(rows[r], depth=False), "reason": rows[r][1], "unknown_level": "L1"}
                                    for r in unknowns), key=key),
                "boundary_contacts": sorted((_item(rows[r]) for r in contacts), key=key)}


def _item(r: tuple, depth: bool = True) -> dict[str, Any]:
    item = {"zone_ref": r[0], "product_ref": r[2], "river_code": r[3], "river_name_in_source": r[4],
            "river_manager_in_source": r[5]}
    if depth:
        item["depth_class"] = json.loads(r[6])
    return item


class _Index:
    """The read-only index connection, shared by the request threads under a lock."""

    def __init__(self, path: Path) -> None:
        self.conn = sqlite3.connect(f"file:{Path(path)}?mode=ro", uri=True, check_same_thread=False)
        self._lock = threading.Lock()

    def rows(self, rowids: list[int]) -> dict[int, tuple]:
        if not rowids:
            return {}
        with self._lock:
            got = {r[0]: r[1:] for r in self.conn.execute(
                f"SELECT rowid, {_COLUMNS} FROM components WHERE rowid IN ({','.join('?' * len(rowids))})", rowids)}
        if len(got) != len(set(rowids)):
            raise FloodIndexError("flood index rows missing")   # the whole section becomes an error
        return got


class FloodProvider:
    id = "flood-a31a-local"

    def __init__(self, regions_file: Path, index: Path, *, ledger_file: Path = DEFAULT_LEDGER) -> None:
        regions_file = Path(regions_file).expanduser()
        sources = load_flood_sources(regions_file)
        if not sources:
            raise FloodIndexError("the regions file has no flood_sources")
        meta = read_meta(index)
        if meta["registration"] != [registration_view(s) for s in sources]:
            raise FloodIndexError("the flood index was built from another registration; rebuild it")
        for s in sources:
            for f in s["files"]:
                if a31a.sha256_file(f["path"]) != meta["zip_sha256"].get(f["file_name"]):
                    raise FloodIndexError("a registered flood file differs from the indexed one; rebuild the index")
        n03 = {r["prefecture_code"]: r["address_n03"] for r in load_regions(regions_file)}
        region_polys: dict[str, list[Any]] = {}
        for pref in sorted({p for s in sources for p in s["service_prefectures"]}):
            if a31a.sha256_file(n03[pref]) != (meta["n03"].get(pref) or {}).get("sha256"):
                raise FloodIndexError("a service-region N03 file differs from the indexed one; rebuild the index")
            region_polys[pref] = [g for _, g, _ in read_n03(n03[pref], pref)[1]]
        ledger = {e.get("entry_id"): e for e in load_ledger(ledger_file)}
        self._index = _Index(index)
        self._sources = [_Source(s, self._index, ledger,
                                 _Region([g for p in s["service_prefectures"] for g in region_polys[p]]))
                         for s in sources]
        self.meta = {"built_at": meta["built_at"], "validator": meta["validator"], "limitations": meta["limitations"]}

    def lookup(self, lat: float, lon: float) -> dict[str, Any]:
        pt = shapely.Point(lon, lat)                       # GeoJSON axis order: x = lon, y = lat
        listed = [(s, rel) for s in self._sources if (rel := s.region.relation(pt, lat)) is not None]
        base = {"provider": self.id, "synthetic": False, "candidate_scope": "registered_sources_in_service_region",
                "candidate_completeness": "not_guaranteed", "limitations": LIMITATIONS,
                "identifiers": "provisional_local", "data_use_notice": DATA_USE_NOTICE}
        if not listed:
            return {**base, "status": NOT_AVAILABLE, "results": None, "reason": "outside_service_region"}
        sources = [s.search(pt, lon, lat, rel) for s, rel in listed]
        if sum(len(s[k]) for s in sources for k in ("zones", "unknowns", "boundary_contacts")) > MAX_ITEMS:
            return error_section(self.id, "flood_response_limit_exceeded")
        summary = {"sources_total": len(sources), "sources_with_zones": sum(1 for s in sources if s["zones"]),
                   "sources_with_unknown_or_boundary": sum(1 for s in sources if s["unknowns"] or s["boundary_contacts"])}
        region_state = "inside" if all(s["service_region_relation"] == "inside" for s in sources) else "region_boundary"
        out = {**base, "region_state": region_state, "summary": summary,
               "searched_sources": [s["source_id"] for s in sources], "sources": sources}
        results = [{"source": {k: s[k] for k in ("source_id", "organization", "title", "data_version", "scenario")},
                    "feature_ref": z["zone_ref"], "product_ref": z["product_ref"],
                    "original_class": {"code": z["depth_class"]["class_code"], "label": z["depth_class"]["label"]},
                    "depth_class": z["depth_class"], "river_code": z["river_code"],
                    "river_name_in_source": z["river_name_in_source"]}
                   for s in sources for z in s["zones"]]
        if results:
            return {**out, "status": AVAILABLE, "results": results}
        reasons = [r for r, hit in (("pending_geometry_zone", any(s["unknowns"] for s in sources)),
                                    ("zone_boundary_contact", any(s["boundary_contacts"] for s in sources)),
                                    ("service_region_boundary", region_state == "region_boundary")) if hit]
        if reasons:
            return {**out, "status": UNKNOWN, "results": None, "reasons": reasons}
        return {**out, "status": NO_MATCH, "results": [], "scope_notice": NO_MATCH_SCOPE_NOTICE}
