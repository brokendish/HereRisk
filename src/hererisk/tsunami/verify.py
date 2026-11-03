"""Independent check of the tsunami index and provider against the GML of the same ZIP (Phase 4-M).

    python -m hererisk.tsunami verify --regions <regions.json> --index <index.sqlite>
        [--sample 3000] [--report-dir DIR]

The expectations are computed without the shared Polygon Engine and without shapely / GEOS:

* the GML (``A40-<yy>_<pref>.xml``, the other official encoding in the ZIP) is read with the standard
  library: ``gml:Curve`` / ``gml:OrientableCurve`` / ``gml:Surface`` / ``ksj:ExpectedTsunamiInundatedArea``,
  positions "lat lon" with 8 decimals, read exactly as integers of 10^-8 degree
* the index is read with ``sqlite3`` and a small WKB reader (not shapely)
* checks: feature and component counts; ring / vertex counts and every vertex (the index's float rounded
  half-up to 8 decimals equals the GML integer); FID = GML id; prefecture name / code and the depth text
  (byte for byte); the validity class against an exact integer segment check (self-touch, crossing,
  overlap, too few points / zero area, hole outside the shell, nested holes, two rings touching twice);
  and, for sampled points, ``TsunamiProvider.lookup`` against an even-odd test with holes and the
  distance to the GML boundary (inside / outside are compared only farther than ``TOL_DEG`` from the
  boundary; vertices of the indexed geometry must be boundary contacts; pending components must be
  listed when the point is in their bounding box)

Not verified here (reported): interiors disconnected by chains of touches over three or more rings; the
A40 attribute meanings beyond the product specification's text; points near the boundary closer than
``TOL_DEG`` (inside / outside there depends on the float coordinates). Nothing is repaired.
"""

from __future__ import annotations

import json
import random
import sqlite3
import struct
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from hererisk.tsunami import a40
from hererisk.tsunami.registry import load_tsunami_sources

GML_NS = "http://schemas.opengis.net/gml/3.2.1"
KSJ_NS = "http://nlftp.mlit.go.jp/ksj/schemas/ksj-app"
XLINK = "{http://www.w3.org/1999/xlink}href"
SCALE = 10 ** 8
TOL_DEG = 2e-8          # > the 5e-9 degree difference between the GeoJSON floats and the 8-decimal GML
OFFSET_DEG = 2e-6       # sampled points beside an edge midpoint (about 0.2 m)


def _g(tag: str) -> str:
    return f"{{{GML_NS}}}{tag}"


def _k(tag: str) -> str:
    return f"{{{KSJ_NS}}}{tag}"


# --- GML ---------------------------------------------------------------------------------------------
def _to_int(token: str) -> int:
    d = Decimal(token).scaleb(8)
    if d != d.to_integral_value():
        raise ValueError("a GML position has more than 8 decimals")
    return int(d)


def read_gml(fh) -> list[dict[str, Any]]:
    """Features in document order: {gml_id, name, code, depth, components: [[ring [(x, y) int]]]}."""
    curves: dict[str, list[tuple[int, int]]] = {}
    orientable: dict[str, tuple[str, str]] = {}
    surfaces: dict[str, list[list[list[str]]]] = {}
    features = []
    gid = _g("id")
    for _, el in ET.iterparse(fh, events=("end",)):
        if el.tag == _g("Curve"):
            pos = []
            for pl in el.iter(_g("posList")):
                t = pl.text.split()
                if len(t) % 2:
                    raise ValueError("a posList has an odd number of values")
                pts = [(_to_int(t[i + 1]), _to_int(t[i])) for i in range(0, len(t), 2)]   # "lat lon" -> (x, y)
                pos.extend(pts if not pos else pts[1:] if pts[0] == pos[-1] else pts)
            curves[el.get(gid)] = pos
            el.clear()
        elif el.tag == _g("OrientableCurve"):
            base = el.find(_g("baseCurve")).get(XLINK).lstrip("#")
            orientable[el.get(gid)] = (base, el.get("orientation", "+").strip())
            el.clear()
        elif el.tag == _g("Surface"):
            patches = []
            for patch in el.iter(_g("PolygonPatch")):
                rings = []
                for part in [patch.find(_g("exterior")), *patch.findall(_g("interior"))]:
                    rings.append([m.get(XLINK).lstrip("#") for m in part.iter(_g("curveMember"))])
                patches.append(rings)
            surfaces[el.get(gid)] = patches
            el.clear()
        elif el.tag == _k("ExpectedTsunamiInundatedArea"):
            features.append({"gml_id": el.get(gid), "bounds": el.find(_k("bounds")).get(XLINK).lstrip("#"),
                             "name": el.findtext(_k("prefectureName")), "code": el.findtext(_k("prefectureCode")),
                             "depth": el.findtext(_k("classificationOfWaterDepth"))})
            el.clear()

    def curve(ref: str) -> list[tuple[int, int]]:
        if ref in curves:
            return curves[ref]
        base, orient = orientable[ref]
        if orient not in ("+", "-"):
            raise ValueError("an OrientableCurve orientation is neither + nor -")
        return curves[base] if orient == "+" else curves[base][::-1]

    for f in features:
        comps = []
        for rings in surfaces[f.pop("bounds")]:
            out = []
            for members in rings:
                ring: list[tuple[int, int]] = []
                for m in members:
                    c = curve(m)
                    ring.extend(c if not ring else c[1:] if c[0] == ring[-1] else c)
                out.append(ring)
            comps.append(out)
        f["components"] = comps
    return features


# --- WKB (index) ---------------------------------------------------------------------------------------
def read_wkb_polygon(b: bytes) -> list[list[tuple[float, float]]]:
    order = "<" if b[0] == 1 else ">"
    kind, n = struct.unpack_from(order + "II", b, 1)
    if kind != 3:
        raise ValueError("not a 2-D WKB polygon")
    off, rings = 9, []
    for _ in range(n):
        (k,) = struct.unpack_from(order + "I", b, off)
        off += 4
        vals = struct.unpack_from(order + f"{2 * k}d", b, off)
        off += 16 * k
        rings.append([(vals[i], vals[i + 1]) for i in range(0, 2 * k, 2)])
    return rings


def _round8(v: float) -> int:
    return int(Decimal(repr(v)).scaleb(8).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# --- exact segment checks on integer coordinates --------------------------------------------------------
def _orient(a, b, c) -> int:
    v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return (v > 0) - (v < 0)


def _on_seg(a, b, p) -> bool:
    return min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])


def _pair(s, t) -> tuple[str | None, set]:
    a, b = s
    c, d = t
    o1, o2, o3, o4 = _orient(a, b, c), _orient(a, b, d), _orient(c, d, a), _orient(c, d, b)
    if o1 == o2 == o3 == o4 == 0:
        if not (max(min(a[0], b[0]), min(c[0], d[0])) <= min(max(a[0], b[0]), max(c[0], d[0]))
                and max(min(a[1], b[1]), min(c[1], d[1])) <= min(max(a[1], b[1]), max(c[1], d[1]))):
            return None, set()
        shared = {p for p in (a, b) if _on_seg(c, d, p)} | {p for p in (c, d) if _on_seg(a, b, p)}
        return ("overlap" if len(shared) > 1 else "touch"), shared
    if o1 * o2 < 0 and o3 * o4 < 0:
        return "crossing", set()
    pts = {p for p, o, seg in ((c, o1, s), (d, o2, s), (a, o3, t), (b, o4, t)) if o == 0 and _on_seg(*seg, p)}
    return ("touch" if pts else None), pts


def _area2(r) -> int:
    return sum(r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1] for i in range(len(r) - 1))


def _inside_even_odd(rings, x, y) -> bool:
    inside = False
    for r in rings:
        for (ax, ay), (bx, by) in zip(r, r[1:]):
            if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
                inside = not inside
    return inside


def defects(rings: list[list[tuple[int, int]]]) -> Counter:
    """Exact defect kinds of one component (integer coordinates, consecutive duplicates collapsed)."""
    out: Counter = Counter()
    clean = []
    for r in rings:
        c = [p for i, p in enumerate(r) if i == 0 or p != r[i - 1]]
        if len(c) < 4 or c[0] != c[-1] or _area2(c) == 0:
            out["too_few_points_or_zero_area"] += 1
        clean.append(c)
    segs = [(min(a[0], b[0]), max(a[0], b[0]), min(a[1], b[1]), max(a[1], b[1]), k, i, (a, b))
            for k, r in enumerate(clean) for i, (a, b) in enumerate(zip(r, r[1:]))]
    segs.sort()
    n_per_ring = [len(r) - 1 for r in clean]
    ring_touch: dict[tuple[int, int], set] = defaultdict(set)
    for i, s in enumerate(segs):
        for t in segs[i + 1:]:
            if t[0] > s[1]:
                break
            if t[2] > s[3] or t[3] < s[2]:
                continue
            (k1, i1), (k2, i2) = s[4:6], t[4:6]
            kind, pts = _pair(s[6], t[6])
            if kind is None:
                continue
            if k1 == k2:
                n = n_per_ring[k1]
                adjacent = abs(i1 - i2) == 1 or abs(i1 - i2) == n - 1
                if adjacent and kind == "touch":
                    continue                               # the shared vertex of consecutive edges
                out[f"ring_self_{kind}"] += 1
            elif kind == "touch":
                ring_touch[tuple(sorted((k1, k2)))].update(pts)
            else:
                out[f"rings_{kind}"] += 1
    out["rings_touch_twice"] += sum(1 for p in ring_touch.values() if len(p) > 1)
    shell, holes = clean[0], clean[1:]
    for h in holes:
        if h and not _inside_even_odd([shell], *_probe(h, shell)):
            out["hole_outside_shell"] += 1
    for a_i, a in enumerate(holes):
        for b_i, b in enumerate(holes):
            if a_i != b_i and a and b and _inside_even_odd([b], *_probe(a, b)):
                out["nested_holes"] += 1
    return +out


def feature_level(components: list[list[list[tuple[int, int]]]]) -> set[int]:
    """Components of one feature whose interiors overlap or that share an edge with another (exact)."""
    involved: set[int] = set()
    segs = [[(a, b) for r in c for a, b in zip(r, r[1:]) if a != b] for c in components]
    for i in range(len(components)):
        for j in range(i + 1, len(components)):
            hit = any(_pair(s, t)[0] in ("overlap", "crossing") for s in segs[i] for t in segs[j]
                      if max(min(s[0][0], s[1][0]), min(t[0][0], t[1][0])) <= min(max(s[0][0], s[1][0]), max(t[0][0], t[1][0])))
            for a, b in ((i, j), (j, i)):
                if hit:
                    break
                bverts = {p for r in components[b] for p in r}
                for p in (q for r in components[a][:1] for q in r):
                    if p not in bverts and _inside_even_odd(components[b], *p) \
                            and min(_dist_seg(*p, *s[0], *s[1]) for s in segs[b]) > 0:
                        hit = True
                        break
            if hit:
                involved.update((i, j))
    return involved


def _probe(ring, other) -> tuple[float, float]:
    """A vertex of ``ring`` that is not a vertex of ``other`` (a touching vertex says nothing)."""
    vs = set(other)
    for p in ring:
        if p not in vs:
            return p
    return ring[0]


# --- point relation ------------------------------------------------------------------------------------
def _dist_seg(px, py, ax, ay, bx, by) -> float:
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return ((px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2) ** 0.5


def expect(rings_deg, x, y) -> str:
    d = min(_dist_seg(x, y, *a, *b) for r in rings_deg for a, b in zip(r, r[1:]))
    if d <= TOL_DEG:
        return "near_boundary"
    return "inside" if _inside_even_odd(rings_deg, x, y) else "outside"


def run(regions: Path, index: Path, sample: int, log=lambda m: None) -> dict[str, Any]:
    from hererisk.location.tsunami_provider import TsunamiProvider     # the system under test
    checks: Counter = Counter()
    sources = load_tsunami_sources(regions)
    db = sqlite3.connect(f"file:{Path(index)}?mode=ro", uri=True)
    rows = db.execute("SELECT source_id, file_name, feature_index, polygon_index, fid, validity, kind, prefecture_name, "
                      "prefecture_code, depth_label, zone_ref, minx, miny, maxx, maxy, wkb FROM components "
                      "ORDER BY rowid").fetchall()
    db.close()
    by_file: dict[str, dict[int, list]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by_file[r[1]][r[2]].append(r)
    comps = []          # (source_id, zone_ref, valid in index, gml rings as degrees, index bbox, gml defects)
    depth_counts: Counter = Counter()
    invalid_by_depth: Counter = Counter()
    for src in sources:
        for f in src["files"]:
            z, m = a40.open_zip(f["path"])
            with z, z.open(m["gml"]) as fh:
                log(f"GML {f['file_name']}")
                gml = read_gml(fh)
            idx = by_file.get(f["file_name"], {})
            checks["feature_count_equal" if len(gml) == len(idx) else "FEATURE_COUNT_DIFFERS"] += 1
            for fi, g in enumerate(gml):
                ir = idx.get(fi, [])
                if g["gml_id"] != f"id{fi}" or not ir or ir[0][4] != fi:
                    checks["FID_DIFFERS_FROM_GML_ID"] += 1
                    continue
                checks["fid_equals_gml_id"] += 1
                attrs_ok = all((r[7], r[8], r[9]) == (g["name"], g["code"], g["depth"]) for r in ir)
                checks["attributes_equal" if attrs_ok else "ATTRIBUTES_DIFFER"] += 1
                depth_counts[g["depth"]] += 1
                if len(ir) != len(g["components"]):
                    checks["COMPONENT_COUNT_DIFFERS"] += 1
                    continue
                involved = feature_level(g["components"]) if len(g["components"]) > 1 else set()
                for pi, (r, grings) in enumerate(zip(sorted(ir, key=lambda r: r[3]), g["components"])):
                    irings = read_wkb_polygon(r[15])
                    same = len(irings) == len(grings) and all(
                        len(a) == len(b) and all((_round8(x), _round8(y)) == p for (x, y), p in zip(a, b))
                        for a, b in zip(irings, grings))
                    checks["geometry_round8_equal" if same else "GEOMETRY_DIFFERS"] += 1
                    found = defects(grings)
                    mine = "invalid_geometry" if found else "feature_invalid_component" if pi in involved else "valid"
                    idx_valid = r[5] == "valid"
                    checks["validity_equals_independent" if mine == r[5] else "VALIDITY_DIFFERS"] += 1
                    for k in found:
                        checks[f"defect:{k}"] += 1
                    if not idx_valid:
                        invalid_by_depth[r[9]] += 1
                        checks[f"index_{r[5]}:{r[6]}"] += 1
                    deg = [[(x / SCALE, y / SCALE) for x, y in ring] for ring in grings]
                    comps.append((r[0], r[10], idx_valid, deg, (r[11], r[12], r[13], r[14]), irings))
    checks["components_total"] = len(comps)
    log("points")
    provider = TsunamiProvider(regions, index)
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for n, c in enumerate(comps):
        minx, miny, maxx, maxy = c[4]
        for gx in range(int(minx * 100) - 1, int(maxx * 100) + 2):
            for gy in range(int(miny * 100) - 1, int(maxy * 100) + 2):
                grid[(gx, gy)].append(n)
    rnd = random.Random(20261103)
    picks = rnd.sample(range(len(comps)), min(sample, len(comps)))
    picks += [n for n, c in enumerate(comps) if not c[2] or len(c[3]) > 1]      # every pending / holed component
    points = []
    for n in picks:
        sid, ref, valid, deg, (minx, miny, maxx, maxy), irings = comps[n]
        if not valid:
            points += [("pending_bbox_centre", (minx + maxx) / 2, (miny + maxy) / 2, n),
                       ("pending_bbox_corner", minx, maxy, n)]
            continue
        x, y = irings[0][rnd.randrange(len(irings[0]) - 1)]
        points.append(("vertex", x, y, n))
        for k, ring in enumerate(irings):
            i = rnd.randrange(len(ring) - 1)
            (ax, ay), (bx, by) = ring[i], ring[i + 1]
            L = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5 or 1.0
            mx, my, nx, ny = (ax + bx) / 2, (ay + by) / 2, -(by - ay) / L, (bx - ax) / L
            tag = "hole_edge" if k else "edge"
            points += [(f"{tag}_side_a", mx + nx * OFFSET_DEG, my + ny * OFFSET_DEG, n),
                       (f"{tag}_side_b", mx - nx * OFFSET_DEG, my - ny * OFFSET_DEG, n)]
    kinds: Counter = Counter()
    ms = []
    multi = 0
    for kind, x, y, n in points:
        t0 = time.perf_counter()
        section = provider.lookup(y, x)
        ms.append((time.perf_counter() - t0) * 1000)
        if section["status"] == "not_available":
            kinds[f"{kind}:outside_service_region"] += 1
            continue
        if section["status"] == "error":
            checks["PROVIDER_ERROR"] += 1
            continue
        kinds[f"{kind}:compared"] += 1
        got = {}
        for s in section["sources"]:
            for key in ("zones", "boundary_contacts", "unknowns"):
                for z in s[key]:
                    got[z["zone_ref"]] = key
        multi += sum(1 for v in got.values() if v == "zones") > 1
        cand = {m for gx in (int(x * 100),) for gy in (int(y * 100),) for m in grid.get((gx, gy), [])}
        ok = True
        for m in cand:
            sid, ref, valid, deg, (minx, miny, maxx, maxy), _ = comps[m]
            have = got.get(ref)
            if not valid:
                inbox = minx <= x <= maxx and miny <= y <= maxy
                near_box = min(abs(x - minx), abs(x - maxx), abs(y - miny), abs(y - maxy)) <= TOL_DEG
                if have not in (None, "unknowns") or (inbox and have is None) or (not inbox and have and not near_box):
                    ok = False
                checks[f"expect_pending_{'in' if inbox else 'out_of'}_bbox"] += 1
                continue
            e = expect(deg, x, y)
            checks[f"expect_{e}"] += 1
            if e == "inside" and have != "zones" or e == "outside" and have is not None:
                ok = False
            elif e == "near_boundary":
                checks["near_boundary_not_strict"] += 1
                if have == "unknowns":
                    ok = False
        if kind == "vertex":
            ok = ok and got.get(comps[n][1]) == "boundary_contacts"
        if not ok:
            checks["POINT_DIFFERS"] += 1
        else:
            checks["point_equals_independent"] += 1
    ms.sort()
    return {"started_at": datetime.now(timezone.utc).isoformat(), "tol_deg": TOL_DEG, "offset_deg": OFFSET_DEG,
            "checks": dict(sorted(checks.items())), "failed": sorted(k for k in checks if k.isupper()),
            "depth_labels_in_gml": dict(depth_counts), "not_valid_by_depth_label": dict(invalid_by_depth),
            "point_kinds": dict(sorted(kinds.items())), "points_with_several_zones": multi,
            "lookup_ms": {"n": len(ms), "median": round(ms[len(ms) // 2], 3) if ms else None,
                          "p95": round(ms[int(0.95 * (len(ms) - 1))], 3) if ms else None},
            "not_verified": ["interiors disconnected by touches over three or more rings",
                             f"inside / outside within {TOL_DEG} degree of the boundary",
                             "the meaning of A40_001..A40_003 beyond the product specification text"]}


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="python -m hererisk.tsunami verify")
    p.add_argument("--regions", type=Path, required=True)
    p.add_argument("--index", type=Path, required=True)
    p.add_argument("--sample", type=int, default=3000, help="valid components sampled for point checks")
    p.add_argument("--report-dir", type=Path)
    args = p.parse_args(argv)
    out = run(args.regions, args.index, args.sample, log=lambda m: sys.stderr.write(f"tsunami verify: {m}\n"))
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if args.report_dir:
        d = Path(args.report_dir) / f"tsunami-verify-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
        d.mkdir(parents=True)
        (d / "summary.json").write_text(text + "\n", encoding="utf-8")
        sys.stderr.write(f"tsunami verify: report {d}\n")
    print(text)
    return 1 if out["failed"] else 0
