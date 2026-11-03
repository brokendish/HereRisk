"""Phase 4-N.2 check: the Location Resolver against the existing in-memory N03 decisions.

    python -m hererisk.research.resolver_compare --regions <regions.json> --admin-index <admin.sqlite>
        [--baseline <flood-local-analysis-* dir>] [--tsunami-index <t.sqlite>] [--per-kind 3000]
        [--threads 8,32] [--report-dir DIR]

References (unchanged code, memory-resident): ``N03Municipalities.locate`` (address) and the providers'
``_Region.relation`` (flood: ``location.flood_provider._Region``, tsunami: ``location.tsunami_provider._Region``)
for every single prefecture and for every pair of registered prefectures. Points: the Phase 4-C flood
points, tsunami zone vertices and box centres (if a tsunami index is given), N03 vertices and points 5 m,
9.9 m, 10.1 m and 15 m beside N03 edges on both sides (border edges between prefectures first), and
uniform points over the registered area's box. Differences are listed with their distances to the
boundaries so they can be classified. Research only; nothing is adopted.
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import math
import platform
import random
import resource
import sqlite3
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

import shapely

from hererisk.location.address_regions import load_regions
from hererisk.location.n03_municipality import N03Municipalities, _read_file
from hererisk.location.resolver import INSIDE, NEAR, LocationResolver, tolerance_deg


def _rss() -> int:
    v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(v if platform.system() == "Darwin" else v * 1024)


def _cur_rss() -> int | None:
    try:
        for line in open("/proc/self/status"):
            if line.startswith("VmRSS"):
                return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


def _stats(v: list[float]) -> dict[str, float] | None:
    if not v:
        return None
    s = sorted(v)
    return {"n": len(s), "median": round(statistics.median(s), 4), "p95": round(s[int(0.95 * (len(s) - 1))], 4),
            "max": round(s[-1], 4)}


def expected_locate(state: str, value: Any) -> tuple:
    return (state, value if state != "ambiguous" else tuple(value))


def got_locate(loc) -> tuple:
    if loc.status == INSIDE:
        return ("inside", loc.municipalities[0]["code"])
    if loc.status == NEAR:
        return ("ambiguous", tuple(m["code"] for m in loc.municipalities))
    return ("outside", None)


MICRO_GAP_M2 = 1.0


def micro_gap(loc, prefecture_set) -> bool:
    """A gap smaller than ``MICRO_GAP_M2`` within the tolerance between the source features near the point
    (holes of their union that are not holes of any single feature): the source's own geometry, checked
    without the resolver's decision."""
    feats = [a.geometry for a in loc._near if a.prefecture_code in prefecture_set]
    if len(feats) < 2:
        return False
    u = shapely.union_all(feats)
    own = {r.wkb for f in feats for p in getattr(f, "geoms", [f]) for r in p.interiors}
    pt = shapely.Point(loc.lon, loc.lat)
    k = 111320.0 ** 2 * math.cos(math.radians(loc.lat))
    for p in getattr(u, "geoms", [u]):
        for r in p.interiors:
            if r.wkb not in own and shapely.Polygon(r).area * k < MICRO_GAP_M2 and r.distance(pt) <= loc.tolerance_deg:
                return True
    return False


def points(regions: Path, baseline: Path | None, tsunami_index: Path | None, per_kind: int) -> list[tuple]:
    rnd = random.Random(20261103)
    pts: list[tuple] = []
    if baseline:
        pts += [(p["lon"], p["lat"], "flood_points") for p in
                (json.loads(line) for line in (Path(baseline) / "points.jsonl").read_text("utf-8").splitlines() if line.strip())]
    if tsunami_index:
        db = sqlite3.connect(f"file:{tsunami_index}?mode=ro", uri=True)
        rows = db.execute("SELECT minx, miny, maxx, maxy, wkb FROM components").fetchall()
        db.close()
        for minx, miny, maxx, maxy, wkb in rnd.sample(rows, min(per_kind // 2, len(rows))):
            pts.append(((minx + maxx) / 2, (miny + maxy) / 2, "tsunami_box_centre"))
            c = shapely.from_wkb(wkb).exterior.coords
            pts.append((*c[rnd.randrange(len(c) - 1)], "tsunami_vertex"))
    regs = load_regions(regions)
    by_pref = {r["prefecture_code"]: [g for _, g, _ in _read_file(r["address_n03"], r["prefecture_code"])[1]] for r in regs}
    rings = {p: [list(r.coords) for g in gs for poly in getattr(g, "geoms", [g]) for r in [poly.exterior, *poly.interiors]]
             for p, gs in by_pref.items()}
    verts = {p: {v for r in rs for v in r} for p, rs in rings.items()}
    edges = []          # (border, pref, a, b): a border edge has both ends on another prefecture's vertices
    for p, rs in rings.items():
        others = set().union(*(v for q, v in verts.items() if q != p)) if len(verts) > 1 else set()
        for c in rs:
            for a, b in zip(c, c[1:]):
                edges.append((a in others and b in others, p, a, b))
    border = [e for e in edges if e[0]]
    plain = [e for e in edges if not e[0]]
    chosen = rnd.sample(border, min(per_kind, len(border))) + rnd.sample(plain, min(per_kind, len(plain)))
    for is_border, p, (ax, ay), (bx, by) in chosen:
        tag = "border" if is_border else "edge"
        pts.append((ax, ay, f"{tag}_vertex"))
        L = math.hypot(bx - ax, by - ay) or 1.0
        mx, my = (ax + bx) / 2, (ay + by) / 2
        kx = 111320.0 * math.cos(math.radians(my))
        for d_m in (5.0, 9.9, 10.1, 15.0):
            for side in (1, -1):
                # metres on the ground (the tolerance in degrees is on the longitude scale; these straddle it)
                nx, ny = -(by - ay) / L, (bx - ax) / L
                pts.append((mx + side * nx * d_m / kx, my + side * ny * d_m / 111320.0, f"{tag}_{d_m}m"))
    bounds = [g.bounds for gs in by_pref.values() for g in gs]
    minx, miny = min(b[0] for b in bounds), min(b[1] for b in bounds)
    maxx, maxy = max(b[2] for b in bounds), max(b[3] for b in bounds)
    pts += [(rnd.uniform(minx, maxx), rnd.uniform(miny, maxy), "uniform") for _ in range(per_kind)]
    return pts


def run(regions: Path, admin_index: Path, baseline: Path | None, tsunami_index: Path | None, per_kind: int,
        threads: list[int], log=lambda m: None) -> dict[str, Any]:
    from hererisk.location.flood_provider import _Region as FloodRegion
    from hererisk.location.tsunami_provider import _Region as TsunamiRegion
    out: dict[str, Any] = {"started_at": datetime.now(timezone.utc).isoformat(), "rss": {}}
    rss = out["rss"]
    rss["start_cur"] = _cur_rss()
    t0 = time.perf_counter()
    res = LocationResolver(admin_index, regions_file=regions)
    out["resolver_start_s"] = round(time.perf_counter() - t0, 3)
    rss["after_resolver_start_cur"] = _cur_rss()
    log("points")
    pts = points(regions, baseline, tsunami_index, per_kind)
    rss["after_points_cur"] = _cur_rss()
    log("references")
    regs = load_regions(regions)
    prefs = [r["prefecture_code"] for r in regs]
    t0 = time.perf_counter()
    n03 = N03Municipalities([(r["prefecture_code"], r["address_n03"]) for r in regs])
    out["reference_n03_start_s"] = round(time.perf_counter() - t0, 3)
    polys = {r["prefecture_code"]: [g for _, g, _ in _read_file(r["address_n03"], r["prefecture_code"])[1]] for r in regs}
    sets = [frozenset([p]) for p in prefs] + [frozenset(c) for c in combinations(prefs, 2)]
    regions_ref = {s: (FloodRegion([g for p in sorted(s) for g in polys[p]]),
                       TsunamiRegion([g for p in sorted(s) for g in polys[p]])) for s in sets}
    del polys
    log(f"{len(pts)} points: resolver")
    db = sqlite3.connect(f"file:{admin_index}?mode=ro", uri=True)
    views, ms, cands, wkb_bytes = [], [], [], []
    checks, diffs, kinds = Counter(), [], Counter()
    for x, y, kind in pts:            # one point at a time: a resolved location holds its candidates' geometry
        tol = tolerance_deg(y)
        q = (x - tol, x + tol, y - tol, y + tol)
        c = db.execute("SELECT count(*), coalesce(sum(length(a.wkb)), 0) FROM area_rtree r JOIN areas a ON a.id = r.id "
                       "WHERE r.maxx >= ? AND r.minx <= ? AND r.maxy >= ? AND r.miny <= ?", q).fetchone()
        cands.append(c[0])
        wkb_bytes.append(c[1])
        t = time.perf_counter()
        loc = res.resolve(y, x)
        ms.append((time.perf_counter() - t) * 1000)
        views.append(loc.view())
        kinds[kind] += 1
        if not loc.complete:
            checks["RESOLVER_FAILED"] += 1
            continue
        want = expected_locate(*n03.locate(y, x))
        have = got_locate(loc)
        checks["locate_equal" if have == want else "LOCATE_DIFFERS"] += 1
        checks[f"state:{have[0]}"] += 1
        if have != want:
            diffs.append({"kind": kind, "lon": x, "lat": y, "what": "locate", "resolver": have, "n03": want})
        pt = shapely.Point(x, y)
        for s, (fr, tr) in regions_ref.items():
            a, b = fr.relation(pt, y), tr.relation(pt, y)
            r = res.region_relation(loc, s)
            key = "+".join(sorted(s))
            checks["flood_tsunami_region_equal" if a == b else "FLOOD_TSUNAMI_REGION_DIFFER"] += 1
            if r == a:
                checks[f"region_equal:{key}"] += 1
                continue
            # classify: the point's candidates all lie in one prefecture P of the set, and the reference for {P}
            # alone agrees with the resolver -> the reference's answer depends on which other (farther than the
            # tolerance) polygons were in its union (a GEOS overlay effect on a source micro-gap), not the point
            near_prefs = {q["code"] for q in loc.prefectures}
            single = len(near_prefs) == 1 and frozenset(near_prefs) in regions_ref
            cls = ("reference_union_depends_on_set"
                   if single and regions_ref[frozenset(near_prefs)][0].relation(pt, y) == r else "UNCLASSIFIED")
            if cls == "UNCLASSIFIED" and r == "boundary" and micro_gap(loc, s):
                cls = "source_micro_gap"
            checks[f"region_differs:{key}:{cls}"] += 1
            diffs.append({"kind": kind, "lon": x, "lat": y, "what": f"region {key}", "resolver": r, "region": a,
                          "class": cls})
        if loc.status == NEAR and len({p["code"] for p in loc.prefectures}) > 1:
            checks["near_boundary_with_two_prefectures"] += 1
        del loc
    db.close()
    rss["peak_after_references"] = _rss()
    par = {}
    for n in threads:
        sample = list(zip(pts, views))[: min(4000, len(pts))]
        t = time.perf_counter()
        with cf.ThreadPoolExecutor(max_workers=n) as pool:
            again = list(pool.map(lambda item: res.resolve(item[0][1], item[0][0]).view(), sample))
        same = sum(1 for (p, a), b in zip(sample, again) if a == b)
        par[str(n)] = {"points": len(sample), "identical": same, "busy_or_failed": sum(1 for b in again if not b["complete"]),
                       "seconds": round(time.perf_counter() - t, 2), "rss_cur_after": _cur_rss()}
        if same != len(sample):
            checks[f"PARALLEL_{n}_DIFFERS"] += 1
    res.close()
    out.update({"points": len(pts), "point_kinds": dict(sorted(kinds.items())), "checks": dict(sorted(checks.items())),
                "failed": sorted(k for k in checks if k.isupper() or k.split(":")[0].isupper() or k.endswith("UNCLASSIFIED")),
                "differences": diffs[:200], "differences_total": len(diffs),
                "resolve_ms": _stats(ms), "rtree_candidates": _stats(cands), "candidate_wkb_bytes": _stats(wkb_bytes),
                "parallel": par, "index_bytes": Path(admin_index).stat().st_size, "platform": platform.platform()})
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="python -m hererisk.research.resolver_compare")
    p.add_argument("--regions", type=Path, required=True)
    p.add_argument("--admin-index", type=Path, required=True)
    p.add_argument("--baseline", type=Path)
    p.add_argument("--tsunami-index", type=Path)
    p.add_argument("--per-kind", type=int, default=3000)
    p.add_argument("--threads", default="8,32")
    p.add_argument("--report-dir", type=Path)
    p.add_argument("--dump-points", type=Path, help="write the generated points (JSON lines) for resolver_measure")
    args = p.parse_args(argv)
    if args.dump_points:
        with open(args.dump_points, "w", encoding="utf-8") as fh:
            for x, y, kind in points(args.regions, args.baseline, args.tsunami_index, args.per_kind):
                fh.write(json.dumps({"lon": x, "lat": y, "kind": kind}) + "\n")
        return 0
    out = run(args.regions, args.admin_index, args.baseline, args.tsunami_index, args.per_kind,
              [int(t) for t in args.threads.split(",") if t], log=lambda m: sys.stderr.write(f"compare: {m}\n"))
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if args.report_dir:
        d = Path(args.report_dir) / f"resolver-compare-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
        d.mkdir(parents=True)
        (d / "summary.json").write_text(text + "\n", encoding="utf-8")
        sys.stderr.write(f"compare: report {d}\n")
    print(text)
    return 1 if out["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
