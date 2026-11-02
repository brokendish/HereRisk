"""Local analysis of invalid A31a polygons around a point (Phase 4-C, PoC, diagnosis only).

    python -m hererisk.flood local-analysis --regions <regions.json> [--index <index.sqlite>]
        [--settings <flood-settings.json>] [--source ID ...] [--per-category N] [--per-rank N]
        [--defect-points N] [--seed S] [--point LAT,LON ...] [--report-dir DIR]

Nothing here changes the official ZIPs, the search index or the Flood Provider's answer. The source is
read with the Phase 4-B verifier's own reader (``hererisk.flood.verify``); the index and the Provider
are only read (``--index``) to confirm that the analysed invalid components are exactly the Provider's
``unknowns`` at each point.

The local method (``local``) reads the original vertices only. No ring is cut, closed or rebuilt:

1. offline, once per component: the ring segments, the orientation of each ring (signed area), and
   the defect locations (every place where two non-adjacent segments meet: self-touches, crossings,
   ring-to-ring contacts)
2. per point and radius r (staged, smallest first):

   * a defect within r                       -> ``defect_within_radius`` (undetermined; final)
   * no segment within r                     -> ``no_boundary_within_radius`` (try the next radius)
   * the nearest segment(s) within r: the side of the point relative to them, with the ring's
     orientation, gives a local reading (``on_boundary`` / ``ambiguous_nearest`` when it cannot)
   * the far contour: the normalised winding number of the whole component (exterior and holes) must
     agree with the local reading (1 inside, 0 outside); otherwise ``inconsistent_winding``

   A local reading alone (a clean boundary nearby) is never taken as inside. ``local_plus_far`` is a
   second policy for comparison only: with no boundary within the largest radius it accepts the far
   winding number when it is 0 or 1 and the even-odd parity agrees.

Diagnostic readings compared with it (none decides anything): GEOS ``make_valid``, the even-odd rule
and the exterior ring only (Phase 4-B ``interpretations``), the winding number, and ``clip_rect`` (the
component cut by the window, GEOS ``clip_by_rect``), which shows what a window-edge cut does.
Valid components at the same points are analysed as a control: there the local method must agree
with GEOS ``contains`` whenever it decides.
"""

from __future__ import annotations

import json
import math
import platform
import random
import resource
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import shapely

from hererisk.flood import verify
from hererisk.flood.settings import load_settings, radii as setting_radii

POC_VERSION = "flood-local-analysis-poc-v0.1"
M_PER_DEG = 111320.0
ON_BOUNDARY_M = 0.001
TIE_M = 1e-6
DECIDED = ("inside", "outside")


def _scale(lat: float) -> tuple[float, float]:
    return M_PER_DEG * math.cos(math.radians(lat)), M_PER_DEG


def _ring_coords(ring: Any) -> np.ndarray:
    c = np.asarray(ring.coords)[:, :2]
    keep = np.ones(len(c), dtype=bool)
    keep[1:] = np.any(c[1:] != c[:-1], axis=1)          # consecutive repeated vertices are not defects
    return c[keep]


def _signed_area(c: np.ndarray) -> float:
    return 0.5 * float(np.sum(c[:-1, 0] * c[1:, 1] - c[1:, 0] * c[:-1, 1]))


# --- offline preparation (per component) -----------------------------------------------------------
class Prepared:
    """Segments, ring orientation and defect locations of one component, from the original vertices."""

    def __init__(self, geom: Any) -> None:
        t0 = time.perf_counter()
        x1, y1, x2, y2, ring, nxt, prv = [], [], [], [], [], [], []
        self.inner_left: list[bool] = []
        self.area_sign: list[int] = []
        start = 0
        for k, r in enumerate([geom.exterior, *geom.interiors]):
            c = _ring_coords(r)
            n = len(c) - 1
            if n < 1:
                continue
            a = _signed_area(c)
            self.area_sign.append((a > 0) - (a < 0))
            self.inner_left.append(a > 0 if k == 0 else a < 0)   # the polygon's interior side of the ring
            x1.append(c[:-1, 0]), y1.append(c[:-1, 1]), x2.append(c[1:, 0]), y2.append(c[1:, 1])
            ring.append(np.full(n, len(self.area_sign) - 1, dtype=np.int32))
            idx = np.arange(start, start + n)
            nxt.append(np.roll(idx, -1)), prv.append(np.roll(idx, 1))
            start += n
        self.x1, self.y1, self.x2, self.y2 = (np.concatenate(v) for v in (x1, y1, x2, y2))
        self.ring, self.next, self.prev = (np.concatenate(v) for v in (ring, nxt, prv))
        self.ring_is_hole = np.array([k > 0 for k in range(len(self.area_sign))])
        self.minx, self.maxx = np.minimum(self.x1, self.x2), np.maximum(self.x1, self.x2)
        self.miny, self.maxy = np.minimum(self.y1, self.y2), np.maximum(self.y1, self.y2)
        self.valid = bool(geom.is_valid)
        self.defects = self._defects()
        self.defects_unlocated = not self.valid and len(self.defects) == 0
        self.segments = len(self.x1)
        self.seconds = time.perf_counter() - t0

    def _defects(self) -> np.ndarray:
        segs = shapely.linestrings(np.stack([np.stack([self.x1, self.y1], 1), np.stack([self.x2, self.y2], 1)], 1))
        i, j = shapely.STRtree(segs).query(segs, predicate="intersects")
        keep = (i < j) & (self.next[i] != j) & (self.prev[i] != j)
        i, j = i[keep], j[keep]
        if not len(i):
            return np.zeros((0, 2))
        pts = shapely.get_coordinates(shapely.intersection(segs[i], segs[j]))
        return np.unique(np.round(pts, 12), axis=0)

    @property
    def nbytes(self) -> int:
        return sum(a.nbytes for a in (self.x1, self.y1, self.x2, self.y2, self.ring, self.next, self.prev,
                                      self.minx, self.maxx, self.miny, self.maxy, self.defects))

    def defect_distance_m(self, lat: float, lon: float) -> float | None:
        if not len(self.defects):
            return None
        kx, ky = _scale(lat)
        return float(np.min(np.hypot((self.defects[:, 0] - lon) * kx, (self.defects[:, 1] - lat) * ky)))

    def winding(self, lat: float, lon: float) -> tuple[int, int]:
        """(normalised winding number: 1 inside the exterior, -1 per hole; ray crossings) over every ring."""
        up = (self.y1 <= lat) & (self.y2 > lat)
        dn = (self.y2 <= lat) & (self.y1 > lat)
        i = np.nonzero(up | dn)[0]
        xi = self.x1[i] + (lat - self.y1[i]) * (self.x2[i] - self.x1[i]) / (self.y2[i] - self.y1[i])
        right = xi > lon
        raw = np.bincount(self.ring[i][right], weights=np.where(up[i][right], 1, -1), minlength=len(self.area_sign))
        w = sum(raw[k] * self.area_sign[k] * (-1 if self.ring_is_hole[k] else 1) for k in range(len(raw)))
        return int(round(w)), int(right.sum())

    def _side(self, g: int, t: float, lat: float, lon: float) -> bool | None:
        """True when the point is on the polygon's interior side next to segment g (nearest at t)."""
        kx, ky = _scale(lat)

        def xy(k: int, end: int) -> tuple[float, float]:
            return ((self.x2[k] if end else self.x1[k]) - lon) * kx, ((self.y2[k] if end else self.y1[k]) - lat) * ky

        def left(p, q) -> bool | None:       # the point (the origin) left of p->q
            v = (q[0] - p[0]) * (0 - p[1]) - (q[1] - p[1]) * (0 - p[0])
            return None if v == 0 else v > 0
        if 0 < t < 1:
            on_left = left(xy(g, 0), xy(g, 1))
        else:                                 # nearest at a vertex: the wedge of the two segments
            s_in, s_out = (g, int(self.next[g])) if t >= 1 else (int(self.prev[g]), g)
            a, v, b = xy(s_in, 0), xy(s_in, 1), xy(s_out, 1)
            l_in, l_out = left(a, v), left(v, b)
            turn = (v[0] - a[0]) * (b[1] - v[1]) - (v[1] - a[1]) * (b[0] - v[0])
            if l_in is None or l_out is None or turn == 0:
                return None
            on_left = (l_in and l_out) if turn > 0 else (l_in or l_out)
        if on_left is None:
            return None
        return on_left == self.inner_left[int(self.ring[g])]

    def evaluate(self, lat: float, lon: float, r: float) -> dict[str, Any]:
        """The local method at one radius (meters). Independent of the other radii."""
        dd = self.defect_distance_m(lat, lon)
        out: dict[str, Any] = {"defect_m": None if dd is None else round(dd, 2)}
        if self.defects_unlocated:
            return {**out, "outcome": "defect_location_unknown"}
        if dd is not None and dd <= r:
            return {**out, "outcome": "defect_within_radius"}
        kx, ky = _scale(lat)
        rx, ry = r / kx, r / ky
        i = np.nonzero((self.maxx >= lon - rx) & (self.minx <= lon + rx) & (self.maxy >= lat - ry)
                       & (self.miny <= lat + ry))[0]
        if not len(i):
            return {**out, "outcome": "no_boundary_within_radius"}
        ax, ay = (self.x1[i] - lon) * kx, (self.y1[i] - lat) * ky
        bx, by = (self.x2[i] - lon) * kx, (self.y2[i] - lat) * ky
        dx, dy = bx - ax, by - ay
        t = np.clip(-(ax * dx + ay * dy) / (dx * dx + dy * dy), 0.0, 1.0)
        d = np.hypot(ax + t * dx, ay + t * dy)
        dmin = float(d.min())
        out["edge_m"] = round(dmin, 3)
        if dmin > r:
            return {**out, "outcome": "no_boundary_within_radius"}
        if dmin < ON_BOUNDARY_M:
            return {**out, "outcome": "on_boundary"}
        near = [n for n in np.nonzero(d <= dmin + TIE_M)[0]]
        if any(self.area_sign[int(self.ring[i[n]])] == 0 for n in near):
            return {**out, "outcome": "orientation_unknown"}       # a ring of zero signed area
        # every nearest place must give the same side
        sides = {self._side(int(i[n]), float(t[n]), lat, lon) for n in near}
        if None in sides or len(sides) != 1:
            return {**out, "outcome": "ambiguous_nearest"}
        inner = sides.pop()
        w, crossings = self.winding(lat, lon)
        out.update(local_side="inside" if inner else "outside", winding=w, parity_inside=bool(crossings % 2))
        if (inner and w == 1) or (not inner and w == 0):
            return {**out, "outcome": "inside" if inner else "outside"}
        return {**out, "outcome": "inconsistent_winding"}


def staged(evals: list[dict[str, Any]], radii: list[float]) -> dict[str, Any]:
    """The staged result: the first radius whose outcome is not ``no_boundary_within_radius``."""
    for r, e in zip(radii, evals):
        if e["outcome"] != "no_boundary_within_radius":
            return {**e, "radius_m": r}
    return {**evals[-1], "outcome": "no_boundary_within_max_radius", "radius_m": radii[-1]}


def plus_far(final: dict[str, Any], prep: Prepared, lat: float, lon: float) -> dict[str, Any]:
    """Comparison policy: no boundary within the largest radius -> the far winding number, when clean."""
    if final["outcome"] != "no_boundary_within_max_radius":
        return final
    w, crossings = prep.winding(lat, lon)
    if prep.defects_unlocated:
        return {**final, "outcome": "defect_location_unknown", "winding": w}
    if 0 in prep.area_sign:                   # a ring of zero signed area: the far reading has no orientation
        return {**final, "outcome": "orientation_unknown", "winding": w}
    if w in (0, 1) and bool(crossings % 2) == (w == 1):
        return {**final, "outcome": "inside" if w == 1 else "outside", "by": "far_winding", "winding": w}
    return {**final, "outcome": "inconsistent_winding", "winding": w}


# --- per point ---------------------------------------------------------------------------------------
class Analyzer:
    def __init__(self, radii: list[float]) -> None:
        self.radii = radii
        self.prepared: dict[str, Prepared] = {}
        self.geoms: dict[str, Any] = {}
        self.mv_seconds: dict[str, float] = {}

    def prep(self, c: verify.Comp) -> Prepared:
        if c.ref not in self.prepared:
            self.prepared[c.ref] = Prepared(c.geom)
            self.geoms[c.ref] = c.geom
        return self.prepared[c.ref]

    def pair(self, c: verify.Comp, lat: float, lon: float, control: bool) -> dict[str, Any]:
        p = self.prep(c)
        pt = shapely.Point(lon, lat)
        evals, times = [], []
        for r in self.radii:
            t0 = time.perf_counter()
            evals.append(p.evaluate(lat, lon, r))
            times.append(time.perf_counter() - t0)
        final = staged(evals, self.radii)
        stop = self.radii.index(final["radius_m"])
        far = plus_far(final, p, lat, lon)
        kx, ky = _scale(lat)
        clips = []
        t0 = time.perf_counter()
        for r in self.radii:
            try:
                g = shapely.clip_by_rect(c.geom, lon - r / kx, lat - r / ky, lon + r / kx, lat + r / ky)
                clips.append(bool(g.contains(pt)))
            except shapely.errors.GEOSException:
                clips.append(None)
        clips_t = time.perf_counter() - t0
        w, crossings = p.winding(lat, lon)
        item: dict[str, Any] = {
            "zone_ref": c.ref, "source_id": c.source_id, "member": c.member, "feature_index": c.fi,
            "polygon_index": c.pi, "river": c.props["A31a_202"], "rank": c.rank, "control": control,
            "vertices": c.nverts, "segments": p.segments, "defects": int(len(p.defects)),
            "prepare_ms": round(p.seconds * 1000, 2),
            "per_radius": [{"radius_m": r, **e, "ms": round(dt * 1000, 3)} for r, e, dt in zip(self.radii, evals, times)],
            "local": final, "local_plus_far": far,
            "staged_ms": round(sum(times[:stop + 1]) * 1000, 3),
            "clip_rect": clips, "clip_rect_all_radii_ms": round(clips_t * 1000, 3),
            "winding": w, "parity_inside": bool(crossings % 2)}
        if control:
            item["geos_contains"] = bool(c.geom.contains(pt))
        else:
            t0 = time.perf_counter()
            fresh = c.ref not in verify._MV_CACHE
            item.update(verify.interpretations(c, lat, lon))
            spent = time.perf_counter() - t0
            if fresh:
                self.mv_seconds[c.ref] = spent
            item["interpretations_ms"] = round(spent * 1000, 2)
        return item


def _defect_points(sources, analyzer: Analyzer, rnd: random.Random, n: int) -> list[dict[str, Any]]:
    """Points 0-120 m from a located defect of randomly chosen invalid components (fixed seed)."""
    out = []
    for s in sources:
        pend = [c for c in s.pending if c.valid is False]
        for c in rnd.sample(pend, min(n, len(pend))):
            p = analyzer.prep(c)
            if not len(p.defects):
                continue
            x, y = p.defects[rnd.randrange(len(p.defects))]
            dist, ang = rnd.uniform(0, 120), rnd.uniform(0, 2 * math.pi)
            kx, ky = _scale(y)
            out.append({"category": "defect_near", "lat": round(y + dist * math.sin(ang) / ky, 9),
                        "lon": round(x + dist * math.cos(ang) / kx, 9), "note": f"{s.sid} {dist:.0f} m from a defect"})
    return out


def _rss_bytes() -> int:
    v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(v if platform.system() == "Darwin" else v * 1024)


def run(regions_file: Path, *, index: Path | None = None, settings: Path | None = None,
        source_ids: list[str] | None = None, per_category: int = 30, per_rank: int = 5, defect_points: int = 40,
        seed: int = 20261102, extra_points: list[tuple[float, float]] = (), log=lambda m: None) -> dict[str, Any]:
    from hererisk.flood.registry import load_flood_sources
    from hererisk.location.address_regions import load_regions
    started = time.time()
    cfg = load_settings(settings)["local_analysis"]
    radii = setting_radii(cfg)
    regs = load_flood_sources(regions_file)
    if source_ids:
        regs = [r for r in regs if r["source_id"] in source_ids]
        if len(regs) != len(set(source_ids)):
            raise ValueError("--source names a source that is not registered")
    n03 = {r["prefecture_code"]: r["address_n03"] for r in load_regions(regions_file)}
    regions: dict[tuple[str, ...], verify.Region] = {}
    sources = []
    t0 = time.time()
    for r in regs:
        key = tuple(r["service_prefectures"])
        if key not in regions:
            regions[key] = verify.Region([n03[p] for p in key])
        s = verify.SourceData(r, regions[key])
        s.scan(log)
        s.finish()
        sources.append(s)
    scan_seconds = time.time() - t0
    rss_after_scan = _rss_bytes()
    analyzer = Analyzer(radii)
    rnd = random.Random(seed)
    pts = [{"category": "given", "lat": lat, "lon": lon, "note": "--point"} for lat, lon in extra_points]
    pts += verify.sample_points(sources, seed, per_category, per_rank)
    pts += _defect_points(sources, analyzer, rnd, defect_points)
    provider = None
    if index is not None:
        from hererisk.location.flood_provider import FloodProvider     # read only: the Provider's answer
        provider = FloodProvider(regions_file, index)
    log(f"local analysis: {len(pts)} points")
    points = []
    for pt in pts:
        lat, lon = pt["lat"], pt["lon"]
        exp = verify.expected(sources, lat, lon)
        q = shapely.Point(lon, lat)
        pairs = []
        t_point = 0.0
        for s in sources:
            if s.sid not in exp["sources"]:
                continue
            for c in exp["sources"][s.sid]["pending"]:
                pairs.append(analyzer.pair(c, lat, lon, control=False))
            for k in s.tree.query(q):                       # valid components whose bounding box holds the point
                c = s.usable[int(k)]
                minx, miny, maxx, maxy = c.geom.bounds
                if minx <= lon <= maxx and miny <= lat <= maxy:
                    pairs.append(analyzer.pair(c, lat, lon, control=True))
        pending = [p for p in pairs if not p["control"]]
        t_point = sum(p["staged_ms"] for p in pending)
        item = {**pt, "expected_status": exp["status"], "pairs": pairs,
                "pending": len(pending), "staged_ms_pending": round(t_point, 3),
                "resolved_local": bool(pending) and all(p["local"]["outcome"] in DECIDED for p in pending),
                "resolved_local_plus_far": bool(pending) and all(p["local_plus_far"]["outcome"] in DECIDED for p in pending)}
        if provider is not None:
            act = provider.lookup(lat, lon)
            unknown = {(s["source_id"], z["zone_ref"]) for s in act.get("sources") or [] for z in s["unknowns"]}
            item["provider_status"] = act.get("status")
            item["provider_unknowns_match"] = unknown == {(p["source_id"], p["zone_ref"]) for p in pending}
        points.append(item)
    report = {"poc_version": POC_VERSION,
              "started_at": datetime.fromtimestamp(started, timezone.utc).isoformat(),
              "seconds": round(time.time() - started, 1), "scan_seconds": round(scan_seconds, 1),
              "inputs": {"regions_file": str(regions_file), "index": None if index is None else str(index),
                         "sources": [s.sid for s in sources], "seed": seed, "per_category": per_category,
                         "per_rank": per_rank, "defect_points": defect_points,
                         "points_given": [list(p) for p in extra_points], "local_analysis": cfg},
              "program": {"python": platform.python_version(), "shapely": shapely.__version__,
                          "numpy": np.__version__, "geos": shapely.geos_version_string},
              "memory": {"peak_rss_bytes": _rss_bytes(), "rss_after_source_scan_bytes": rss_after_scan,
                         "prepared_components": len(analyzer.prepared),
                         "prepared_bytes": sum(p.nbytes for p in analyzer.prepared.values()),
                         "prepared_segments": sum(p.segments for p in analyzer.prepared.values())},
              "points": points}
    report["summary"] = summarize(report, analyzer)
    report["_geoms"] = {ref: (analyzer.prepared[ref], analyzer.geoms[ref]) for ref in analyzer.prepared}
    return report


# --- summary -------------------------------------------------------------------------------------------
def _pct(n: int, d: int) -> float | None:
    return None if not d else round(100.0 * n / d, 1)


def _dist(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    v = sorted(values)
    return {"n": len(v), "median": round(statistics.median(v), 3), "p95": round(v[int(0.95 * (len(v) - 1))], 3),
            "max": round(v[-1], 3)}


def summarize(report: dict[str, Any], analyzer: Analyzer) -> dict[str, Any]:
    radii = report["inputs"]["local_analysis"]
    rlist = setting_radii(radii)
    pend = [p for pt in report["points"] for p in pt["pairs"] if not p["control"]]
    ctrl = [p for pt in report["points"] for p in pt["pairs"] if p["control"]]
    per_radius = {str(r): Counter() for r in rlist}
    per_radius_ms = {str(r): [] for r in rlist}
    for p in pend:
        for e in p["per_radius"]:
            per_radius[str(e["radius_m"])][e["outcome"]] += 1
            per_radius_ms[str(e["radius_m"])].append(e["ms"])
    final = Counter(p["local"]["outcome"] for p in pend)
    final_far = Counter(p["local_plus_far"]["outcome"] for p in pend)
    stop_radius = Counter(str(p["local"]["radius_m"]) for p in pend if p["local"]["outcome"] in DECIDED)
    # agreement between the methods (pending components)
    agree = Counter()
    for p in pend:
        reads = p.get("reads", {})
        loc = p["local"]["outcome"]
        mv, eo = reads.get("make_valid"), reads.get("even_odd")
        if loc in DECIDED:
            l_in = loc == "inside"
            agree["local=make_valid" if l_in == mv else "local!=make_valid"] += 1
            agree["local=even_odd" if l_in == eo else "local!=even_odd"] += 1
        agree["make_valid=even_odd" if mv == eo else "make_valid!=even_odd"] += 1
        agree["even_odd=winding_parity" if eo == p["parity_inside"] else "even_odd!=winding_parity"] += 1
        agree["readings " + p.get("agree", "?")] += 1
    # radius dependence: a decided reading that changes with the radius, or a decision lost by widening
    flips = lost = 0
    for p in pend + ctrl:
        decided = {e["outcome"] for e in p["per_radius"] if e["outcome"] in DECIDED}
        flips += len(decided) > 1
        outs = [e["outcome"] for e in p["per_radius"]]
        lost += any(a in DECIDED and b == "defect_within_radius" for a, b in zip(outs, outs[1:]))
    clip_dis = {str(r): Counter() for r in rlist}
    for p in pend:
        for r, c in zip(rlist, p["clip_rect"]):
            clip_dis[str(r)]["error" if c is None else "=even_odd" if c == p["reads"]["even_odd"] else "!=even_odd"] += 1
    # control: valid components, the local method against GEOS contains
    ctrl_final = Counter(p["local"]["outcome"] for p in ctrl)
    ctrl_bad = [p for p in ctrl if p["local"]["outcome"] in DECIDED and (p["local"]["outcome"] == "inside") != p["geos_contains"]]
    pts_pend = [pt for pt in report["points"] if pt["pending"]]
    by_cat: dict[str, Counter] = defaultdict(Counter)
    for pt in report["points"]:
        for p in pt["pairs"]:
            if not p["control"]:
                by_cat[pt["category"]][p["local"]["outcome"]] += 1
    prov = [pt for pt in report["points"] if "provider_unknowns_match" in pt]
    prep = list(analyzer.prepared.values())
    big = [p.seconds * 1000 for p in prep if p.segments > 100000]
    return {
        "points": len(report["points"]), "points_with_invalid": len(pts_pend),
        "pairs_invalid": len(pend), "pairs_control_valid": len(ctrl),
        "points_resolved_local": sum(pt["resolved_local"] for pt in pts_pend),
        "points_resolved_local_plus_far": sum(pt["resolved_local_plus_far"] for pt in pts_pend),
        "points_resolved_local_pct": _pct(sum(pt["resolved_local"] for pt in pts_pend), len(pts_pend)),
        "points_resolved_local_plus_far_pct": _pct(sum(pt["resolved_local_plus_far"] for pt in pts_pend), len(pts_pend)),
        "local_final": dict(final.most_common()), "local_plus_far_final": dict(final_far.most_common()),
        "decided_pct": _pct(sum(final[k] for k in DECIDED), len(pend)),
        "no_conclusion_after_max_radius_pct": _pct(final["no_boundary_within_max_radius"], len(pend)),
        "decided_at_radius": dict(sorted(stop_radius.items(), key=lambda kv: float(kv[0]))),
        "per_radius_outcomes": {k: dict(v.most_common()) for k, v in per_radius.items()},
        "per_radius_ms": {k: _dist(v) for k, v in per_radius_ms.items()},
        "staged_ms_per_pair": _dist([p["staged_ms"] for p in pend]),
        "staged_ms_per_point": _dist([pt["staged_ms_pending"] for pt in pts_pend]),
        "invalid_components_per_point": _dist([pt["pending"] for pt in pts_pend]),
        "prepare_ms_per_component": _dist([p.seconds * 1000 for p in prep]),
        "prepare_ms_components_over_100k_segments": _dist(big),
        "make_valid_first_call_ms": _dist([v * 1000 for v in analyzer.mv_seconds.values()]),
        "segments_per_component": _dist([float(p.segments) for p in prep]),
        "defects_per_invalid_component": _dist([float(len(p.defects)) for p in prep if not p.valid]),
        "agreement": dict(sorted(agree.items())),
        "radius_dependence": {"decided_reading_changes_with_radius": flips,
                              "decided_then_defect_within_larger_radius": lost},
        "clip_rect_vs_even_odd": {k: dict(v) for k, v in clip_dis.items()},
        "control_valid_local_final": dict(ctrl_final.most_common()),
        "control_valid_mismatches": len(ctrl_bad),
        "control_valid_mismatch_examples": [{k: p[k] for k in ("zone_ref", "local", "geos_contains")} for p in ctrl_bad[:5]],
        "by_category_local_final": {k: dict(v) for k, v in sorted(by_cat.items())},
        "provider_checked_points": len(prov),
        "provider_unknowns_match": sum(pt["provider_unknowns_match"] for pt in prov),
        "provider_status": dict(Counter(pt.get("provider_status") for pt in prov)),
        "memory": report["memory"]}


# --- report --------------------------------------------------------------------------------------------
def _svg(prep: Prepared, geom: Any, lat: float, lon: float, radii: list[float], title: str, note: str) -> str:
    kx, ky = _scale(lat)
    half = max(radii) * 1.6
    scale = 190.0 / half

    def lx(x):
        return 210 + (x - lon) * kx * scale

    def ly(y):
        return 230 - (y - lat) * ky * scale
    hx, hy = half / kx, half / ky
    i = np.nonzero((prep.maxx >= lon - hx) & (prep.minx <= lon + hx) & (prep.maxy >= lat - hy) & (prep.miny <= lat + hy))[0]
    lines = [f'<line x1="{lx(prep.x1[k]):.1f}" y1="{ly(prep.y1[k]):.1f}" x2="{lx(prep.x2[k]):.1f}" '
             f'y2="{ly(prep.y2[k]):.1f}" stroke="{"#1f5fa8" if not prep.ring_is_hole[prep.ring[k]] else "#2a8a4a"}" '
             f'stroke-width="1.5"/>' for k in i[:20000]]
    circles = [f'<circle cx="210" cy="230" r="{r * scale:.1f}" fill="none" stroke="#888" stroke-dasharray="3 3"/>'
               f'<text x="{212 + r * scale * 0.71:.0f}" y="{228 - r * scale * 0.71:.0f}" font-size="9" fill="#666">{r:g} m</text>'
               for r in radii]
    dfx = [f'<circle cx="{lx(x):.1f}" cy="{ly(y):.1f}" r="4" fill="#c0392b"/>' for x, y in prep.defects
           if abs(x - lon) <= hx and abs(y - lat) <= hy][:500]
    # overview: the whole component, decimated
    minx, miny, maxx, maxy = geom.bounds
    k2 = math.cos(math.radians(lat))
    s2 = 380.0 / max((maxx - minx) * k2, maxy - miny, 1e-9)

    def ox(x):
        return 440 + (x - minx) * k2 * s2

    def oy(y):
        return 420 - (y - miny) * s2
    paths = []
    for n, r in enumerate([geom.exterior, *geom.interiors]):
        c = np.asarray(r.coords)
        step = max(1, len(c) // 6000)
        d = " ".join(f"{ox(x):.1f},{oy(y):.1f}" for x, y in c[::step])
        paths.append(f'<polyline points="{d}" fill="none" stroke="{"#1f5fa8" if n == 0 else "#2a8a4a"}" stroke-width="0.6"/>')
    odfx = [f'<circle cx="{ox(x):.1f}" cy="{oy(y):.1f}" r="2.5" fill="#c0392b"/>' for x, y in prep.defects[:2000]]
    marker = f'<rect x="{ox(lon) - 4:.1f}" y="{oy(lat) - 4:.1f}" width="8" height="8" fill="none" stroke="#000" stroke-width="1.5"/>'
    esc = (title + " | " + note).replace("&", "&amp;").replace("<", "&lt;")
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="840" height="460" font-family="sans-serif">'
            '<rect width="840" height="460" fill="#fff"/>'
            f'<text x="10" y="18" font-size="11">{esc}</text>'
            '<text x="10" y="34" font-size="10" fill="#555">左: 地点周辺（原典の頂点のみ、青=外周 緑=穴 赤=問題箇所 破線=解析半径）'
            ' 右: Polygon全体（間引き表示、□=地点）</text>'
            '<clipPath id="w"><rect x="20" y="40" width="380" height="380"/></clipPath>'
            '<rect x="20" y="40" width="380" height="380" fill="none" stroke="#ccc"/>'
            f'<g clip-path="url(#w)">{"".join(lines)}{"".join(dfx)}{"".join(circles)}'
            '<circle cx="210" cy="230" r="3.5" fill="#000"/></g>'
            f'<rect x="440" y="40" width="380" height="380" fill="none" stroke="#ccc"/>{"".join(paths)}{"".join(odfx)}{marker}'
            '</svg>')


def write_report(report: dict[str, Any], analyzer_geoms: dict[str, tuple[Prepared, Any]], directory: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path(directory) / f"flood-local-analysis-{stamp}"
    out.mkdir(parents=True, exist_ok=False)
    (out / "summary.json").write_text(json.dumps({k: v for k, v in report.items() if k != "points"},
                                                 ensure_ascii=False, indent=1), encoding="utf-8")
    with open(out / "points.jsonl", "w", encoding="utf-8") as f:
        for r in report["points"]:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    cases = representative(report)
    (out / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=1), encoding="utf-8")
    svg_dir = out / "svg"
    svg_dir.mkdir()
    radii = setting_radii(report["inputs"]["local_analysis"])
    for n, c in enumerate(cases):
        prep, geom = analyzer_geoms[c["zone_ref"]]
        name = f"{n:02d}-{c['group'].replace(' ', '_').replace('/', '_')}.svg"
        c["svg"] = f"svg/{name}"
        (svg_dir / name).write_text(_svg(prep, geom, c["lat"], c["lon"], radii, f"{c['group']} {c['river']} rank {c['rank']}",
                                         f"local={c['local']} make_valid={c['reads'].get('make_valid')} "
                                         f"even_odd={c['reads'].get('even_odd')} edge={c['edge_m']} m defect={c['defect_m']} m"),
                                    encoding="utf-8")
    (out / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def representative(report: dict[str, Any], per_group: int = 2) -> list[dict[str, Any]]:
    """The given points' invalid components, then a few per final outcome of the local method."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pt in report["points"]:
        for p in pt["pairs"]:
            if p["control"]:
                continue
            key = "given" if pt["category"] == "given" else p["local"]["outcome"]
            groups[key].append({"group": key, "category": pt["category"], "lat": pt["lat"], "lon": pt["lon"],
                                "zone_ref": p["zone_ref"], "source_id": p["source_id"], "river": p["river"],
                                "rank": p["rank"], "vertices": p["vertices"], "defects": p["defects"],
                                "local": p["local"]["outcome"], "decided_at_m": p["local"]["radius_m"],
                                "edge_m": p["local"].get("edge_m"), "defect_m": p["local"].get("defect_m"),
                                "reads": p.get("reads", {}), "reason": p.get("reason"),
                                "per_radius": [e["outcome"] for e in p["per_radius"]]})
    out = []
    for key in ["given", *sorted(k for k in groups if k != "given")]:
        items = groups.get(key, [])
        out.extend(items if key == "given" else items[:per_group])
    return out


def summary_text(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [f"flood local analysis {report['poc_version']}  seed={report['inputs']['seed']}  points={s['points']}  "
             f"({report['seconds']}s, source scan {report['scan_seconds']}s)  DIAGNOSIS ONLY",
             f"radii: {setting_radii(report['inputs']['local_analysis'])} m",
             f"points with invalid components: {s['points_with_invalid']}  resolved: local {s['points_resolved_local']} "
             f"({s['points_resolved_local_pct']}%), local+far {s['points_resolved_local_plus_far']} "
             f"({s['points_resolved_local_plus_far_pct']}%)",
             f"invalid pairs {s['pairs_invalid']}: local {s['local_final']}",
             f"  local+far (comparison only): {s['local_plus_far_final']}",
             f"  decided at radius: {s['decided_at_radius']}",
             "per radius: " + "; ".join(f"{k} m {v}" for k, v in s["per_radius_outcomes"].items()),
             f"agreement: {s['agreement']}",
             f"radius dependence: {s['radius_dependence']}",
             f"clip_rect vs even_odd: {s['clip_rect_vs_even_odd']}",
             f"control (valid) pairs {s['pairs_control_valid']}: {s['control_valid_local_final']}  "
             f"mismatches with GEOS contains: {s['control_valid_mismatches']}",
             f"time: staged per point {s['staged_ms_per_point']} ms; per pair {s['staged_ms_per_pair']} ms; "
             f"prepare per component {s['prepare_ms_per_component']} ms",
             f"memory: peak RSS {s['memory']['peak_rss_bytes'] / 2**20:.0f} MiB, prepared "
             f"{s['memory']['prepared_components']} components {s['memory']['prepared_bytes'] / 2**20:.1f} MiB"]
    if s["provider_checked_points"]:
        lines.append(f"provider: unknowns == analysed invalid components at {s['provider_unknowns_match']}/"
                     f"{s['provider_checked_points']} points; statuses {s['provider_status']} (unchanged; not modified)")
    for pt in report["points"]:
        if pt["category"] == "given":
            lines.append(f"given {pt['lat']},{pt['lon']}: {pt['pending']} invalid components")
            for p in pt["pairs"]:
                if not p["control"]:
                    lines.append(f"  {p['river']} rank {p['rank']} f{p['feature_index']}: "
                                 f"{[e['outcome'] for e in p['per_radius']]} -> {p['local']['outcome']} "
                                 f"(edge {p['local'].get('edge_m')} m, defect {p['local'].get('defect_m')} m, "
                                 f"winding {p['winding']}); readings {p.get('reads')}")
    lines.append("note: diagnosis only; the Flood Provider still answers unknown for these components")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    import argparse
    from hererisk.flood.settings import FloodSettingsError
    parser = argparse.ArgumentParser(prog="python -m hererisk.flood local-analysis")
    parser.add_argument("--regions", type=Path, required=True)
    parser.add_argument("--index", type=Path, help="also confirm the Provider's unknowns (read only)")
    parser.add_argument("--settings", type=Path, help='{"local_analysis": {...}} (default: the built-in values)')
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--per-category", type=int, default=30)
    parser.add_argument("--per-rank", type=int, default=5)
    parser.add_argument("--defect-points", type=int, default=40)
    parser.add_argument("--seed", type=int, default=20261102)
    parser.add_argument("--point", action="append", default=[], metavar="LAT,LON")
    parser.add_argument("--report-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        points = [tuple(float(v) for v in p.split(",")) for p in args.point]
        if any(len(p) != 2 for p in points):
            raise ValueError
    except ValueError:
        sys.stderr.write("flood local-analysis: --point must be LAT,LON\n")
        return 2
    try:
        load_settings(args.settings)
    except FloodSettingsError as exc:
        sys.stderr.write(f"flood local-analysis: {exc}\n")
        return 2
    try:
        report = run(args.regions, index=args.index, settings=args.settings, source_ids=args.source or None,
                     per_category=args.per_category, per_rank=args.per_rank, defect_points=args.defect_points,
                     seed=args.seed, extra_points=points, log=lambda m: sys.stderr.write(m + "\n"))
    except Exception as exc:    # noqa: BLE001 - the analysis itself failed
        sys.stderr.write(f"flood local-analysis: ERROR ({type(exc).__name__}: {exc})\n")
        return 3
    geoms = report.pop("_geoms")
    print(summary_text(report))
    if args.report_dir:
        print(f"report: {write_report(report, geoms, args.report_dir)}")
    s = report["summary"]
    bad = s["control_valid_mismatches"] or s["radius_dependence"]["decided_reading_changes_with_radius"] \
        or (s["provider_checked_points"] and s["provider_unknowns_match"] != s["provider_checked_points"])
    return 1 if bad else 0
