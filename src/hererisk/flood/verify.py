"""Flood verification against the official source (Phase 4-B).

    python -m hererisk.flood verify --regions <regions.json> --index <index.sqlite>
        [--source ID ...] [--per-category N] [--per-rank N] [--seed S] [--point LAT,LON ...]
        [--report-dir DIR]

Independence: the expected results are computed here from the official ZIPs (and the N03 ZIPs)
with this module's own reader. No function of the index builder (``hererisk.flood.a31a`` parsing,
``hererisk.flood.index``) computes an expected value: own member selection, own feature parsing
(``shapely.geometry.shape``), own depth class table, own feature-level invalidity test, own region test. The SQLite index and the
Flood Provider are read only as the *actual* side. Shared on both sides, and so not independently
checked: the registration file (input), GEOS (the only validator), and the zone_ref formula (an
identifier recomputed from the documented rule).

Steps:

1. provenance: ZIP SHA-256 now / in the index, registration in the index, program and GEOS versions
2. reconciliation (every feature of every registered file): counts per product, components,
   validity, every index row against the source (attributes, class, bounding box, exact geometry),
   and completeness: every feature that can matter for a point within 10 m of the service region
   must be in the index (extra features are allowed and counted)
3. points: sampled from the source with a fixed seed per category, plus ``--point``; expected result
   from the source, actual from the Flood Provider; verdict per point

Verdicts: PASS (matches what the source determines), FAIL (does not), INDETERMINATE (matches, but an
invalid component's area covers the point, so the source itself does not determine the answer),
OUT_OF_SCOPE (outside every registered service region, and the provider says so), ERROR (the check
itself failed). INDETERMINATE is never counted as PASS.

For INDETERMINATE points the report adds, for diagnosis only, how three interpretations of the
invalid ring read the point (even-odd rule, GEOS make_valid, exterior ring only). They never decide a
verdict and are never used as a depth.
"""

from __future__ import annotations

import hashlib
import json
import math
import platform
import random
import re
import sqlite3
import sys
import time
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import shapely
from shapely.geometry import shape

from hererisk.flood.registry import load_flood_sources, registration_view
from hererisk.location.address_regions import load_regions

VERIFY_VERSION = "flood-verify-v0.1"
SCENARIO_CATEGORY = {"maximum": "20"}          # A31a member name category of each scenario
FOLDER_WORD = {"maximum": "想定最大規模"}
# 浸水ランクコード (KS-PS-A31a 第4.3版 / water_depth_code), written out again on purpose
RANK_LABELS = {"1": "0～0.5m未満", "2": "0.5～3.0m未満", "3": "3.0～5.0m未満", "4": "5.0～10.0m未満",
               "5": "10.0～20.0m未満", "6": "20.0m以上"}
BOUNDARY_M = 10.0
CATEGORIES = ("valid_interior", "valid_overlap", "rank_differs", "multi_source", "hole", "boundary",
              "pending_bbox", "region_no_zone", "outside_region", "region_edge")
VERDICTS = ("PASS", "FAIL", "INDETERMINATE", "OUT_OF_SCOPE", "ERROR")
SAMPLE_MAX_VERTICES = 20000      # sampling geometry operations skip huge polygons (they are still checked)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _tol(lat: float) -> float:
    return BOUNDARY_M / (111320.0 * max(0.01, math.cos(math.radians(lat))))


def _zone_ref(zip_sha: str, member: str, fi: int, pi: int) -> str:
    """The documented local zone_ref rule (Location API contract 8.5), recomputed here."""
    doc = {"domain": "hererisk-flood-zone-ref-local-v0", "polygon_index": pi,
           "record_key": {"feature_index": fi, "zip_member": member, "zip_sha256": zip_sha}}
    raw = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "loc-zn-" + hashlib.sha256(raw).hexdigest()[:20]


def _reason_class(reason: str) -> str:
    return re.sub(r"\[.*\]$", "", reason).strip()


# --- the official source, read independently -----------------------------------------------------
class Comp:
    __slots__ = ("source_id", "member", "fi", "pi", "geom", "valid", "involved", "props", "ref", "nverts")

    def __init__(self, **kw: Any) -> None:
        for k, v in kw.items():
            setattr(self, k, v)

    @property
    def usable(self) -> bool:
        return self.valid and not self.involved

    @property
    def rank(self) -> str:
        return str(self.props["A31a_205"])


def _members(z: zipfile.ZipFile, scenario: str) -> list[tuple[str, str]]:
    """(raw name, normalized name) of the scenario: folder word in the folder, category in the name."""
    cat, word = SCENARIO_CATEGORY[scenario], FOLDER_WORD[scenario]
    out = []
    for raw in z.namelist():
        norm = unicodedata.normalize("NFC", raw.replace("\\", "/"))
        folder, _, base = norm.rpartition("/")
        if base.startswith(f"A31a-{cat}-") and base.endswith(".geojson"):
            if not folder.endswith(word):
                raise ValueError("a scenario member outside the scenario folder")
            out.append((raw, norm))
        elif word in folder and base.endswith(".geojson"):
            raise ValueError("a member in the scenario folder with another category")
    return sorted(out, key=lambda m: m[1])


def _features(z: zipfile.ZipFile, raw: str, counter: dict[str, int]):
    """Every feature of one member, one at a time. ``counter["markers"]`` counts '"type":"Feature"' in
    the bytes independently of the parsing, so a feature the parser skipped would show up."""
    with z.open(raw) as fh:
        for line in fh:
            counter["markers"] += line.count(b'"type":"Feature"') + line.count(b'"type": "Feature"')
            s = line.strip().rstrip(b",")
            if s.startswith(b"{") and b'"Feature"' in s and b'"FeatureCollection"' not in s:
                obj = json.loads(s)
                if obj.get("type") == "Feature":
                    yield obj


class SourceData:
    def __init__(self, reg: dict[str, Any], region: Any) -> None:
        self.reg, self.region = reg, region
        self.sid = reg["source_id"]
        self.files: list[dict[str, Any]] = []
        self.products: dict[str, dict[str, Any]] = {}
        self.comps: list[Comp] = []              # components near the service region (all kinds)
        self.required: set[tuple[str, int]] = set()   # features that must be in the index
        self.all_features: set[tuple[str, int]] = set()

    def scan(self, log) -> None:
        for f in self.reg["files"]:
            sha = _sha256(f["path"])
            self.files.append({"file_name": f["file_name"], "sha256": sha, "size": f["path"].stat().st_size})
            with zipfile.ZipFile(f["path"]) as z:
                for raw, norm in _members(z, self.reg["scenario"]):
                    log(f"verify scan: {self.sid}: {norm.rsplit('/', 1)[-1]}")
                    counter = {"markers": 0}
                    p = {"file_name": f["file_name"], "zip_sha256": sha, "features": 0,
                         "feature_markers": 0, "components": 0, "invalid": 0, "involved": 0,
                         "multipolygon": 0, "reasons": Counter(), "ranks": Counter(), "managers": Counter(),
                         "rivers": Counter(), "rank_types": Counter()}
                    self.products[norm] = p
                    for fi, feat in enumerate(_features(z, raw, counter)):
                        p["features"] += 1
                        self._feature(norm, sha, fi, feat, p)
                    p["feature_markers"] = counter["markers"]
                    p["reasons"] = dict(p["reasons"])
                    for k in ("ranks", "managers", "rivers", "rank_types"):
                        p[k] = dict(p[k])

    def _feature(self, member, sha, fi, feat, p) -> None:
        props = feat["properties"]
        g = shape(feat["geometry"])
        parts = list(g.geoms) if g.geom_type == "MultiPolygon" else [g]
        p["components"] += len(parts)
        p["multipolygon"] += g.geom_type == "MultiPolygon"
        p["ranks"][str(props.get("A31a_205"))] += 1
        p["rank_types"][type(props.get("A31a_205")).__name__] += 1
        p["managers"][f"{props.get('A31a_203')} {props.get('A31a_204')}"] += 1
        p["rivers"][f"{props.get('A31a_201')} {props.get('A31a_202')}"] += 1
        valid = [bool(c.is_valid) for c in parts]
        involved = [False] * len(parts)
        if len(parts) > 1 and not g.is_valid:
            # own method: a valid part is involved if it shares area or a line with another valid part
            for i in range(len(parts)):
                for j in range(i + 1, len(parts)):
                    if valid[i] and valid[j] and parts[i].intersects(parts[j]):
                        inter = parts[i].intersection(parts[j])
                        if inter.area > 0 or any(t.geom_type in ("LineString", "MultiLineString")
                                                 for t in getattr(inter, "geoms", [inter])):
                            involved[i] = involved[j] = True
        for i, c in enumerate(parts):
            if not valid[i]:
                p["invalid"] += 1
                p["reasons"][_reason_class(shapely.is_valid_reason(c))] += 1
            elif involved[i]:
                p["involved"] += 1
        key = (member, fi)
        self.all_features.add(key)
        if not self.region.near(shapely.box(*g.bounds)):
            return
        for i, c in enumerate(parts):
            area = c if valid[i] and not involved[i] else shapely.box(*c.bounds)
            if key not in self.required and self.region.needed(area):
                self.required.add(key)
            self.comps.append(Comp(source_id=self.sid, member=member, fi=fi, pi=i, geom=c, valid=valid[i],
                                   involved=involved[i], props=props, ref=_zone_ref(sha, member, fi, i),
                                   nverts=len(c.exterior.coords) + sum(len(r.coords) for r in c.interiors)))

    def finish(self) -> None:
        self.usable = [c for c in self.comps if c.usable]
        self.pending = [c for c in self.comps if not c.usable]
        self.tree = shapely.STRtree([c.geom for c in self.usable])
        self.ptree = shapely.STRtree([shapely.box(*c.geom.bounds) for c in self.pending])


class Region:
    def __init__(self, n03_paths: list[Path]) -> None:
        polys = []
        for path in n03_paths:
            with zipfile.ZipFile(path) as z:
                names = [n for n in z.namelist() if n.endswith(".geojson")]
                if len(names) != 1:
                    raise ValueError("N03 ZIP must hold one GeoJSON")
                for f in json.loads(z.read(names[0]))["features"]:
                    polys.append(shape(f["geometry"]))
        self.geom = shapely.union_all(polys)
        self.edge = self.geom.boundary
        self._boxes = shapely.STRtree([shapely.box(*g.bounds) for g in polys])   # municipality bounding boxes
        self.need_deg = _tol(self.geom.bounds[1]) * 1.5   # the widest 10 m band in the region, widened
        parts = list(getattr(self.geom, "geoms", [self.geom]))
        self.main = max(parts, key=lambda g: g.area)     # sampling area (the largest part; no named place)
        for g in (self.geom, self.edge):
            shapely.prepare(g)

    def near(self, geom: Any) -> bool:
        """Kept for the checks: within ~1 km of the region, or within ~100 m of a municipality's bounding
        box (the contract's L1 rule keeps such pending components in the index; a wider net than the
        index's own tolerance, so every index row has its source component here)."""
        if shapely.dwithin(self.geom, geom, 0.01):
            return True
        minx, miny, maxx, maxy = geom.bounds
        return len(self._boxes.query(shapely.box(minx - 0.001, miny - 0.001, maxx + 0.001, maxy + 0.001))) > 0

    def needed(self, geom: Any) -> bool:        # within the 10 m band: must be in the index
        return bool(shapely.dwithin(self.geom, geom, self.need_deg))

    def relation(self, pt: Any, lat: float) -> str | None:
        t = _tol(lat)
        if self.edge.distance(pt) <= t:
            return "boundary"
        return "inside" if self.geom.contains(pt) else None


# --- expected result from the source ---------------------------------------------------------------
def expected(sources: list[SourceData], lat: float, lon: float) -> dict[str, Any]:
    pt = shapely.Point(lon, lat)
    out = {"sources": {}}
    for s in sources:
        rel = s.region.relation(pt, lat)
        if rel is None:
            continue
        zones, contacts, pending = [], [], []
        for i in s.tree.query(pt):
            c = s.usable[int(i)]
            if c.geom.contains(pt):
                zones.append(c)
            elif c.geom.intersects(pt):
                contacts.append(c)
        for i in s.ptree.query(pt):
            c = s.pending[int(i)]
            minx, miny, maxx, maxy = c.geom.bounds
            if minx <= lon <= maxx and miny <= lat <= maxy:
                pending.append(c)
        out["sources"][s.sid] = {"relation": rel, "zones": zones, "contacts": contacts, "pending": pending}
    srcs = out["sources"].values()
    if not out["sources"]:
        out["status"] = "not_available"
    elif any(v["zones"] for v in srcs):
        out["status"] = "available"
    elif any(v["pending"] or v["contacts"] or v["relation"] == "boundary" for v in srcs):
        out["status"] = "unknown"
    else:
        out["status"] = "no_match"
    return out


def _even_odd(c: Any, x: float, y: float) -> bool:
    inside = False
    for ring in [c.exterior, *c.interiors]:
        pts = list(ring.coords)
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


_MV_CACHE: dict[str, Any] = {}


def interpretations(c: Comp, lat: float, lon: float) -> dict[str, Any]:
    """Diagnosis only: how three readings of an invalid ring see the point. Never a verdict or a depth."""
    pt = shapely.Point(lon, lat)
    if c.ref not in _MV_CACHE:
        _MV_CACHE[c.ref] = shapely.make_valid(c.geom)
    reads = {"even_odd": _even_odd(c.geom, lon, lat), "make_valid": bool(_MV_CACHE[c.ref].contains(pt)),
             "exterior_only": bool(shapely.Polygon(c.geom.exterior).buffer(0).contains(pt))}
    agree = "inside" if all(reads.values()) else ("outside" if not any(reads.values()) else "disagree")
    reason = shapely.is_valid_reason(c.geom) if not c.valid else "feature_invalid_component"
    return {"reads": reads, "agree": agree, "reason": _reason_class(reason),
            "self_touch_at_vertex": _self_touch(c.geom, reason)}


def _self_touch(geom: Any, reason: str) -> bool | None:
    m = re.search(r"\[([-0-9.]+) ([-0-9.]+)\]", reason)
    if not m:
        return None
    x, y = float(m.group(1)), float(m.group(2))
    for ring in [geom.exterior, *geom.interiors]:
        pts = list(ring.coords)[:-1]
        hits = [i for i, (a, b) in enumerate(pts) if abs(a - x) < 1e-9 and abs(b - y) < 1e-9]
        if len(hits) >= 2:
            return True
    return False


# --- comparison --------------------------------------------------------------------------------------
def compare(exp: dict[str, Any], act: dict[str, Any]) -> list[str]:
    diffs = []
    if act.get("status") != exp["status"]:
        diffs.append(f"status: expected {exp['status']}, got {act.get('status')}")
    act_sources = {s["source_id"]: s for s in act.get("sources") or []}
    if set(act_sources) != set(exp["sources"]):
        diffs.append(f"sources: expected {sorted(exp['sources'])}, got {sorted(act_sources)}")
    for sid, e in exp["sources"].items():
        a = act_sources.get(sid)
        if a is None:
            continue
        if a["service_region_relation"] != e["relation"]:
            diffs.append(f"{sid} relation: expected {e['relation']}, got {a['service_region_relation']}")
        for key, akey in (("zones", "zones"), ("contacts", "boundary_contacts"), ("pending", "unknowns")):
            want = {c.ref for c in e[key]}
            got = {z["zone_ref"] for z in a[akey]}
            if want != got:
                diffs.append(f"{sid} {akey}: missing {sorted(want - got)[:3]} extra {sorted(got - want)[:3]}")
        by_ref = {c.ref: c for c in e["zones"] + e["contacts"]}
        for z in a["zones"] + a["boundary_contacts"]:
            c = by_ref.get(z["zone_ref"])
            if c is None:
                continue
            want = (c.rank, RANK_LABELS.get(c.rank), c.props["A31a_201"], c.props["A31a_202"], c.props["A31a_204"])
            got = (z["depth_class"]["class_code"], z["depth_class"]["label"], z["river_code"],
                   z["river_name_in_source"], z["river_manager_in_source"])
            if want != got:
                diffs.append(f"{sid} {z['zone_ref']} attributes: expected {want}, got {got}")
    if exp["status"] == "available":
        want = sorted((sid, c.ref) for sid, e in exp["sources"].items() for c in e["zones"])
        got = sorted((r["source"]["source_id"], r["feature_ref"]) for r in act.get("results") or [])
        if want != got:
            diffs.append("results differ from the zones of all sources")
    return diffs


def verdict(exp: dict[str, Any], act: dict[str, Any] | None, error: str | None) -> tuple[str, list[str]]:
    if error:
        return "ERROR", [error]
    diffs = compare(exp, act)
    if diffs:
        return "FAIL", diffs
    if exp["status"] == "not_available":
        return "OUT_OF_SCOPE", []
    if any(e["pending"] for e in exp["sources"].values()):
        return "INDETERMINATE", []
    return "PASS", []


# --- sampling ----------------------------------------------------------------------------------------
def _inside_point(rnd: random.Random, geom: Any) -> Any:
    minx, miny, maxx, maxy = geom.bounds
    for _ in range(30):
        p = shapely.Point(rnd.uniform(minx, maxx), rnd.uniform(miny, maxy))
        if geom.contains(p):
            return p
    p = geom.representative_point()
    return p if geom.contains(p) else None


def sample_points(sources: list[SourceData], seed: int, per_category: int, per_rank: int) -> list[dict[str, Any]]:
    rnd = random.Random(seed)
    pts: list[dict[str, Any]] = []

    def add(cat: str, p: Any, note: str = "") -> None:
        pts.append({"category": cat, "lat": round(p.y, 9), "lon": round(p.x, 9), "note": note})

    def small(cs: list[Comp]) -> list[Comp]:
        return [c for c in cs if c.nverts <= SAMPLE_MAX_VERTICES]

    for s in sources:
        usable = small(s.usable)
        by_rank = defaultdict(list)
        for c in usable:
            by_rank[c.rank].append(c)
        for rank in sorted(by_rank):                                   # stratified by depth class
            for c in rnd.sample(by_rank[rank], min(per_rank, len(by_rank[rank]))):
                if (p := _inside_point(rnd, c.geom)) is not None:
                    add("valid_interior", p, f"{s.sid} rank {rank}")
        for c in rnd.sample(usable, min(per_category, len(usable))):
            if (p := _inside_point(rnd, c.geom)) is not None:
                add("valid_interior", p, s.sid)
        found = {"valid_overlap": 0, "rank_differs": 0}
        for c in rnd.sample(usable, min(len(usable), per_category * 400)):
            if all(v >= per_category for v in found.values()):
                break
            for j in s.tree.query(c.geom, predicate="intersects"):
                d = s.usable[int(j)]
                if d is c or d.nverts > SAMPLE_MAX_VERTICES:
                    continue
                inter = c.geom.intersection(d.geom)
                if inter.area <= 0:
                    continue
                cat = "rank_differs" if c.rank != d.rank else "valid_overlap"
                if found[cat] < per_category and (p := _inside_point(rnd, inter)) is not None:
                    add(cat, p, f"{s.sid} ranks {c.rank}/{d.rank}")
                    found[cat] += 1
                break
        holed = [c for c in usable if len(c.geom.interiors)]
        for c in rnd.sample(holed, min(per_category, len(holed))):
            hole = shapely.Polygon(rnd.choice(list(c.geom.interiors)))
            if (p := _inside_point(rnd, hole)) is not None:
                add("hole", p, s.sid)
        for c in rnd.sample(usable, min(per_category, len(usable))):
            ring = rnd.choice([c.geom.exterior, *c.geom.interiors])
            x, y = rnd.choice(list(ring.coords))
            add("boundary", shapely.Point(x, y), f"{s.sid} vertex")
        pend = small(s.pending)
        for c in rnd.sample(pend, min(per_category, len(pend))):
            minx, miny, maxx, maxy = c.geom.bounds
            add("pending_bbox", shapely.Point(rnd.uniform(minx, maxx), rnd.uniform(miny, maxy)), s.sid)
    if len(sources) > 1:
        a, b = sources[0], sources[1]
        n = 0
        for c in rnd.sample(small(a.usable), min(len(a.usable), per_category * 40)):
            if n >= per_category:
                break
            for j in b.tree.query(c.geom, predicate="intersects"):
                d = b.usable[int(j)]
                if d.nverts > SAMPLE_MAX_VERTICES:
                    continue
                inter = c.geom.intersection(d.geom)
                if inter.area > 0 and (p := _inside_point(rnd, inter)) is not None:
                    add("multi_source", p, f"{a.sid} rank {c.rank} / {b.sid} rank {d.rank}")
                    n += 1
                break
    region = sources[0].region
    minx, miny, maxx, maxy = region.main.bounds
    n = tries = 0
    while n < per_category and tries < per_category * 200:
        tries += 1
        p = shapely.Point(rnd.uniform(minx, maxx), rnd.uniform(miny, maxy))
        e = expected(sources, p.y, p.x)
        if e["status"] == "no_match":
            add("region_no_zone", p)
            n += 1
    n = tries = 0
    while n < per_category and tries < per_category * 200:
        tries += 1
        p = shapely.Point(rnd.uniform(minx - 0.05, maxx + 0.05), rnd.uniform(miny - 0.05, maxy + 0.05))
        if all(s.region.relation(p, p.y) is None for s in sources):
            add("outside_region", p)
            n += 1
    edge = region.main.exterior
    for _ in range(per_category):
        p = edge.interpolate(rnd.uniform(0, edge.length))
        add("region_edge", p)
    return pts


# --- reconciliation with the index ------------------------------------------------------------------
def reconcile(sources: list[SourceData], index: Path) -> dict[str, Any]:
    db = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    try:
        meta = {k: json.loads(v) for k, v in db.execute("SELECT key, value FROM meta")}
        products = {r[0]: (r[1], r[2], json.loads(r[3])) for r in
                    db.execute("SELECT member, source_id, zip_sha256, counts FROM products")}
        product_of = {r[0]: r[1] for r in db.execute("SELECT product_ref, member FROM products")}
        out: dict[str, Any] = {"files": [], "sources": []}
        out["registration_matches_index"] = meta.get("registration") == [registration_view(s.reg) for s in sources] \
            if len(sources) == len(meta.get("registration", [])) else "partial (--source)"
        for s in sources:
            out["sources"].append(_reconcile_source(s, db, meta, products, product_of, out))
    finally:
        db.close()
    out["index_meta"] = {k: meta.get(k) for k in ("index_format", "built_at", "validator", "limitations")}
    return out


def _reconcile_source(s, db, meta, products, product_of, out) -> dict[str, Any]:
    for f in s.files:
        out["files"].append({**f, "source_id": s.sid, "index_sha256": meta["zip_sha256"].get(f["file_name"]),
                             "match": meta["zip_sha256"].get(f["file_name"]) == f["sha256"]})
    problems: list[str] = []
    prod_rows = []
    for member, p in sorted(s.products.items()):
        idx = products.get(member)
        if idx is None:
            problems.append(f"product missing from the index: {member}")
            continue
        c = idx[2]
        want = {"features_total": p["features"], "components_total": p["components"],
                "invalid_geometry_total": p["invalid"], "feature_invalid_component_total": p["involved"],
                "multipolygon_features": p["multipolygon"]}
        got = {k: c.get(k) for k in want}
        if want != got or p["features"] != p["feature_markers"] or idx[1] != p["zip_sha256"]:
            problems.append(f"product counts differ: {member}: source {want} markers {p['feature_markers']}, index {got}")
        prod_rows.append({"member": member, **want, "features_kept_in_index": c.get("features_kept"),
                          "invalid_reasons": p["reasons"], "ranks": p["ranks"], "rank_types": p["rank_types"],
                          "managers": p["managers"], "rivers": p["rivers"]})
    extra_products = sorted(m for m, v in products.items() if v[0] == s.sid and m not in s.products)
    if extra_products:
        problems.append(f"index has products not in the source: {extra_products[:3]}")
    src_by_ref = {c.ref: c for c in s.comps}
    indexed_features: set[tuple[str, int]] = set()
    rows = unknown = 0
    mism = []
    for r in db.execute("SELECT zone_ref, feature_index, polygon_index, usable, reason, minx, miny, maxx, maxy, "
                        "river_code, river_name, manager_code, manager, depth_class, wkb, product_ref "
                        "FROM components WHERE source_id = ?", (s.sid,)):
        rows += 1
        indexed_features.add((product_of[r[15]], r[1]))
        c = src_by_ref.get(r[0])
        if c is None:
            unknown += 1
            continue
        want = (c.fi, c.pi, int(c.usable), c.props["A31a_201"], c.props["A31a_202"], c.props["A31a_203"],
                c.props["A31a_204"], c.rank, RANK_LABELS.get(c.rank), c.geom.bounds)
        dc = json.loads(r[13])
        got = (r[1], r[2], r[3], r[9], r[10], r[11], r[12], dc["class_code"], dc["label"], tuple(r[5:9]))
        if want != got or not shapely.equals_exact(c.geom, shapely.from_wkb(r[14]), tolerance=0):
            mism.append({"zone_ref": r[0], "source": list(map(str, want)), "index": list(map(str, got))})
        elif not c.usable and r[4] != ("invalid_geometry" if not c.valid else "feature_invalid_component"):
            mism.append({"zone_ref": r[0], "pending_reason_in_index": r[4]})
    missing_required = sorted(s.required - indexed_features)
    if missing_required:
        problems.append(f"{len(missing_required)} features near the region are missing from the index, "
                        f"e.g. {missing_required[:3]}")
    if unknown:
        problems.append(f"{unknown} index rows have no source component near the region (or a wrong zone_ref)")
    if mism:
        problems.append(f"{len(mism)} index rows differ from the source")
    return {"source_id": s.sid, "products": len(s.products),
            "features_total": sum(p["features"] for p in s.products.values()),
            "components_total": sum(p["components"] for p in s.products.values()),
            "invalid_components_total": sum(p["invalid"] for p in s.products.values()),
            "involved_components_total": sum(p["involved"] for p in s.products.values()),
            "features_required_near_region": len(s.required), "features_in_index": len(indexed_features),
            "features_in_index_not_required": len(indexed_features - s.required),
            "index_rows": rows, "index_rows_checked": rows - unknown,
            "row_mismatches": mism[:20], "problems": problems, "result": "PASS" if not problems else "FAIL",
            "product_table": prod_rows}


# --- run -----------------------------------------------------------------------------------------------
def run(regions_file: Path, index: Path, *, source_ids: list[str] | None = None, per_category: int = 40,
        per_rank: int = 10, seed: int = 20261102, extra_points: list[tuple[float, float]] = (),
        log=lambda m: None) -> dict[str, Any]:
    from hererisk.location.flood_provider import FloodProvider      # the actual side only
    started = time.time()
    regs = load_flood_sources(regions_file)
    if source_ids:
        regs = [r for r in regs if r["source_id"] in source_ids]
        if len(regs) != len(set(source_ids)):
            raise ValueError("--source names a source that is not registered")
    n03 = {r["prefecture_code"]: r["address_n03"] for r in load_regions(regions_file)}
    regions: dict[tuple[str, ...], Region] = {}
    sources = []
    for r in regs:
        key = tuple(r["service_prefectures"])
        if key not in regions:
            regions[key] = Region([n03[p] for p in key])
        s = SourceData(r, regions[key])
        s.scan(log)
        s.finish()
        sources.append(s)
    log("verify: reconciliation with the index")
    recon = reconcile(sources, index)
    log("verify: provider start")
    provider = FloodProvider(regions_file, index)
    pts = sample_points(sources, seed, per_category, per_rank)
    pts = [{"category": "given", "lat": lat, "lon": lon, "note": "--point"} for lat, lon in extra_points] + pts
    ids = {s.sid for s in sources}
    results = []
    for pt in pts:
        err = act = None
        try:
            exp = expected(sources, pt["lat"], pt["lon"])
            act = provider.lookup(pt["lat"], pt["lon"])
            if source_ids:          # compare only the selected sources
                act = {**act, "sources": [s for s in act.get("sources") or [] if s["source_id"] in ids]}
                act["results"] = [r for r in act.get("results") or [] if r["source"]["source_id"] in ids]
                act["status"] = _status_of(act, exp)
        except Exception as exc:    # noqa: BLE001 - reported as ERROR
            exp, err = {"sources": {}, "status": None}, f"{type(exc).__name__}: {exc}"
        v, diffs = verdict(exp, act, err)
        item = {**pt, "verdict": v, "expected_status": exp["status"], "actual_status": (act or {}).get("status"),
                "diffs": diffs, "sources": {}}
        for sid, e in exp["sources"].items():
            sv = "ERROR" if v == "ERROR" else "FAIL" if any(d.startswith(sid) for d in diffs) else \
                "INDETERMINATE" if e["pending"] else "PASS"
            item["sources"][sid] = {"verdict": sv, "relation": e["relation"],
                                    "zones": [{"zone_ref": c.ref, "member": c.member, "feature_index": c.fi,
                                               "polygon_index": c.pi, "river": c.props["A31a_202"], "rank": c.rank}
                                              for c in e["zones"]],
                                    "boundary_contacts": [c.ref for c in e["contacts"]],
                                    "pending": [{"zone_ref": c.ref, "member": c.member, "feature_index": c.fi,
                                                 "polygon_index": c.pi, "river": c.props["A31a_202"], "rank": c.rank,
                                                 **(interpretations(c, pt["lat"], pt["lon"]) if v == "INDETERMINATE" or pt["category"] == "given" else {})}
                                                for c in e["pending"]]}
        results.append(item)
    return {"verify_version": VERIFY_VERSION, "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat(),
            "seconds": round(time.time() - started, 1),
            "inputs": {"regions_file": str(regions_file), "index": str(index), "sources": [s.sid for s in sources],
                       "seed": seed, "per_category": per_category, "per_rank": per_rank,
                       "points_given": [list(p) for p in extra_points]},
            "program": {"python": platform.python_version(), "shapely": shapely.__version__,
                        "geos": shapely.geos_version_string, "verify_sha256": _sha256(Path(__file__))},
            "reconciliation": recon, "points": results, "summary": summarize(results)}


def _status_of(act: dict[str, Any], exp: dict[str, Any]) -> str:
    srcs = act["sources"]
    if not srcs:
        return "not_available"
    if any(s["zones"] for s in srcs):
        return "available"
    if any(s["unknowns"] or s["boundary_contacts"] or s["service_region_relation"] == "boundary" for s in srcs):
        return "unknown"
    return "no_match"


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_cat: dict[str, Counter] = defaultdict(Counter)
    by_source: dict[str, Counter] = defaultdict(Counter)
    by_rank: dict[str, Counter] = defaultdict(Counter)
    causes: Counter = Counter()
    agree: Counter = Counter()
    point_reads: Counter = Counter()
    for r in results:
        if r["verdict"] == "INDETERMINATE":
            reads = [p.get("agree") for s in r["sources"].values() for p in s["pending"]]
            point_reads["all_pending_read_outside" if all(x == "outside" for x in reads) else
                        "some_pending_read_inside" if "inside" in reads else "readings_disagree"] += 1
        by_cat[r["category"]][r["verdict"]] += 1
        for sid, s in r["sources"].items():
            by_source[sid][s["verdict"]] += 1        # the source's own verdict at this point
            for z in s["zones"]:
                by_rank[f"{sid} rank {z['rank']}"][s["verdict"]] += 1
            for p in s["pending"]:
                if "reason" in p:
                    causes[f"{sid}: {p['reason']}{' (self-touch at a vertex)' if p.get('self_touch_at_vertex') else ''}"] += 1
                    agree[p["agree"]] += 1
    total = Counter(r["verdict"] for r in results)
    return {"points": len(results), "verdicts": {v: total.get(v, 0) for v in VERDICTS},
            "by_category": {k: dict(v) for k, v in sorted(by_cat.items())},
            "by_source": {k: dict(v) for k, v in sorted(by_source.items())},
            "by_source_note": "each source's own verdict at the point; a source whose region is far is not counted",
            "by_rank_of_expected_zone": {k: dict(v) for k, v in sorted(by_rank.items())},
            "indeterminate_causes": dict(causes.most_common()),
            "indeterminate_interpretations_agree": dict(agree),
            "indeterminate_points_by_reading": dict(point_reads),
            "categories_not_covered": [c for c in CATEGORIES if c not in by_cat]}


def representative_cases(results: list[dict[str, Any]], per_cause: int = 3) -> list[dict[str, Any]]:
    """A few points per distinct cause, so a person reviews causes, not every point."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in results:
        if r["verdict"] in ("PASS", "OUT_OF_SCOPE"):
            continue
        if r["verdict"] == "INDETERMINATE":
            key = "INDETERMINATE " + ", ".join(sorted({f"{sid}: {p.get('reason')}"
                                                       for sid, s in r["sources"].items() for p in s["pending"]}))
        else:
            key = f"{r['verdict']} " + "; ".join(sorted({d.split(':')[0] for d in r["diffs"]}))
        groups[key].append(r)
    return [{"cause": k, "count": len(v), "examples": [{"lat": e["lat"], "lon": e["lon"], "category": e["category"],
                                                         "diffs": e["diffs"][:5], "sources": e["sources"]} for e in v[:per_cause]]}
            for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))]


def write_report(report: dict[str, Any], directory: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(directory) / f"flood-verify-{stamp}"
    out.mkdir(parents=True, exist_ok=False)
    (out / "summary.json").write_text(json.dumps({k: v for k, v in report.items() if k != "points"},
                                                 ensure_ascii=False, indent=1), encoding="utf-8")
    with open(out / "points.jsonl", "w", encoding="utf-8") as f:
        for r in report["points"]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / "cases.json").write_text(json.dumps(representative_cases(report["points"]), ensure_ascii=False, indent=1),
                                    encoding="utf-8")
    return out


def summary_text(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [f"flood verify {report['verify_version']}  seed={report['inputs']['seed']}  points={s['points']}  "
             f"({report['seconds']}s)"]
    lines.append("verdicts: " + "  ".join(f"{k}={v}" for k, v in s["verdicts"].items()))
    for src in report["reconciliation"]["sources"]:
        lines.append(f"index vs source [{src['result']}] {src['source_id']}: products {src['products']}, "
                     f"features {src['features_total']}, components {src['components_total']}, "
                     f"invalid {src['invalid_components_total']}, involved {src['involved_components_total']}, "
                     f"required near region {src['features_required_near_region']}, in index {src['features_in_index']}, "
                     f"rows checked {src['index_rows_checked']}/{src['index_rows']}")
        lines.extend(f"  problem: {p}" for p in src["problems"])
    for f in report["reconciliation"]["files"]:
        lines.append(f"zip {'OK ' if f['match'] else 'NG '} {f['file_name']} sha256 {f['sha256'][:16]}… (index {str(f['index_sha256'])[:16]}…)")
    lines.append("by category: " + "; ".join(f"{k} {dict(v)}" for k, v in s["by_category"].items()))
    lines.append("by source: " + "; ".join(f"{k} {dict(v)}" for k, v in s["by_source"].items()))
    lines.append("by depth class of the expected zones: " + "; ".join(f"{k} {dict(v)}" for k, v in s["by_rank_of_expected_zone"].items()))
    if s["indeterminate_causes"]:
        lines.append("indeterminate causes: " + "; ".join(f"{k} x{v}" for k, v in s["indeterminate_causes"].items()))
        lines.append(f"interpretations of the pending areas at those points (diagnosis only): {s['indeterminate_interpretations_agree']}; "
                     f"per point: {s['indeterminate_points_by_reading']}")
    if s["categories_not_covered"]:
        lines.append(f"categories without points: {s['categories_not_covered']}")
    lines.append("note: sampled points only; this is not a proof that every zone is correct")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="python -m hererisk.flood verify")
    parser.add_argument("--regions", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--source", action="append", default=[], help="verify only this source_id (repeatable)")
    parser.add_argument("--per-category", type=int, default=40)
    parser.add_argument("--per-rank", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20261102)
    parser.add_argument("--point", action="append", default=[], metavar="LAT,LON")
    parser.add_argument("--report-dir", type=Path, help="write summary.json, points.jsonl, cases.json here")
    args = parser.parse_args(argv)
    try:
        points = [tuple(float(v) for v in p.split(",")) for p in args.point]
        if any(len(p) != 2 for p in points):
            raise ValueError
    except ValueError:
        sys.stderr.write("flood verify: --point must be LAT,LON\n")
        return 2
    try:
        report = run(args.regions, args.index, source_ids=args.source or None, per_category=args.per_category,
                     per_rank=args.per_rank, seed=args.seed, extra_points=points,
                     log=lambda m: sys.stderr.write(m + "\n"))
    except Exception as exc:    # noqa: BLE001 - the verification itself failed
        sys.stderr.write(f"flood verify: ERROR ({type(exc).__name__}: {exc})\n")
        return 3
    print(summary_text(report))
    if args.report_dir:
        print(f"report: {write_report(report, args.report_dir)}")
    s = report["summary"]["verdicts"]
    bad = s["FAIL"] or s["ERROR"] or any(src["result"] != "PASS" for src in report["reconciliation"]["sources"]) \
        or not all(f["match"] for f in report["reconciliation"]["files"])
    return 1 if bad else 0
