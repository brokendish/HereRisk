"""Phase 4-J study: when is a point's inside / outside relation to a (possibly invalid) polygon supported?

    python -m hererisk.research.point_study synthetic [--report-dir DIR]
    python -m hererisk.research.point_study real --flood-index <index.sqlite> --diag-index <diag.sqlite>
        --baseline <4-C report dir> [--records <4-I diag-api-verify report dir>] [--report-dir DIR]

Research only: reads the existing indexes read only, changes nothing, is not imported by any product
module, and its classes are not the product's ``candidate / undetermined / rejected``.

Per (component, point) it records, apart from each other:

* geometric facts on the original rings: nearest boundary (m, all rings), nearest defect (m), the raw
  winding number of each ring, the normalised winding number (each ring oriented by its own signed
  area, holes subtracted: ``local_analysis.Prepared.winding``) and the ray-crossing parity
* interpretations (rules that differ in substance, not implementations of one rule):
  ``even_odd`` (parity of all rings), ``nonzero`` (normalised winding != 0), ``make_valid_linework``
  (GEOS: noded linework, faces by parity), ``make_valid_structure`` (GEOS: union of shells minus union
  of holes, per ring role), ``buffer0`` (GEOS buffer(0): orientation as stored). ``geos_raw`` (GEOS
  predicates on the invalid input) is recorded but is not an interpretation (undefined for invalid input)
* the local contour method (Phase 4-C/4-D rule, ``Prepared``) staged up to 100, 500 and 1,000 m, with
  the Phase 4-E style conditions (local reading, winding, parity, no defect within the largest radius)
* a study class: ``determinate`` (valid geometry: GEOS), ``interpretation_consistent``,
  ``interpretation_dependent``, ``insufficient_evidence``, ``on_boundary``. Agreement of rules is NOT
  agreement with the intent of the data's author; nothing here claims the latter
"""

from __future__ import annotations

import json
import math
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
import shapely
from shapely.geometry import MultiPolygon, Point, Polygon

from hererisk.flood.local_analysis import ON_BOUNDARY_M, Prepared, staged

STUDY_VERSION = "polygon-point-study-v0.1"
RADIUS_SETS = {"r100": [5, 10, 25, 50, 100], "r500": [5, 10, 25, 50, 100, 250, 500],
               "r1000": [5, 10, 25, 50, 100, 250, 500, 1000]}
INTERPRETATIONS = ("even_odd", "nonzero", "make_valid_linework", "make_valid_structure", "buffer0")
M_PER_DEG = 111320.0
LAT0, LON0 = 35.0, 139.0


def _kx(lat: float) -> float:
    return M_PER_DEG * math.cos(math.radians(lat))


def _rss() -> int:
    v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(v if platform.system() == "Darwin" else v * 1024)


def _dist(values: list[float]) -> dict[str, Any] | None:
    if not values:
        return None
    v = sorted(values)
    return {"n": len(v), "median": round(statistics.median(v), 3), "p95": round(v[max(0, math.ceil(0.95 * len(v)) - 1)], 3),
            "max": round(v[-1], 3)}


# --- geometric facts ---------------------------------------------------------------------------------
def ring_facts(prep: Prepared, lat: float, lon: float) -> dict[str, Any]:
    """Nearest boundary over every segment (m), raw winding per ring, normalised winding, parity."""
    kx, ky = _kx(lat), M_PER_DEG
    ax, ay = (prep.x1 - lon) * kx, (prep.y1 - lat) * ky
    bx, by = (prep.x2 - lon) * kx, (prep.y2 - lat) * ky
    dx, dy = bx - ax, by - ay
    den = dx * dx + dy * dy
    t = np.clip(np.where(den > 0, -(ax * dx + ay * dy) / np.where(den > 0, den, 1), 0.0), 0.0, 1.0)
    edge_m = float(np.min(np.hypot(ax + t * dx, ay + t * dy)))
    up = (prep.y1 <= lat) & (prep.y2 > lat)
    dn = (prep.y2 <= lat) & (prep.y1 > lat)
    i = np.nonzero(up | dn)[0]
    xi = prep.x1[i] + (lat - prep.y1[i]) * (prep.x2[i] - prep.x1[i]) / (prep.y2[i] - prep.y1[i])
    right = xi > lon
    raw = np.bincount(prep.ring[i][right], weights=np.where(up[i][right], 1, -1), minlength=len(prep.area_sign))
    w, crossings = prep.winding(lat, lon)
    dd = prep.defect_distance_m(lat, lon)
    return {"edge_m": round(edge_m, 4), "defect_m": None if dd is None else round(dd, 2),
            "raw_winding_per_ring": [int(round(x)) for x in raw], "winding_normalised": w,
            "parity_inside": bool(crossings % 2), "zero_area_rings": int(sum(1 for a in prep.area_sign if a == 0)),
            "defects": int(len(prep.defects)), "defects_unlocated": bool(prep.defects_unlocated)}


def per_ring_unit(prep: Prepared, facts: dict[str, Any]) -> bool:
    """Every ring's own winding around the point, oriented by the ring's signed area, is 0 or 1; a ring
    of zero signed area (no orientation) must not wind around the point at all."""
    return all((r == 0) if a == 0 else (r * a in (0, 1)) for r, a in zip(facts["raw_winding_per_ring"], prep.area_sign))


def _polygonal(g: Any) -> Any:
    parts = [p for p in shapely.get_parts(g) if p.geom_type in ("Polygon", "MultiPolygon") and not p.is_empty]
    return shapely.union_all(parts) if parts else None


def _member(g: Any, pt: Point) -> str:
    if g is None or g.is_empty:
        return "empty"
    if g.contains(pt):
        return "inside"
    return "on_boundary" if g.intersects(pt) else "outside"


class Repairs:
    """The GEOS repairs of one geometry, built once (their cost is recorded)."""

    def __init__(self, geom: Any) -> None:
        self.geom = geom
        self.seconds: dict[str, float] = {}
        self.errors: dict[str, str] = {}
        self.out: dict[str, Any] = {}
        for name, fn in (("make_valid_linework", lambda g: shapely.make_valid(g, method="linework")),
                         ("make_valid_structure", lambda g: shapely.make_valid(g, method="structure", keep_collapsed=False)),
                         ("buffer0", lambda g: g.buffer(0))):
            t0 = time.perf_counter()
            try:
                v = _polygonal(fn(geom))
                shapely.prepare(v) if v is not None else None
                self.out[name] = v
            except Exception as exc:     # noqa: BLE001 - recorded, the rule is then "failed"
                self.out[name] = None
                self.errors[name] = type(exc).__name__
            self.seconds[name] = time.perf_counter() - t0


def interpretations(prep: Prepared, rep: Repairs, facts: dict[str, Any], pt: Point) -> dict[str, str]:
    on = facts["edge_m"] < ON_BOUNDARY_M
    w = facts["winding_normalised"]
    out = {"even_odd": "on_boundary" if on else ("inside" if facts["parity_inside"] else "outside"),
           "nonzero": "on_boundary" if on else ("inside" if w != 0 else "outside")}
    for name in ("make_valid_linework", "make_valid_structure", "buffer0"):
        out[name] = "failed" if name in rep.errors else _member(rep.out[name], pt)
    out["geos_raw"] = _member(rep.geom, pt)
    return out


def local_readings(prep: Prepared, lat: float, lon: float, facts: dict[str, Any]) -> dict[str, Any]:
    """The Phase 4-C rule staged per radius set, with the Phase 4-E style candidate conditions."""
    out = {}
    for name, radii in RADIUS_SETS.items():
        t0 = time.perf_counter()
        evals = []
        for r in radii:
            e = prep.evaluate(lat, lon, r)
            evals.append(e)
            if e["outcome"] != "no_boundary_within_radius":
                break
        final = staged(evals + [evals[-1]] * (len(radii) - len(evals)), radii)
        outcome = final["outcome"]
        dmax = facts["defect_m"] is not None and facts["defect_m"] <= radii[-1]
        cond = None
        if outcome in ("inside", "outside"):
            inside = outcome == "inside"
            cond = (final.get("winding") == (1 if inside else 0)) and (final.get("parity_inside") is inside) and not dmax
        out[name] = {"outcome": outcome, "radius_m": final.get("radius_m"), "edge_m": final.get("edge_m"),
                     "conditions_met": cond, "defect_within_max": dmax,
                     "ms": round((time.perf_counter() - t0) * 1000, 3)}
    return out


def study_class(valid: bool, feature_invalid: bool, interp: dict[str, str], facts: dict[str, Any],
                zero_area_around_point: bool = False) -> dict[str, Any]:
    values = {interp[k] for k in INTERPRETATIONS}
    if "on_boundary" in values or facts["edge_m"] < ON_BOUNDARY_M:
        return {"class": "on_boundary", "why": "the point is on (or within 1 mm of) a ring"}
    if valid and not feature_invalid:
        return {"class": "determinate", "why": "valid geometry: GEOS contains", "relation": interp["geos_raw"],
                "interpretations_agree": len(values) == 1}
    if feature_invalid:
        return {"class": "insufficient_evidence", "why": "feature-level invalidity: the component alone is not the area"}
    if "failed" in values or "empty" in values:
        return {"class": "insufficient_evidence", "why": "a repair failed or gave no area"}
    if zero_area_around_point:      # a ring with no orientation winds around the point: rules cannot orient it
        return {"class": "insufficient_evidence", "why": "a ring of zero signed area winds around the point"}
    if len(values) == 1:
        return {"class": "interpretation_consistent", "relation": values.pop(),
                "why": "every interpretation gives the same relation (not the author's intent)"}
    return {"class": "interpretation_dependent", "why": "the interpretations differ",
            "by_rule": {k: interp[k] for k in INTERPRETATIONS}}


def assess(geom: Any, lat: float, lon: float, *, feature_invalid: bool = False,
           prep: Prepared | None = None, rep: Repairs | None = None) -> dict[str, Any]:
    prep = prep or Prepared(geom)
    rep = rep or Repairs(geom)
    pt = Point(lon, lat)
    t0 = time.perf_counter()
    facts = ring_facts(prep, lat, lon)
    t_facts = time.perf_counter() - t0
    t0 = time.perf_counter()
    interp = interpretations(prep, rep, facts, pt)
    t_interp = time.perf_counter() - t0
    local = local_readings(prep, lat, lon, facts)
    valid = bool(geom.is_valid)
    w = facts["winding_normalised"]
    h = w in (0, 1) and facts["parity_inside"] == (w == 1)
    facts["h_winding_parity"] = h
    facts["h2_per_ring_unit"] = bool(h and per_ring_unit(prep, facts))
    return {"valid": valid, "validity_reason": shapely.is_valid_reason(geom), "facts": facts,
            "interpretations": interp, "local": local,
            "study": study_class(valid, feature_invalid, interp, facts, zero_area_around_point=any(
                a == 0 and r != 0 for r, a in zip(facts["raw_winding_per_ring"], prep.area_sign))),
            "ms": {"facts": round(t_facts * 1000, 3), "interpretations_per_point": round(t_interp * 1000, 3)}}


# --- synthetic geometries ----------------------------------------------------------------------------
def ll(x: float, y: float) -> tuple[float, float]:
    """metres east / north of (LAT0, LON0) -> (lon, lat)."""
    return LON0 + x / _kx(LAT0), LAT0 + y / M_PER_DEG


def _poly(shell, *holes):
    return Polygon([ll(*p) for p in shell], [[ll(*p) for p in h] for h in holes])


def synthetic_cases() -> list[dict[str, Any]]:
    sq = lambda x0, y0, x1, y1: [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]   # noqa: E731
    pinch = [(0, 0), (1500, 0), (1200, 600), (1800, 600), (1500, 0), (3000, 0), (3000, 3000), (0, 3000), (0, 0)]
    corner = [(0, 0), (3000, 0), (3000, 3100), (3100, 3000), (0, 3000), (0, 0)]
    eight = [(0, 0), (5000, 3000), (5000, 1000), (0, 3000), (0, 0)]
    cases = [
        ("C01 square 50 m (valid)", _poly(sq(0, 0, 50, 50)), [("centre", 25, 25), ("outside", 80, 25)], "valid, small"),
        ("C02 square 500 m (valid)", _poly(sq(0, 0, 500, 500)), [("centre", 250, 250)], "valid, medium"),
        ("C03 square 5 km (valid)", _poly(sq(0, 0, 5000, 5000)),
         [("centre", 2500, 2500), ("near edge", 2500, 30), ("outside", 5100, 2500)], "valid, large: no boundary within 100 m at the centre"),
        ("C04 corridor 300 m x 5 km (valid)", _poly(sq(0, 0, 5000, 300)), [("middle", 2500, 150)],
         "valid, long and thin: the parallel sides are 150 m away, the ends 2.5 km"),
        ("C05 U shape (valid)", _poly([(0, 0), (1000, 0), (1000, 1000), (700, 1000), (700, 300), (300, 300), (300, 1000), (0, 1000), (0, 0)]),
         [("arm", 150, 600), ("notch", 500, 700), ("base", 500, 150)], "valid U: the notch is 200 m from both arms"),
        ("C06 5 km square with a 1 km hole (valid)", _poly(sq(0, 0, 5000, 5000), sq(2000, 2000, 3000, 3000)),
         [("hole centre", 2500, 2500), ("between", 1000, 1000), ("shell-hole gap 3 m", 1998.5, 2500)], "valid with a hole"),
        ("C07 shell and hole 3 m apart (valid)", _poly(sq(0, 0, 1000, 1000), sq(3, 3, 997, 997)),
         [("in the 3 m band", 1.5, 500), ("in the hole", 500, 500)], "valid: a thin band between shell and hole"),
        ("C08 self-touch far away (pinch, inverted triangle)", _poly(pinch),
         [("far inside", 1500, 1500), ("in the triangle", 1500, 300), ("far corner", 2900, 2900)],
         "invalid (vertex self-touch at (1500,0)); the point 1.5 km away"),
        ("C09 self-crossing far away (small reversed corner lobe)", _poly(corner),
         [("far inside", 1500, 1500), ("inside the reversed lobe", 3030, 3030)],
         "invalid (edges cross at (3000,3000)); the lobe is traversed clockwise"),
        ("C10 self-crossing, large unequal lobes (figure eight)", _poly(eight),
         [("big lobe, 1.5 km from the crossing", 4500, 2000), ("small lobe, 1.2 km from the crossing", 600, 2400)],
         "invalid; each lobe is a face; the small one is reversed: interpretation decides the point"),
        ("C11 hole touching the shell at two far points", _poly(sq(0, 0, 3000, 3000), [(0, 1500), (1500, 1000), (3000, 1500), (1500, 2000), (0, 1500)]),
         [("upper part", 1500, 2700), ("in the hole", 1500, 1500)], "invalid (interior disconnected); membership need not change"),
        ("C12 hole crossing the shell far away", _poly(sq(0, 0, 3000, 3000), sq(2500, 1000, 3500, 2000)),
         [("hole inside shell", 2750, 1500), ("hole outside shell", 3250, 1500), ("far inside", 500, 500)],
         "invalid; the part of the hole outside the shell is read differently"),
        ("C13 zero-area hole ring", _poly(sq(0, 0, 2000, 2000), [(1000, 1000), (1500, 1000), (1200, 1000), (1000, 1000)]),
         [("near the flat ring", 1200, 1040), ("far", 300, 300)], "invalid; a ring with no orientation"),
        ("C14 MultiPolygon with overlapping components", MultiPolygon([_poly(sq(0, 0, 2000, 2000)), _poly(sq(1000, 1000, 3000, 3000))]),
         [("in the overlap", 1500, 1500), ("only in the first", 500, 500)], "feature-level invalidity: union vs parity"),
        ("C15 point on the boundary", _poly(sq(0, 0, 1000, 1000)), [("on an edge", 500, 0), ("on a vertex", 1000, 1000)], "valid"),
        ("C17 figure eight of C10 with the ring order reversed", _poly(list(reversed(eight))),
         [("big lobe, 1.5 km from the crossing", 4500, 2000), ("small lobe, 1.2 km from the crossing", 600, 2400)],
         "same set of points and edges as C10, opposite stored orientation: which rules follow the storage order"),
        ("C18 curl outside the main area (a loop traversed in the same direction)",
         _poly([(0, 0), (2000, 0), (2000, 1000), (2600, 1000), (2600, 1600), (2300, 1600), (2300, 900), (2000, 900), (2000, 2000), (0, 2000), (0, 0)]),
         [("in the curl", 2450, 1300), ("main area", 1000, 1000)], "invalid (crossing); the curl has winding +1"),
        ("C16 doubly wound ring (winding 2)", _poly([(0, 0), (2000, 0), (2000, 2000), (0, 2000), (0, 10), (1990, 10), (1990, 1990), (10, 1990), (10, 0), (0, 0)]),
         [("inner square", 1000, 1000)], "invalid; a ring that winds twice around the inner area"),
    ]
    return [{"name": n, "geometry": g, "points": pts, "note": note} for n, g, pts, note in cases]


def _assess_any(geom: Any, lat: float, lon: float) -> dict[str, Any]:
    if geom.geom_type == "MultiPolygon":       # feature level: each component, plus the feature as a whole
        parts = [assess(p, lat, lon, feature_invalid=not geom.is_valid) for p in geom.geoms]
        pt = Point(lon, lat)
        inside = [p["interpretations"]["geos_raw"] == "inside" for p in parts]
        feat = {"union": _member(shapely.union_all(list(geom.geoms)), pt),
                "parity_over_components": "inside" if sum(inside) % 2 else "outside",
                "make_valid_linework": _member(_polygonal(shapely.make_valid(geom, method="linework")), pt),
                "make_valid_structure": _member(_polygonal(shapely.make_valid(geom, method="structure", keep_collapsed=False)), pt)}
        return {"feature_valid": bool(geom.is_valid), "components": parts, "feature_interpretations": feat,
                "feature_class": "interpretation_consistent" if len(set(feat.values())) == 1 else "interpretation_dependent"}
    return assess(geom, lat, lon)


def run_synthetic(fuzz_n: int = 3000) -> dict[str, Any]:
    out = []
    for c in synthetic_cases():
        g = c["geometry"]
        pts = []
        for label, x, y in c["points"]:
            lon, lat = ll(x, y)
            pts.append({"label": label, "x_m": x, "y_m": y, "lon": lon, "lat": lat, **_assess_any(g, lat, lon)})
        out.append({"name": c["name"], "note": c["note"], "valid": bool(g.is_valid),
                    "validity_reason": shapely.is_valid_reason(g), "wkt_lonlat": g.wkt, "points": pts})
    return {"study_version": STUDY_VERSION, "kind": "synthetic", "started_at": datetime.now(timezone.utc).isoformat(),
            "program": _program(), "origin": {"lat": LAT0, "lon": LON0, "m_per_deg": M_PER_DEG}, "cases": out,
            "fuzz": fuzz(fuzz_n)}


def fuzz(n: int = 3000, seed: int = 20261103) -> dict[str, Any]:
    """Counterexample search for H: "normalised winding in {0, 1} and the parity agrees" => every
    interpretation gives the same relation, and for the stricter H2: H and, for every ring, its own
    winding (oriented by its signed area) is 0 or 1 (no ring goes round the point twice or backwards). Random rings (5-12 vertices in a 1 km box, often
    self-crossing), sometimes with a random hole; 20 random points each (not on a ring). A violation is
    recorded with its geometry. Finding none does not prove H."""
    import random
    rnd = random.Random(seed)
    tested = held = skipped = 0
    by_class, by_class2 = Counter(), Counter()
    violations, dependent_w = [], Counter()
    for _ in range(n):
        k = rnd.randint(5, 12)
        shell = [(rnd.uniform(0, 1000), rnd.uniform(0, 1000)) for _ in range(k)]
        holes = []
        if rnd.random() < 0.4:
            cx, cy, r = rnd.uniform(100, 900), rnd.uniform(100, 900), rnd.uniform(50, 300)
            holes.append([(cx + r * math.cos(t), cy + r * math.sin(t)) for t in sorted(rnd.uniform(0, 2 * math.pi) for _ in range(rnd.randint(3, 6)))])
        try:
            g = _poly(shell + shell[:1], *[h + h[:1] for h in holes])
            prep, rep = Prepared(g), Repairs(g)
        except Exception:     # noqa: BLE001 - degenerate random input
            skipped += 1
            continue
        if prep.defects_unlocated or 0 in prep.area_sign:
            skipped += 1
            continue
        for _ in range(20):
            lon, lat = ll(rnd.uniform(-50, 1050), rnd.uniform(-50, 1050))
            facts = ring_facts(prep, lat, lon)
            if facts["edge_m"] < 0.01:
                continue
            interp = interpretations(prep, rep, facts, Point(lon, lat))
            values = {interp[x] for x in INTERPRETATIONS}
            if "failed" in values or "empty" in values or "on_boundary" in values:
                skipped += 1
                continue
            tested += 1
            w = facts["winding_normalised"]
            h = w in (0, 1) and facts["parity_inside"] == (w == 1)
            h2 = h and per_ring_unit(prep, facts)
            cls = "consistent" if len(values) == 1 else "dependent"
            by_class[f"H={'yes' if h else 'no'} {cls}"] += 1
            by_class2[f"H2={'yes' if h2 else 'no'} {cls}"] += 1
            if cls == "dependent":
                dependent_w[str(w)] += 1
            if h:
                held += 1
                if cls == "dependent" and len(violations) < 20:
                    violations.append({"wkt_lonlat": g.wkt, "lon": lon, "lat": lat, "winding": w, "by_rule": interp})
    return {"seed": seed, "geometries": n, "points_tested": tested, "points_with_H": held, "skipped": skipped,
            "by_class": dict(by_class), "by_class_h2": dict(by_class2), "dependent_by_winding": dict(dependent_w),
            "violations": violations, "violations_found": by_class.get("H=yes dependent", 0),
            "violations_h2_found": by_class2.get("H2=yes dependent", 0)}


def _program() -> dict[str, str]:
    return {"python": platform.python_version(), "shapely": shapely.__version__, "geos": shapely.geos_version_string,
            "numpy": np.__version__, "machine": platform.machine(), "system": platform.system()}


# --- the Tokyo flood fixed set (Phase 4-C points, read only) -------------------------------------------
def _load_points(baseline: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (Path(baseline) / "points.jsonl").read_text("utf-8").splitlines() if line.strip()]


def _load_records(records_dir: Path | None) -> dict[tuple, dict[str, Any]]:
    if records_dir is None:
        return {}
    out = {}
    for line in (Path(records_dir) / "records.jsonl").read_text("utf-8").splitlines():
        r = json.loads(line)
        out[(r["lat"], r["lon"], r["zone_ref"])] = r
    return out


def _size(geom: Any) -> dict[str, float]:
    minx, miny, maxx, maxy = geom.bounds
    lat = (miny + maxy) / 2
    kx = _kx(lat)
    return {"area_m2": round(float(geom.area) * kx * M_PER_DEG, 1),
            "bbox_w_m": round((maxx - minx) * kx, 1), "bbox_h_m": round((maxy - miny) * M_PER_DEG, 1)}


def run_real(flood_index: Path, diag_index: Path, baseline: Path, records_dir: Path | None = None,
             log=lambda m: None) -> dict[str, Any]:
    from hererisk.flood.diag import DiagIndex
    points = _load_points(baseline)
    records = _load_records(records_dir)
    refs = sorted({p["zone_ref"] for pt in points for p in pt["pairs"]})
    db = sqlite3.connect(f"file:{flood_index}?mode=ro", uri=True)
    rows = {}
    for k in range(0, len(refs), 500):
        part = refs[k:k + 500]
        for ref, usable, reason, wkb in db.execute(
                f"SELECT zone_ref, usable, reason, wkb FROM components WHERE zone_ref IN ({','.join('?' * len(part))})", part):
            rows[ref] = (usable, reason, wkb)
    db.close()
    diag = DiagIndex(diag_index, flood_index=flood_index)
    rss0 = _rss()
    cache: dict[str, tuple] = {}
    prep_ms, repair_ms = [], defaultdict(list)
    out, times = [], defaultdict(list)
    for n, pt in enumerate(points):
        lat, lon = pt["lat"], pt["lon"]
        for p in pt["pairs"]:
            ref = p["zone_ref"]
            usable, reason, wkb = rows[ref]
            if ref not in cache:
                g = shapely.from_wkb(wkb)
                t0 = time.perf_counter()
                prep = Prepared(g)
                prep_ms.append((time.perf_counter() - t0) * 1000)
                rep = Repairs(g)
                for k, v in rep.seconds.items():
                    repair_ms[k].append(v * 1000)
                cache[ref] = (g, prep, rep, _size(g))
            g, prep, rep, size = cache[ref]
            a = assess(g, lat, lon, feature_invalid=(reason == "feature_invalid_component"), prep=prep, rep=rep)
            for k, v in a["ms"].items():
                times[k].append(v)
            for k, v in a["local"].items():
                times[f"local_{k}"].append(v["ms"])
            diag_local = None
            if not usable:                                   # the SQLite diagnosis index, same rule, larger radii
                comp = diag.by_refs([ref])[0]
                diag_local = {}
                for name, radii in RADIUS_SETS.items():
                    t0 = time.perf_counter()
                    r = diag.analyze(comp, lat, lon, radii)["local"]
                    times[f"diag_index_{name}"].append((time.perf_counter() - t0) * 1000)
                    diag_local[name] = r["outcome"]
            rec = records.get((lat, lon, ref)) or {}
            out.append({"category": pt["category"], "lat": lat, "lon": lon, "zone_ref": ref, "control": p["control"],
                        "usable": bool(usable), "reason": reason, "size": size, "segments": prep.segments,
                        "phase_4i": {k: rec.get(k) for k in ("classification", "interpretation", "relation", "reasons")} if rec else None,
                        "diag_index_local": diag_local, **a})
        if (n + 1) % 100 == 0:
            log(f"point study: {n + 1}/{len(points)} points")
    summary = summarize(out)
    return {"study_version": STUDY_VERSION, "kind": "real", "started_at": datetime.now(timezone.utc).isoformat(),
            "program": _program(), "inputs": {"flood_index": str(flood_index), "diag_index": str(diag_index),
                                              "baseline": str(baseline), "records": None if records_dir is None else str(records_dir),
                                              "points": len(points), "pairs": len(out), "components": len(cache)},
            "radius_sets_m": RADIUS_SETS, "summary": summary,
            "timing_ms": {**{k: _dist(v) for k, v in times.items()}, "prepare_per_component": _dist(prep_ms),
                          **{f"repair_{k}_per_component": _dist(v) for k, v in repair_ms.items()}},
            "memory": {"rss_after_load_bytes": rss0, "peak_rss_bytes": _rss()}, "pairs": out}


def summarize(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    inv = [p for p in pairs if not p["control"]]
    ctl = [p for p in pairs if p["control"]]
    s: dict[str, Any] = {"pairs_invalid": len(inv), "pairs_control_valid": len(ctl)}
    s["study_class_invalid"] = dict(Counter(p["study"]["class"] for p in inv))
    s["study_class_control"] = dict(Counter(p["study"]["class"] for p in ctl))
    s["control_interpretations_agree_with_geos"] = dict(Counter(
        all(p["interpretations"][k] == p["interpretations"]["geos_raw"] for k in INTERPRETATIONS) for p in ctl))
    s["invalid_rule_pairs_disagreeing"] = {f"{a}!={b}": sum(1 for p in inv if p["interpretations"][a] != p["interpretations"][b])
                                          for i, a in enumerate(INTERPRETATIONS) for b in INTERPRETATIONS[i + 1:]}
    s["invalid_dependent_examples"] = [{k: p[k] for k in ("lat", "lon", "zone_ref", "category")} | {
        "by_rule": p["interpretations"], "winding": p["facts"]["winding_normalised"], "defect_m": p["facts"]["defect_m"],
        "edge_m": p["facts"]["edge_m"]} for p in inv if p["study"]["class"] == "interpretation_dependent"][:20]
    cross = Counter()
    for p in inv:
        k = p["phase_4i"]["interpretation"] if p.get("phase_4i") else "?"
        cross[f"{k} -> {p['study']['class']}"] += 1
    s["phase_4i_vs_study"] = dict(sorted(cross.items()))
    nlb = [p for p in inv if p.get("phase_4i") and "no_local_boundary" in (p["phase_4i"]["reasons"] or [])]
    s["no_local_boundary"] = {
        "pairs": len(nlb), "study_class": dict(Counter(p["study"]["class"] for p in nlb)),
        "winding_in_0_1_and_parity_agrees": sum(1 for p in nlb if p["facts"]["winding_normalised"] in (0, 1)
                                                and p["facts"]["parity_inside"] == (p["facts"]["winding_normalised"] == 1)),
        "by_radius_set": {name: dict(Counter(p["local"][name]["outcome"] for p in nlb)) for name in RADIUS_SETS},
        "conditions_met_by_radius_set": {name: sum(1 for p in nlb if p["local"][name]["conditions_met"]) for name in RADIUS_SETS},
        "edge_m": _dist([p["facts"]["edge_m"] for p in nlb]), "defect_m": _dist([p["facts"]["defect_m"] for p in nlb if p["facts"]["defect_m"] is not None]),
        "bbox_max_side_m": _dist([max(p["size"]["bbox_w_m"], p["size"]["bbox_h_m"]) for p in nlb]),
        "by_category": dict(Counter(p["category"] for p in nlb)),
    }
    s["radius_sets_invalid"] = {name: dict(Counter(p["local"][name]["outcome"] for p in inv)) for name in RADIUS_SETS}
    s["radius_sets_conditions_met_invalid"] = {name: sum(1 for p in inv if p["local"][name]["conditions_met"]) for name in RADIUS_SETS}
    s["radius_sets_control"] = {name: dict(Counter(p["local"][name]["outcome"] for p in ctl)) for name in RADIUS_SETS}
    s["local_vs_consistent_relation"] = {}
    for name in RADIUS_SETS:
        c = Counter()
        for p in inv:
            l, st = p["local"][name], p["study"]
            if l["conditions_met"] and st["class"] == "interpretation_consistent":
                c["agrees" if l["outcome"] == st["relation"] else "DISAGREES"] += 1
            elif l["conditions_met"]:
                c[f"conditions_met but {st['class']}"] += 1
        s["local_vs_consistent_relation"][name] = dict(c)
    s["diag_index_equals_prepared"] = {name: dict(Counter(p["diag_index_local"][name] == p["local"][name]["outcome"]
                                                          for p in inv if p["diag_index_local"])) for name in RADIUS_SETS}
    s["h_conditions_invalid"] = dict(Counter(f"H={p['facts']['h_winding_parity']} H2={p['facts']['h2_per_ring_unit']} {p['study']['class']}"
                                             for p in inv))
    s["consistent_but_undetermined_by_reasons"] = dict(Counter(
        ",".join(p["phase_4i"]["reasons"]) for p in inv if p.get("phase_4i") and p["study"]["class"] == "interpretation_consistent"
        and p["phase_4i"]["classification"] == "undetermined").most_common())
    s["zero_area_ring_components_pairs"] = sum(1 for p in inv if p["facts"]["zero_area_rings"])
    s["category_invalid"] = dict(Counter(p["category"] for p in inv))
    s["defect_kinds_note"] = "defect kinds are in the diagnosis index (Phase 4-D: all 52,602 are 'touch')"
    return s


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m hererisk.research.point_study")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("synthetic")
    s.add_argument("--report-dir", type=Path)
    r = sub.add_parser("real")
    r.add_argument("--flood-index", type=Path, required=True)
    r.add_argument("--diag-index", type=Path, required=True)
    r.add_argument("--baseline", type=Path, required=True)
    r.add_argument("--records", type=Path)
    r.add_argument("--report-dir", type=Path)
    args = ap.parse_args(argv)
    rep = run_synthetic() if args.cmd == "synthetic" else run_real(
        args.flood_index, args.diag_index, args.baseline, args.records, log=lambda m: sys.stderr.write(m + "\n"))
    head = {k: v for k, v in rep.items() if k not in ("pairs",)}
    print(json.dumps(head if args.cmd == "real" else {"cases": [
        {"name": c["name"], "points": [{"label": p["label"], **({"study": p["study"], "interpretations": p["interpretations"],
                                                                 "local": {k: v["outcome"] for k, v in p["local"].items()}}
                                                                if "study" in p else {"feature": p["feature_interpretations"]})}
                                        for p in c["points"]]} for c in rep["cases"]],
        "fuzz": {k: v for k, v in rep["fuzz"].items() if k != "violations"}}, ensure_ascii=False, indent=1, default=str))
    if args.report_dir:
        out = Path(args.report_dir) / f"polygon-point-study-{args.cmd}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        out.mkdir(parents=True, exist_ok=False)
        (out / "summary.json").write_text(json.dumps(head, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        if "pairs" in rep:
            with open(out / "pairs.jsonl", "w", encoding="utf-8") as f:     # generated test points only
                for p in rep["pairs"]:
                    f.write(json.dumps(p, ensure_ascii=False, default=str) + "\n")
        print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
