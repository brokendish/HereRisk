"""Phase 4-L check: the shared validity / relation modules against the flood code on the real index.

    python -m hererisk.research.validity_relation_compare --regions <regions.json> --flood-index <index.sqlite>
        --baseline <flood-local-analysis-* dir> [--extra 2000] [--report-dir DIR]
    python -m hererisk.research.validity_relation_compare --regions ... --flood-index ... --memory common|flood

Read only. For every indexed feature, ``validity.classify_components`` is compared with the stored class
and with ``flood.index.classify`` on the same coordinates. For the Phase 4-C points (and, as boundary
cases, sampled vertices of valid components and bounding-box corners of pending ones), the zone_ref
sets of ``ComponentIndex.search`` are compared with ``FloodProvider.lookup`` per source. ``--memory``
measures, in a process of its own, the peak RSS of a ComponentIndex streamed from the index rows (stored
class) or of the FloodProvider (which also holds the N03 service regions). Research only:
nothing is adopted and the product does not use the shared modules.
"""

from __future__ import annotations

import json
import platform
import random
import resource
import sqlite3
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import shapely

from hererisk.common.polygon import relation as rel
from hererisk.common.polygon import validity as val
from hererisk.flood.index import classify
from hererisk.location.flood_provider import FloodProvider

KEYS = {"inside": "zones", "on_boundary": "boundary_contacts", None: "unknowns"}


def _rss() -> int:
    v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(v if platform.system() == "Darwin" else v * 1024)


def _stats(ms: list[float]) -> dict[str, float] | None:
    if not ms:
        return None
    s = sorted(ms)
    return {"n": len(s), "median_ms": round(statistics.median(s), 4), "p95_ms": round(s[int(0.95 * (len(s) - 1))], 4),
            "max_ms": round(s[-1], 4)}


def _bucket(n: int) -> str:
    for b in (100, 1_000, 10_000, 100_000):
        if n < b:
            return f"<{b}"
    return ">=100000"


def run(regions: Path, flood_index: Path, baseline: Path, extra: int, log=lambda m: None) -> dict[str, Any]:
    rss = {"start": _rss()}
    db = sqlite3.connect(f"file:{Path(flood_index)}?mode=ro", uri=True)
    features: dict[tuple, list] = {}
    for r in db.execute("SELECT source_id, product_ref, feature_index, polygon_index, zone_ref, usable, reason, "
                        "invalid_detail, wkb FROM components ORDER BY rowid"):
        features.setdefault((r[1], r[2]), []).append(r)
    db.close()
    checks, classes = Counter(), Counter()
    val_ms, flood_ms, by_size = [], [], {}
    cands, geoms, vertices = [], {}, {}
    log(f"validity: {len(features)} features")
    for comps in features.values():
        gs = [shapely.from_wkb(r[8]) for r in comps]
        polys = [[[list(p) for p in g.exterior.coords]] + [[list(p) for p in i.coords] for i in g.interiors] for g in gs]
        nv = sum(len(ring) for p in polys for ring in p)
        t0 = time.perf_counter()
        got = val.classify_components(polys)
        t1 = time.perf_counter()
        ref = classify(polys)
        t2 = time.perf_counter()
        val_ms.append((t1 - t0) * 1000)
        flood_ms.append((t2 - t1) * 1000)
        by_size.setdefault(_bucket(nv), []).append((t1 - t0) * 1000)
        for r, c, (_, usable, reason, detail) in zip(comps, got, ref):
            classes[c.validity] += 1
            mine = (c.usable, None if c.usable else c.validity, c.detail if c.validity == "invalid_geometry" else None)
            stored = (bool(r[5]), r[6], r[7] if r[6] == "invalid_geometry" else None)
            flood = (usable, reason, detail if reason == "invalid_geometry" else None)
            checks["validity_equals_stored" if mine == stored else "VALIDITY_DIFFERS_FROM_STORED"] += 1
            checks["validity_equals_flood_classify" if mine == flood else "VALIDITY_DIFFERS_FROM_FLOOD"] += 1
            checks["geometry_unchanged" if c.geometry.wkb == r[8] else "GEOMETRY_CHANGED"] += 1
            cands.append(rel.Candidate(r[0], r[4], c.geometry, c.validity, c.detail))
            geoms[r[4]] = (c.geometry, c.validity)
            vertices[r[4]] = sum(len(x.coords) for x in [c.geometry.exterior, *c.geometry.interiors])
    rss["after_validity"] = _rss()
    t0 = time.perf_counter()
    idx = rel.ComponentIndex(cands)
    build_s = time.perf_counter() - t0
    rss["after_common_index"] = _rss()
    log("provider")
    provider = FloodProvider(regions, flood_index)
    rss["after_provider"] = _rss()

    pts = [(p["lon"], p["lat"], "phase_4c") for p in
           (json.loads(line) for line in (Path(baseline) / "points.jsonl").read_text("utf-8").splitlines() if line.strip())]
    rnd = random.Random(20261103)
    valid_refs = sorted(r for r, (_, v) in geoms.items() if v == "valid")
    pending_refs = sorted(r for r, (_, v) in geoms.items() if v != "valid")
    for ref in rnd.sample(valid_refs, min(extra, len(valid_refs))):
        c = list(geoms[ref][0].exterior.coords)
        x, y = c[rnd.randrange(len(c) - 1)]
        pts.append((x, y, "valid_vertex"))
    for ref in rnd.sample(pending_refs, min(extra, len(pending_refs))):
        minx, miny, maxx, maxy = geoms[ref][0].bounds
        pts.append(rnd.choice([(minx, miny, "pending_bbox_corner"), (maxx, maxy, "pending_bbox_corner"),
                               ((minx + maxx) / 2, maxy, "pending_bbox_edge")]))
    log(f"relation: {len(pts)} points")
    seen, kinds = Counter(), Counter()
    common_ms, flood_search_ms, relate_ms, relate_by_size = [], [], [], {}
    for x, y, kind in pts:
        section = provider.lookup(y, x)
        if section["status"] in ("not_available", "error"):
            kinds[f"{kind}:{section['status']}"] += 1
            continue
        kinds[f"{kind}:compared"] += 1
        listed = [s["source_id"] for s in section["sources"]]
        t0 = time.perf_counter()
        out = idx.search(x, y)
        common_ms.append((time.perf_counter() - t0) * 1000)
        pt = shapely.Point(x, y)
        rels = {s["source_id"]: s["service_region_relation"] for s in section["sources"]}
        t0 = time.perf_counter()
        for s in provider._sources:                    # the flood search alone (no region test), for timing
            if s.reg["source_id"] in rels:
                s.search(pt, x, y, rels[s.reg["source_id"]])
        flood_search_ms.append((time.perf_counter() - t0) * 1000)
        if not out["complete"]:
            checks[f"COMMON_{out['status'].upper()}"] += 1
            continue
        got = {(sid, k): set() for sid in listed for k in KEYS.values()}
        for f in out["features"]:
            if f["source_id"] in listed:
                got[(f["source_id"], KEYS[f["relation"]])].add(f["feature_ref"])
                seen[f"{f['evaluation']}:{f['relation']}"] += 1
        want = {(s["source_id"], k): {z["zone_ref"] for z in s[k]} for s in section["sources"] for k in KEYS.values()}
        checks["search_equals_provider" if got == want else "SEARCH_DIFFERS_FROM_PROVIDER"] += 1
        for f in out["features"]:
            g, v = geoms[f["feature_ref"]]
            if v != "valid":
                continue
            t0 = time.perf_counter()
            r = rel.relate(g, v, x, y)
            ms = (time.perf_counter() - t0) * 1000
            relate_ms.append(ms)
            relate_by_size.setdefault(_bucket(vertices[f["feature_ref"]]), []).append(ms)
            checks["relate_equals_search" if r["relation"] == f["relation"] else "RELATE_DIFFERS"] += 1
    rss["end"] = _rss()
    return {"started_at": datetime.now(timezone.utc).isoformat(), "inputs": {"flood_index": str(flood_index),
            "baseline": str(baseline), "features": len(features), "components": len(cands), "points": len(pts)},
            "geos": shapely.geos_version_string, "checks": dict(sorted(checks.items())),
            "failed": sorted(k for k in checks if k.isupper()),
            "validity_classes": dict(classes), "point_kinds": dict(sorted(kinds.items())),
            "search_results": dict(sorted(seen.items())),
            "timing": {"validity_per_feature": _stats(val_ms), "flood_classify_per_feature": _stats(flood_ms),
                       "validity_by_vertices": {k: _stats(v) for k, v in sorted(by_size.items())},
                       "common_index_build_s": round(build_s, 3), "common_search_per_point": _stats(common_ms),
                       "flood_search_per_point": _stats(flood_search_ms), "relate_per_component": _stats(relate_ms),
                       "relate_by_vertices": {k: _stats(v) for k, v in sorted(relate_by_size.items())}},
            "peak_rss_bytes": rss, "platform": platform.platform()}


def memory(mode: str, regions: Path, flood_index: Path) -> dict[str, Any]:
    rss0 = _rss()
    t0 = time.perf_counter()
    if mode == "flood":
        held: Any = FloodProvider(regions, flood_index)
    else:
        db = sqlite3.connect(f"file:{Path(flood_index)}?mode=ro", uri=True)
        rows = db.execute("SELECT source_id, zone_ref, usable, reason, invalid_detail, wkb FROM components ORDER BY rowid")
        held = rel.ComponentIndex(rel.Candidate(sid, ref, wkb, "valid" if usable else reason, detail)
                                  for sid, ref, usable, reason, detail, wkb in rows)
        db.close()
    return {"mode": mode, "seconds": round(time.perf_counter() - t0, 2), "rss_before_bytes": rss0,
            "peak_rss_bytes": _rss(), "held": type(held).__name__}


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="python -m hererisk.research.validity_relation_compare")
    p.add_argument("--regions", type=Path, required=True)
    p.add_argument("--flood-index", type=Path, required=True)
    p.add_argument("--baseline", type=Path, help="a flood-local-analysis-* report directory")
    p.add_argument("--memory", choices=("common", "flood"))
    p.add_argument("--extra", type=int, default=2000, help="sampled boundary points of each kind")
    p.add_argument("--report-dir", type=Path)
    args = p.parse_args(argv)
    if args.memory:
        print(json.dumps(memory(args.memory, args.regions, args.flood_index)))
        return 0
    if args.baseline is None:
        p.error("--baseline is required")
    out = run(args.regions, args.flood_index, args.baseline, args.extra, log=lambda m: sys.stderr.write(f"compare: {m}\n"))
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if args.report_dir:
        d = Path(args.report_dir) / f"polygon-validity-relation-compare-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
        d.mkdir(parents=True)
        (d / "summary.json").write_text(text + "\n", encoding="utf-8")
        sys.stderr.write(f"compare: report {d}\n")
    print(text)
    return 1 if out["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
