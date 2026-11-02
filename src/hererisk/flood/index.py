"""Local flood search index (Phase 4-A): built once from the registered official ZIPs, read by the
Location API flood provider. A local verification artifact, not a Publish / Dataset Registry entry.

    python -m hererisk.flood build --regions <regions.json> --output <index.sqlite>
    python -m hererisk.flood trace --index <index.sqlite> --zone-ref <loc-zn-...>
    python -m hererisk.flood verify ...   (hererisk.flood.verify: independent check against the source)
    python -m hererisk.flood local-analysis ...   (hererisk.flood.local_analysis: Phase 4-C PoC, diagnosis only)
    python -m hererisk.flood diag ...   (hererisk.flood.diag: Phase 4-D offline preparation + light search, diagnosis only)

Build (``build_index``), per registered source and file:

1. SHA-256 of the ZIP; product specification edition from the metadata; the scenario folder's members
2. every feature of every member is read (strict layout, ``hererisk.flood.a31a``); none is skipped
3. each component polygon is classified (Flood Normalize contract 9.3 / 9.3.1, one validator):
   * ``usable``  - valid (GEOS) and not involved in a feature-level invalidity
   * ``pending`` - invalid (``invalid_geometry``) or valid but involved in a feature-level invalidity
     (``feature_invalid_component``: interiors overlap / edges shared with another component)
   If the involved components cannot be identified, the build fails (no silent fallback)
4. a feature is kept whole (all components) when a usable component lies within
   ``SELECT_TOLERANCE_DEG`` of a service-region N03 polygon, or a pending component's bounding box
   (widened by the same tolerance) overlaps one (Integration contract 4.1 / 4.4, L1). This keeps every
   feature that can matter for a point inside the region or within the 10 m boundary band
5. nothing is repaired; geometries are stored as parsed (WKB)

Limitations (reported in the index and the API section): one validator (GEOS) instead of the two the
Normalize contract requires; coordinates are read as JSON floats (not the exact nano-degree integers);
no Source Fidelity / Integrated Validate records. So completeness is ``not_guaranteed``.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import shapely
from shapely.geometry import MultiPolygon, Polygon, box

from hererisk.flood import a31a
from hererisk.flood.errors import FloodIndexError
from hererisk.flood.registry import load_flood_sources, registration_view
from hererisk.location.address_regions import load_regions
from hererisk.location.n03_municipality import _read_file as read_n03

INDEX_FORMAT = "hererisk-flood-index-v0.1"
SELECT_TOLERANCE_DEG = 0.0005      # ~45 m: wider than the 10 m boundary band at any latitude in Japan
VALIDATOR = f"GEOS {shapely.geos_version_string} is_valid (single validator; the contract asks for two)"
LIMITATIONS = ["single_geometry_validator", "coordinates_as_float", "no_integrated_validate_record"]


def _ref(prefix: str, n: int, doc: dict[str, Any]) -> str:
    raw = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return prefix + hashlib.sha256(raw).hexdigest()[:n]


def product_ref(zip_sha256: str, product_id: str) -> str:
    # same shape as the Catalog / Identity contract proposal 4.2, own domain and prefix: not adopted
    return _ref("loc-prd-", 16, {"domain": "hererisk-flood-product-ref-local-v0", "product_id": product_id,
                                 "zip_sha256": zip_sha256})


def zone_ref(zip_sha256: str, member: str, feature_index: int, polygon_index: int) -> str:
    return _ref("loc-zn-", 20, {"domain": "hererisk-flood-zone-ref-local-v0", "polygon_index": polygon_index,
                                "record_key": {"feature_index": feature_index, "zip_member": member,
                                               "zip_sha256": zip_sha256}})


def classify(polys: list[Any]) -> list[tuple[Polygon, bool, str | None, str | None]]:
    """[(component, usable, pending reason, invalid detail)] in polygon_index order."""
    comps = []
    for rings in polys:
        try:
            comps.append(Polygon(rings[0], rings[1:]))
        except (ValueError, TypeError, shapely.errors.GEOSException) as exc:
            raise FloodIndexError("a component polygon cannot be built") from exc
    valid = [bool(c.is_valid) for c in comps]
    involved: set[int] = set()
    if len(comps) > 1 and not MultiPolygon(comps).is_valid:
        ok = [i for i, v in enumerate(valid) if v]
        tree = shapely.STRtree([comps[i] for i in ok])
        for a_pos, i in enumerate(ok):
            for b_pos in tree.query(comps[i]):
                j = ok[int(b_pos)]
                if j <= i:
                    continue
                if comps[i].relate_pattern(comps[j], "T********") or comps[i].relate_pattern(comps[j], "****1****"):
                    involved.update((i, j))
        rest = [comps[i] for i in ok if i not in involved]
        if len(rest) > 1 and not MultiPolygon(rest).is_valid:
            raise FloodIndexError("feature-level invalidity: the involved components cannot be identified")
    out = []
    for i, c in enumerate(comps):
        if not valid[i]:
            out.append((c, False, "invalid_geometry", shapely.is_valid_reason(c)))
        elif i in involved:
            out.append((c, False, "feature_invalid_component", "interiors overlap or an edge is shared"))
        else:
            out.append((c, True, None, None))
    return out


SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE products (product_ref TEXT PRIMARY KEY, source_id TEXT NOT NULL, file_name TEXT NOT NULL,
  zip_sha256 TEXT NOT NULL, member TEXT NOT NULL, product_id TEXT NOT NULL, spec_edition TEXT NOT NULL,
  counts TEXT NOT NULL);
CREATE TABLE components (zone_ref TEXT PRIMARY KEY, source_id TEXT NOT NULL, product_ref TEXT NOT NULL,
  feature_index INTEGER NOT NULL, polygon_index INTEGER NOT NULL, usable INTEGER NOT NULL,
  reason TEXT, invalid_detail TEXT, minx REAL NOT NULL, miny REAL NOT NULL, maxx REAL NOT NULL, maxy REAL NOT NULL,
  river_code TEXT NOT NULL, river_name TEXT NOT NULL, manager_code TEXT NOT NULL, manager TEXT NOT NULL,
  depth_class TEXT NOT NULL, wkb BLOB NOT NULL);
"""


def _region_polygons(regions_file: Path, prefs: set[str]) -> tuple[list[Any], dict[str, dict[str, str]]]:
    polys, files = [], {}
    by_pref = {r["prefecture_code"]: r for r in load_regions(regions_file)}
    for pref in sorted(prefs):
        path = by_pref[pref]["address_n03"]
        meta, items = read_n03(path, pref)
        polys.extend(g for _, g, _ in items)
        files[pref] = {"file": meta["file"], "sha256": a31a.sha256_file(path)}
    return polys, files


def build_index(regions_file: Path, output: Path, *, log=None) -> dict[str, Any]:
    log = log or (lambda msg: None)
    sources = load_flood_sources(regions_file)
    if not sources:
        raise FloodIndexError("the regions file has no flood_sources")
    output = Path(output)
    tmp = output.with_name(output.name + f".tmp-{os.getpid()}")
    if tmp.exists():
        raise FloodIndexError("a temporary index file already exists")
    db = sqlite3.connect(tmp)
    try:
        db.executescript(SCHEMA)
        summary = {"sources": []}
        n03_files: dict[str, dict[str, str]] = {}
        for src in sources:
            region, files = _region_polygons(Path(regions_file).expanduser(), set(src["service_prefectures"]))
            n03_files.update(files)
            tree = shapely.STRtree(region)
            s_sum = {"source_id": src["source_id"], "products": 0, "features_total": 0, "features_kept": 0,
                     "components_kept": 0, "usable_kept": 0, "pending_kept": 0, "pending_total": 0}
            for f in src["files"]:
                log(f"{src['source_id']}: {f['file_name']}")
                sha = a31a.sha256_file(f["path"])
                with a31a.open_zip(f["path"]) as z:
                    edition = a31a.spec_edition(z, f["distribution_code"])
                    for member in a31a.scenario_members(z, src["scenario"], f["distribution_code"], src["data_year"]):
                        _build_member(db, z, member, src, f, sha, edition, tree, s_sum)
            summary["sources"].append(s_sum)
        meta = {"index_format": INDEX_FORMAT,
                "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "registration": [registration_view(s) for s in sources],
                "zip_sha256": {f["file_name"]: None for s in sources for f in s["files"]},
                "n03": n03_files, "select_tolerance_deg": SELECT_TOLERANCE_DEG, "validator": VALIDATOR,
                "limitations": LIMITATIONS, "summary": summary}
        for (name, sha) in db.execute("SELECT DISTINCT file_name, zip_sha256 FROM products"):
            meta["zip_sha256"][name] = sha
        db.executemany("INSERT INTO meta VALUES (?, ?)", [(k, json.dumps(v, ensure_ascii=False)) for k, v in meta.items()])
        db.commit()
    except BaseException:
        db.close()
        tmp.unlink(missing_ok=True)
        raise
    db.close()
    os.replace(tmp, output)
    return summary


def _build_member(db, z, member, src, f, sha, edition, tree, s_sum) -> None:
    norm = a31a.normalized_member(member)
    product_id = norm.rsplit("/", 1)[-1][: -len(".geojson")]
    pref = product_ref(sha, product_id)
    c = {"features_total": 0, "features_kept": 0, "components_total": 0, "components_kept": 0,
         "usable_kept": 0, "pending_kept": 0, "pending_total": 0, "invalid_geometry_total": 0,
         "feature_invalid_component_total": 0, "multipolygon_features": 0}
    rows = []
    for fi, feat in a31a.iter_features(z, member):
        props, geom = feat["properties"], feat["geometry"]
        polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        a31a.check_coordinates(polys)
        if props["A31a_203"] != src["river_manager_code"]:
            raise FloodIndexError("A31a_203 (river manager) does not match the registration")
        if not all(isinstance(props[k], str) and props[k] for k in ("A31a_201", "A31a_202", "A31a_203", "A31a_204")):
            raise FloodIndexError("A31a_201..A31a_204 must be non-empty strings")
        depth = json.dumps(a31a.depth_class(edition, props["A31a_205"]), ensure_ascii=False)
        comps = classify(polys)
        c["features_total"] += 1
        c["components_total"] += len(comps)
        c["multipolygon_features"] += geom["type"] == "MultiPolygon"
        for _, usable, reason, _ in comps:
            if not usable:
                c["pending_total"] += 1
                c["invalid_geometry_total" if reason == "invalid_geometry" else "feature_invalid_component_total"] += 1
        keep = False
        for comp, usable, _, _ in comps:
            if usable:
                hit = tree.query(comp, predicate="intersects")
                if not len(hit):
                    hit = tree.query(comp, predicate="dwithin", distance=SELECT_TOLERANCE_DEG)
            else:
                hit = tree.query(box(*comp.bounds).buffer(SELECT_TOLERANCE_DEG, join_style="mitre"))
            if len(hit):
                keep = True
                break
        if not keep:
            continue
        c["features_kept"] += 1
        for pi, (comp, usable, reason, detail) in enumerate(comps):
            c["components_kept"] += 1
            c["usable_kept" if usable else "pending_kept"] += 1
            rows.append((zone_ref(sha, norm, fi, pi), src["source_id"], pref, fi, pi, int(usable), reason, detail,
                         *comp.bounds, props["A31a_201"], props["A31a_202"], props["A31a_203"], props["A31a_204"],
                         depth, shapely.to_wkb(comp)))
        if len(rows) >= 2000:
            db.executemany("INSERT INTO components VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            rows.clear()
    if rows:
        db.executemany("INSERT INTO components VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    db.execute("INSERT INTO products VALUES (?,?,?,?,?,?,?,?)",
               (pref, src["source_id"], f["file_name"], sha, norm, product_id, edition, json.dumps(c)))
    s_sum["products"] += 1
    for k in ("features_total", "features_kept", "components_kept", "usable_kept", "pending_kept", "pending_total"):
        s_sum[k] += c[k]


def read_meta(index: Path) -> dict[str, Any]:
    try:
        db = sqlite3.connect(f"file:{Path(index)}?mode=ro", uri=True)
        try:
            meta = {k: json.loads(v) for k, v in db.execute("SELECT key, value FROM meta")}
        finally:
            db.close()
    except (sqlite3.Error, ValueError) as exc:
        raise FloodIndexError("flood index unreadable") from exc
    if meta.get("index_format") != INDEX_FORMAT:
        raise FloodIndexError("flood index format not supported")
    return meta


def trace(index: Path, ref: str) -> dict[str, Any] | None:
    """Internal trace of one zone_ref back to the official file (never part of an API response)."""
    db = sqlite3.connect(f"file:{Path(index)}?mode=ro", uri=True)
    try:
        row = db.execute("SELECT c.zone_ref, c.source_id, c.product_ref, p.file_name, p.zip_sha256, p.member, "
                         "p.product_id, c.feature_index, c.polygon_index, c.usable, c.reason, c.invalid_detail, "
                         "c.river_code, c.river_name, c.manager_code, c.manager, c.depth_class, "
                         "c.minx, c.miny, c.maxx, c.maxy FROM components c JOIN products p USING (product_ref) "
                         "WHERE c.zone_ref = ?", (ref,)).fetchone()
    finally:
        db.close()
    if row is None:
        return None
    keys = ["zone_ref", "source_id", "product_ref", "file_name", "zip_sha256", "zip_member", "product_id",
            "feature_index", "polygon_index", "usable", "pending_reason", "invalid_detail", "A31a_201", "A31a_202",
            "A31a_203", "A31a_204", "depth_class", "minx", "miny", "maxx", "maxy"]
    out = dict(zip(keys, row))
    out["usable"] = bool(out["usable"])
    out["depth_class"] = json.loads(out["depth_class"])
    out["bbox"] = [out.pop(k) for k in ("minx", "miny", "maxx", "maxy")]
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["verify"]:
        from hererisk.flood.verify import main as verify_main   # kept apart from the builder on purpose
        return verify_main(argv[1:])
    if argv[:1] == ["local-analysis"]:
        from hererisk.flood.local_analysis import main as local_main
        return local_main(argv[1:])
    if argv[:1] == ["diag"]:
        from hererisk.flood.diag import main as diag_main
        return diag_main(argv[1:])
    parser = argparse.ArgumentParser(prog="python -m hererisk.flood")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the local flood search index from the registered ZIPs")
    b.add_argument("--regions", type=Path, required=True)
    b.add_argument("--output", type=Path, required=True)
    t = sub.add_parser("trace", help="internal trace of a zone_ref to the official file")
    t.add_argument("--index", type=Path, required=True)
    t.add_argument("--zone-ref", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "trace":
        out = trace(args.index, args.zone_ref)
        print(json.dumps(out, ensure_ascii=False, indent=1) if out else "not found")
        return 0 if out else 1
    try:
        summary = build_index(args.regions, args.output, log=lambda m: sys.stderr.write(f"flood index: {m}\n"))
    except (FloodIndexError, a31a.A31aFormatError, ValueError, OSError) as exc:
        sys.stderr.write(f"flood index: not built ({exc})\n")
        return 3
    print(json.dumps({"status": "SUCCESS", "summary": summary}, ensure_ascii=False))
    return 0
