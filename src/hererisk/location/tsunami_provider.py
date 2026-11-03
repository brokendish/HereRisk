"""TsunamiProvider (Phase 4-M): the Location API ``hazards.tsunami`` section from registered official
tsunami inundation assumptions (国土数値情報 A40), the first provider on the shared Polygon Engine.

Start-up (any failure -> the server does not start; nothing is served from unverified data):

* the registration (``tsunami_sources`` in the regions file) must equal the one the index was built
  from (``python -m hererisk.tsunami build``), the index must be ``complete``, and each registered ZIP
  and N03 file must have the SHA-256 recorded at build time
* the service region of each source is the union of its prefectures' N03 polygons

Per point (docs/api/tsunami-api-mvp-contract-v0.1.md):

* the point's relation to each source's service region: ``inside`` / ``boundary`` (within 10 m of the
  region's outer edge, either side) / outside. Sources whose region is far are not listed
* the geometry is the shared engine's (``hererisk.common.polygon.relation.ComponentIndex``): only
  ``valid`` components are evaluated (GEOS, no search radius); the others are ``pending_geometry`` in
  their bounding box. This module only maps the engine's features to the source's attributes
* ``zones``: components that contain the point, each with its source's ``A40_003`` text unchanged
* ``boundary_contacts``: components whose edge the point lies on (not a confirmed match)
* ``unknowns``: pending components (invalid / not verified) whose bounding box holds the point. Never
  dropped, never read as "no zone", no depth class
* nothing is merged, ranked, reduced to a maximum or compared across components or sources

Status (same rules as the flood section):

    no listed source                     -> not_available (outside_service_region)
    a source has zones                   -> available (results = every zone of every source)
    no zones; unknowns / boundary_contacts / region boundary -> unknown (reasons listed)
    every listed source searched, inside, nothing found      -> no_match (NOT "no tsunami": A40 has no
                                                                assessed extent; the source cautions
                                                                that real tsunamis can be larger)
    the engine would list more than MAX_ITEMS   -> error (tsunami_response_limit_exceeded)
    the engine fails                     -> raises (the orchestrator answers provider_failed)
"""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Any

import shapely

from hererisk.common.polygon import relation
from hererisk.location.address_regions import load_regions
from hererisk.location.model import AVAILABLE, NO_MATCH, NOT_AVAILABLE, UNKNOWN, error_section
from hererisk.location.n03_municipality import BOUNDARY_TOLERANCE_M, _read_file as read_n03
from hererisk.tsunami import a40
from hererisk.tsunami.errors import TsunamiIndexError
from hererisk.tsunami.index import LIMITATIONS, read_meta
from hererisk.tsunami.registry import (CATEGORY, CATEGORY_LABEL, DEFAULT_LEDGER, load_ledger, load_tsunami_sources,
                                       registration_view)

MAX_ITEMS = 500
NO_MATCH_SCOPE_NOTICE = ("登録されている津波浸水想定の区域に該当しませんでした。原典は想定を行った範囲を示していないため、"
                         "津波の影響がないことを意味しません。" + a40.SOURCE_CAUTION)
DATA_USE_NOTICE = "公式データの利用条件は確認中です。ローカルでの検証に限ります（一般公開の承認はありません）。"


def _tol_deg(lat: float) -> float:
    return BOUNDARY_TOLERANCE_M / (111320.0 * max(0.01, math.cos(math.radians(lat))))


class _Region:
    """The service region (N03 union) of one source: inside / boundary (10 m band) / None."""

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


class TsunamiProvider:
    id = "tsunami-a40-local"

    def __init__(self, regions_file: Path, index: Path, *, ledger_file: Path = DEFAULT_LEDGER) -> None:
        regions_file = Path(regions_file).expanduser()
        sources = load_tsunami_sources(regions_file)
        if not sources:
            raise TsunamiIndexError("the regions file has no tsunami_sources")
        meta = read_meta(index)
        if meta["registration"] != [registration_view(s) for s in sources]:
            raise TsunamiIndexError("the tsunami index was built from another registration; rebuild it")
        for s in sources:
            for f in s["files"]:
                if a40.sha256_file(f["path"]) != (meta["files"].get(f["file_name"]) or {}).get("sha256"):
                    raise TsunamiIndexError("a registered tsunami file differs from the indexed one; rebuild the index")
        n03 = {r["prefecture_code"]: r["address_n03"] for r in load_regions(regions_file)}
        region_polys = {p: [g for _, g, _ in read_n03(n03[p], p)[1]]
                        for p in sorted({p for s in sources for p in s["service_prefectures"]})}
        ledger = load_ledger(ledger_file)
        self._sources = []
        for s in sources:
            usage = [((ledger.get(f["ledger_entry"]) or {}).get("usage_terms") or {}) for f in s["files"]]
            statuses = sorted({u.get("status", "unknown") for u in usage})
            approved = all(u.get("status") == "approved" and u.get("approval_ref") for u in usage)
            editions = sorted({meta["files"][f["file_name"]]["spec_edition"] for f in s["files"]})
            public = {"source_id": s["source_id"], "organization": s["organization"], "title": s["title"],
                      "category": CATEGORY, "category_label": CATEGORY_LABEL, "data_version": s["data_year"],
                      "spec_edition": editions[0] if len(editions) == 1 else editions,
                      "attribution": {"text": a40.ATTRIBUTION}, "source_caution": a40.SOURCE_CAUTION,
                      "data_use": {"scope": "local_verification_only",
                                   "usage_terms": statuses[0] if len(statuses) == 1 else statuses,
                                   "public_approval": "approved" if approved else "unconfirmed"}}
            region = _Region([g for p in s["service_prefectures"] for g in region_polys[p]])
            self._sources.append((s["source_id"], public, region))
        self._attrs: dict[str, tuple[str, str]] = {}
        db = sqlite3.connect(f"file:{Path(index)}?mode=ro", uri=True)
        try:
            rows = db.execute("SELECT source_id, zone_ref, validity, detail, kind, depth_label, wkb FROM components "
                              "ORDER BY rowid")

            def candidates():
                for sid, ref, validity, detail, kind, label, wkb in rows:
                    self._attrs[ref] = (label, kind)
                    yield relation.Candidate(sid, ref, wkb, validity, detail)
            self._index = relation.ComponentIndex(candidates())
        except sqlite3.Error as exc:
            raise TsunamiIndexError("tsunami index unreadable") from exc
        finally:
            db.close()
        self.meta = {"built_at": meta["built_at"], "validator": meta["validator"], "limitations": meta["limitations"]}

    def lookup(self, lat: float, lon: float) -> dict[str, Any]:
        pt = shapely.Point(lon, lat)                       # GeoJSON axis order: x = lon, y = lat
        listed = [(sid, public, rel) for sid, public, region in self._sources
                  if (rel := region.relation(pt, lat)) is not None]
        base = {"provider": self.id, "synthetic": False, "candidate_scope": "registered_sources_in_service_region",
                "candidate_completeness": "not_guaranteed", "limitations": LIMITATIONS,
                "identifiers": "provisional_local", "data_use_notice": DATA_USE_NOTICE}
        if not listed:
            return {**base, "status": NOT_AVAILABLE, "results": None, "reason": "outside_service_region"}
        found = self._index.search(lon, lat, max_features=MAX_ITEMS)
        if found["status"] == relation.LIMIT_EXCEEDED:
            return error_section(self.id, "tsunami_response_limit_exceeded")
        if not found["complete"]:
            raise TsunamiIndexError("the tsunami search did not complete")    # -> provider_failed, never "no zone"
        by_source: dict[str, dict[str, list]] = {sid: {"zones": [], "boundary_contacts": [], "unknowns": []}
                                                 for sid, _, _ in listed}
        for f in found["features"]:
            if f["source_id"] not in by_source:
                continue                                   # a source whose service region is not here
            label, kind = self._attrs[f["feature_ref"]]
            if f["evaluation"] == relation.PENDING:
                by_source[f["source_id"]]["unknowns"].append(
                    {"zone_ref": f["feature_ref"], "reason": f["geometry_state"]["validity"],
                     "invalid_kind": kind, "unknown_level": "L1"})
            else:
                key = "zones" if f["relation"] == relation.INSIDE else "boundary_contacts"
                by_source[f["source_id"]][key].append(
                    {"zone_ref": f["feature_ref"], "original_class": {"code": None, "label": label},
                     "source_attribute": a40.DEPTH_ATTRIBUTE})
        sources = [{**public, "service_region_relation": rel, "assessed_extent_relation": "unknown", **by_source[sid]}
                   for sid, public, rel in listed]
        summary = {"sources_total": len(sources), "sources_with_zones": sum(1 for s in sources if s["zones"]),
                   "sources_with_unknown_or_boundary": sum(1 for s in sources if s["unknowns"] or s["boundary_contacts"])}
        region_state = "inside" if all(s["service_region_relation"] == "inside" for s in sources) else "region_boundary"
        out = {**base, "region_state": region_state, "summary": summary, "source_caution": a40.SOURCE_CAUTION,
               "searched_sources": [s["source_id"] for s in sources], "sources": sources}
        results = [{"source": {k: s[k] for k in ("source_id", "organization", "title", "data_version")},
                    "feature_ref": z["zone_ref"], "original_class": z["original_class"],
                    "source_attribute": z["source_attribute"]}
                   for s in sources for z in s["zones"]]
        if results:
            return {**out, "status": AVAILABLE, "results": results}
        reasons = [r for r, hit in (("pending_geometry_zone", any(s["unknowns"] for s in sources)),
                                    ("zone_boundary_contact", any(s["boundary_contacts"] for s in sources)),
                                    ("service_region_boundary", region_state == "region_boundary")) if hit]
        if reasons:
            return {**out, "status": UNKNOWN, "results": None, "reasons": reasons}
        return {**out, "status": NO_MATCH, "results": [], "scope_notice": NO_MATCH_SCOPE_NOTICE}
