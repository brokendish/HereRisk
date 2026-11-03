"""Phase 4-L: shared validity (hererisk.common.polygon.validity) and official relation
(hererisk.common.polygon.relation), compared with the existing flood code on the same geometry.

Synthetic geometry only. The flood functions (``flood.index.classify``, ``a31a.check_coordinates``,
``FloodProvider`` on a synthetic index) are the reference; the shared modules must give the same
classes and the same zone sets, must never evaluate an invalid polygon (Codex B1 included), must not
depend on a hazard package and must not be wired into the product yet.
"""

from __future__ import annotations

import math
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

shapely = pytest.importorskip("shapely")

from shapely.geometry import Point, Polygon                              # noqa: E402

from hererisk.common.polygon import relation as rel                     # noqa: E402
from hererisk.common.polygon import validity as val                     # noqa: E402
from hererisk.flood import a31a                                         # noqa: E402
from hererisk.flood.errors import FloodIndexError                       # noqa: E402
from hererisk.flood.index import build_index, classify                  # noqa: E402
from hererisk.location.flood_provider import FloodProvider              # noqa: E402
from test_flood_provider import data, feat, poly, source, two_sources, write_a31a, write_regions   # noqa: E402,F401

REPO = Path(__file__).resolve().parents[2]
LAT0, LON0 = 35.0, 139.0
KX = 111320.0 * math.cos(math.radians(LAT0))


def ll(x, y):            # meters east / north of (139.0, 35.0) -> [lon, lat]
    return [LON0 + x / KX, LAT0 + y / 111320.0]


def ring(*pts):
    return [ll(*p) for p in pts]


def sqm(x0, y0, x1, y1):
    return ring((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))


B1 = ring((0, 0), (100, 0), (100, 100), (0, 100), (0, 0), (0, 100), (100, 100), (100, 0), (0, 0),
          (-100, 0), (0, -100), (0, 0))
U = ring((0, 0), (300, 0), (300, 300), (200, 300), (200, 100), (100, 100), (100, 300), (0, 300), (0, 0))

# name: (component polygons of one feature, expected common classes)
VALIDITY_CASES = {
    "square": ([[sqm(0, 0, 100, 100)]], ["valid"]),
    "hole": ([[sqm(0, 0, 100, 100), sqm(40, 40, 60, 60)]], ["valid"]),
    "hole touching the shell at one point": ([[sqm(0, 0, 100, 100), ring((0, 50), (30, 40), (30, 60), (0, 50))]], ["valid"]),
    "hole touching the shell at two points": ([[sqm(0, 0, 100, 100), ring((0, 50), (50, 30), (100, 50), (50, 70), (0, 50))]],
                                              ["invalid_geometry"]),
    "self-touch": ([[ring((0, 0), (150, 0), (120, 60), (180, 60), (150, 0), (300, 0), (300, 300), (0, 300), (0, 0))]],
                   ["invalid_geometry"]),
    "self-crossing (bow-tie)": ([[ring((0, 0), (100, 100), (100, 0), (0, 100), (0, 0))]], ["invalid_geometry"]),
    "duplicate vertex": ([[ring((0, 0), (100, 0), (100, 0), (100, 100), (0, 100), (0, 0))]], ["valid"]),
    "duplicate edge (spike)": ([[ring((0, 0), (100, 0), (200, 0), (100, 0), (100, 100), (0, 100), (0, 0))]],
                               ["invalid_geometry"]),
    "zero-area ring": ([[ring((0, 0), (100, 0), (200, 0), (0, 0))]], ["invalid_geometry"]),
    "collapsed ring": ([[ring((0, 0), (100, 0), (0, 0), (0, 0))]], ["invalid_geometry"]),
    "hole outside the shell": ([[sqm(0, 0, 100, 100), sqm(200, 200, 250, 250)]], ["invalid_geometry"]),
    "B1 (Codex, cancelled double edge)": ([[B1]], ["invalid_geometry"]),
    "U": ([[U]], ["valid"]),
    "MultiPolygon, apart": ([[sqm(0, 0, 100, 100)], [sqm(200, 0, 300, 100)]], ["valid", "valid"]),
    "MultiPolygon, touching at a vertex": ([[sqm(0, 0, 100, 100)], [sqm(100, 100, 200, 200)]], ["valid", "valid"]),
    "MultiPolygon, overlapping": ([[sqm(0, 0, 100, 100)], [sqm(50, 50, 150, 150)], [sqm(400, 0, 500, 100)]],
                                  ["feature_invalid_component", "feature_invalid_component", "valid"]),
    "MultiPolygon, shared edge": ([[sqm(0, 0, 100, 100)], [sqm(100, 0, 200, 100)]],
                                  ["feature_invalid_component", "feature_invalid_component"]),
    "MultiPolygon, one inside another": ([[sqm(0, 0, 300, 300)], [sqm(100, 100, 200, 200)]],
                                         ["feature_invalid_component", "feature_invalid_component"]),
    "MultiPolygon, island in a hole": ([[sqm(0, 0, 300, 300), sqm(50, 50, 250, 250)], [sqm(100, 100, 200, 200)]],
                                       ["valid", "valid"]),
    "MultiPolygon, invalid and valid overlapping": ([[ring((0, 0), (100, 100), (100, 0), (0, 100), (0, 0))], [sqm(20, 20, 80, 80)]],
                                                    ["invalid_geometry", "valid"]),
}


def as_lists(polys):
    return [[[list(p) for p in r] for r in rings] for rings in polys]


# --- validity -------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(VALIDITY_CASES))
def test_validity_equals_the_flood_index_classification(name) -> None:
    polys, expected = VALIDITY_CASES[name]
    polys = as_lists(polys)
    got = val.classify_components(polys)
    flood = classify(polys)
    assert [c.validity for c in got] == expected, name
    assert [c.polygon_index for c in got] == list(range(len(polys)))
    for c, (fpoly, usable, reason, detail) in zip(got, flood):
        assert c.usable is usable and (None if c.usable else c.validity) == reason, name
        assert c.geometry.equals_exact(fpoly, 0) and c.geometry.wkb == fpoly.wkb        # not repaired, not rebuilt
        if c.validity == "invalid_geometry":
            assert c.detail == detail and c.kind and "[" not in c.kind                   # GEOS reason, as the flood index stores it
        assert c.state()["validity"] == c.validity and c.state()["validator"].startswith("GEOS ")


def test_validity_reasons_and_feature_level_kinds() -> None:
    kinds = {name: [c.kind for c in val.classify_components(as_lists(polys))] for name, (polys, _) in VALIDITY_CASES.items()}
    assert kinds["self-touch"] == ["ring_self_intersection"]               # GEOS names a self-touch a ring self-intersection
    assert kinds["self-crossing (bow-tie)"] == ["self_intersection"]
    assert kinds["hole touching the shell at two points"] == ["interior_is_disconnected"]
    assert kinds["hole outside the shell"] == ["hole_lies_outside_shell"]
    assert kinds["collapsed ring"] == ["too_few_points_in_geometry_component"]
    overlap = val.classify_components(as_lists(VALIDITY_CASES["MultiPolygon, overlapping"][0]))
    assert [(c.kind, c.related) for c in overlap] == [("interiors_overlap", (1,)), ("interiors_overlap", (0,)), (None, ())]
    shared = val.classify_components(as_lists(VALIDITY_CASES["MultiPolygon, shared edge"][0]))
    assert [(c.kind, c.related) for c in shared] == [("shared_edge", (1,)), ("shared_edge", (0,))]
    assert shared[0].state()["related_components"] == [1]


BAD_COORDINATES = {
    "non-finite nan": [[[[0.5, 0.5], [float("nan"), 0.5], [0.6, 0.6], [0.5, 0.5]]]],
    "non-finite inf": [[[[0.5, 0.5], [float("inf"), 0.5], [0.6, 0.6], [0.5, 0.5]]]],
    "ring not closed": [[[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]]],
    "ring too short": [[[[0.0, 0.0], [1.0, 0.0], [0.0, 0.0]]]],
    "longitude 180": [[[[179.0, 0.0], [180.0, 0.0], [180.0, 1.0], [179.0, 0.0]]]],
    "latitude 91": [[[[0.0, 90.0], [1.0, 91.0], [1.0, 90.0], [0.0, 90.0]]]],
    "antimeridian edge": [[[[-179.5, 0.0], [179.5, 0.0], [179.5, 1.0], [-179.5, 0.0]]]],
    "3-D position": [[[[0.0, 0.0, 1.0], [1.0, 0.0, 1.0], [1.0, 1.0, 1.0], [0.0, 0.0, 1.0]]]],
    "string coordinate": [[[["0", 0.0], [1.0, 0.0], [1.0, 1.0], ["0", 0.0]]]],
    "bool coordinate": [[[[True, 0.0], [1.0, 0.0], [1.0, 1.0], [True, 0.0]]]],
    "polygon without rings": [[]],
}


@pytest.mark.parametrize("name", sorted(BAD_COORDINATES))
def test_coordinates_are_refused_as_the_flood_check_refuses_them(name) -> None:
    polys = BAD_COORDINATES[name]
    with pytest.raises(a31a.A31aFormatError):
        a31a.check_coordinates(polys)
    with pytest.raises(val.GeometryInputError):
        val.check_coordinates(polys)
    with pytest.raises(val.GeometryInputError):
        val.classify_components(polys)                 # refused, never classified (not even "invalid")


def test_good_coordinates_pass_both_checks() -> None:
    for polys, _ in VALIDITY_CASES.values():
        a31a.check_coordinates(as_lists(polys))
        val.check_coordinates(as_lists(polys))


def test_structure_of_the_geometry() -> None:
    sq = sqm(0, 0, 10, 10)
    assert val.polygons_of({"type": "Polygon", "coordinates": [sq]}) == [[sq]]
    assert val.polygons_of({"type": "MultiPolygon", "coordinates": [[sq], [sq]]}) == [[sq], [sq]]
    for bad in (None, [], {"type": "Point", "coordinates": [0, 0]}, {"type": "Polygon"},
                {"type": "MultiPolygon", "coordinates": []}, {"type": "Polygon", "coordinates": "x"}):
        with pytest.raises(val.GeometryInputError):
            val.polygons_of(bad)


def test_unverified_when_the_feature_level_check_cannot_finish(monkeypatch) -> None:
    """The flood build stops here (FloodIndexError); the shared module reports unverified, never valid."""
    polys = as_lists(VALIDITY_CASES["MultiPolygon, apart"][0])
    real = val.MultiPolygon

    class AlwaysInvalid:
        def __init__(self, parts):
            self.is_valid = False
    monkeypatch.setattr(val, "MultiPolygon", AlwaysInvalid)
    got = val.classify_components(polys)
    assert [c.validity for c in got] == ["unverified", "unverified"] and not any(c.usable for c in got)
    import hererisk.flood.index as flood_index
    monkeypatch.setattr(flood_index, "MultiPolygon", AlwaysInvalid)
    with pytest.raises(FloodIndexError):
        classify(polys)
    monkeypatch.setattr(val, "MultiPolygon", real)

    def boom(self):
        raise shapely.errors.GEOSException("validator failed")
    monkeypatch.setattr(Polygon, "is_valid", property(boom))
    assert [c.validity for c in val.classify_components(polys)] == ["unverified", "unverified"]


# --- relation: one component ----------------------------------------------------------------------------
def at(x, y):
    return ll(x, y)


SQUARE = Polygon(sqm(0, 0, 1000, 1000))
HOLED = Polygon(sqm(0, 0, 1000, 1000), [sqm(400, 400, 600, 600)])
BIG = Polygon(sqm(0, 0, 5000, 5000))
CORRIDOR = Polygon(sqm(0, 0, 5000, 30))
UPOLY = Polygon(U)
BOWTIE = Polygon(ring((0, 0), (1000, 1000), (1000, 0), (0, 1000), (0, 0)))


@pytest.mark.parametrize("geom, point, expected", [
    (SQUARE, (500, 500), "inside"),
    (SQUARE, (1500, 500), "outside"),
    (SQUARE, None, "on_boundary"),                       # on an edge: the exact vertex coordinates (below)
    (SQUARE, (0, 0), "on_boundary"),                     # a vertex
    (HOLED, (500, 500), "outside"),                      # in the hole
    (HOLED, (200, 200), "inside"),
    (BIG, (2500, 2500), "inside"),                       # 2.5 km from every edge: no search radius involved
    (BIG, (5000.5, 2500), "outside"),
    (CORRIDOR, (2500, 15), "inside"),
    (CORRIDOR, (2500, 45), "outside"),
    (UPOLY, (150, 200), "outside"),                      # in the notch of the U
    (UPOLY, (50, 200), "inside"),                        # in an arm
    (UPOLY, (150, 50), "inside"),                        # in the bottom
])
def test_relation_of_a_valid_polygon(geom, point, expected) -> None:
    if point is None:
        (ax, ay), (bx, _) = geom.exterior.coords[0], geom.exterior.coords[1]
        x, y = (ax + bx) / 2, ay
    else:
        x, y = at(*point)
    got = rel.relate(geom, "valid", x, y)
    assert got == {"evaluation": "evaluated", "relation": expected}
    assert got["relation"] == ("inside" if geom.contains(Point(x, y)) else "on_boundary" if geom.intersects(Point(x, y))
                               else "outside")


def test_relation_does_not_depend_on_the_polygon_size() -> None:
    for side in (1, 100, 5_000, 50_000):
        g = Polygon(sqm(0, 0, side, side))
        assert rel.relate(g, "valid", *at(side / 2, side / 2))["relation"] == "inside"
        assert rel.relate(g, "valid", *at(side * 1.5, side / 2))["relation"] == "outside"
        assert rel.relate(shapely.to_wkb(g), "valid", *at(side / 2, side / 2))["relation"] == "inside"    # WKB as stored


def test_an_invalid_polygon_is_pending_in_its_bounding_box_never_inside_or_outside() -> None:
    for validity in ("invalid_geometry", "feature_invalid_component", "unverified", None):
        for x, y in ((500, 250), (500, 750), (0, 0), (1000, 500), (0, 1000)):     # in the box, its edges and corners
            assert rel.relate(BOWTIE, validity, *at(x, y)) == {"evaluation": "pending_geometry", "relation": None}
        lon, lat = at(1000, 500)
        assert rel.relate(BOWTIE, validity, lon + 1e-9, lat) == {"evaluation": "outside_bounding_box", "relation": None}
        assert rel.relate(BOWTIE, validity, *at(1500, 500))["relation"] is None     # not "outside"


def test_codex_b1_is_pending_not_evaluated() -> None:
    """Phase 4-J.1 B1: H2 holds and GEOS make_valid(linework) reads the point inside. Not valid -> pending."""
    for scale in (1, 10):
        r = [ll(x * scale, y * scale) for x, y in [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0), (0, 100), (100, 100),
                                                     (100, 0), (0, 0), (-100, 0), (0, -100), (0, 0)]]
        comps = val.classify_components([[r]])
        assert [c.validity for c in comps] == ["invalid_geometry"] and comps[0].kind == "ring_self_intersection"
        x, y = at(50 * scale, 50 * scale)
        assert shapely.make_valid(Polygon(r), method="linework").contains(Point(x, y))   # one reading: inside
        assert not Polygon(r).contains(Point(x, y))                                       # GEOS contains: "outside"
        got = rel.relate(comps[0].geometry, comps[0].validity, x, y)
        assert got == {"evaluation": "pending_geometry", "relation": None}
        out = rel.ComponentIndex([rel.Candidate("s", "b1", comps[0].geometry, comps[0].validity, comps[0].detail)]).search(x, y)
        assert out["complete"] and [f["evaluation"] for f in out["features"]] == ["pending_geometry"]
        assert out["features"][0]["geometry_state"] == {"validity": "invalid_geometry", "detail": comps[0].detail}


def test_relation_refuses_bad_input() -> None:
    for x, y in ((float("nan"), 35.0), (139.0, float("inf")), ("139", 35.0), (None, 35.0), (True, 35.0)):
        with pytest.raises(rel.RelationInputError):
            rel.relate(SQUARE, "valid", x, y)
    with pytest.raises(rel.RelationInputError):
        rel.relate(SQUARE, "probably_valid", *at(1, 1))
    for g in (b"not wkb", Point(0, 0), shapely.MultiPolygon([SQUARE]), Polygon()):
        with pytest.raises(rel.RelationInputError):
            rel.relate(g, "valid", *at(1, 1))
        with pytest.raises(rel.RelationInputError):
            rel.ComponentIndex([rel.Candidate("s", "x", g, "valid")])
    with pytest.raises(rel.RelationInputError):
        rel.ComponentIndex([("s", "x", SQUARE, "valid")])


# --- relation: many components and sources ---------------------------------------------------------------
def test_search_lists_inside_boundary_and_pending_separately_and_omits_outside() -> None:
    idx = rel.ComponentIndex([
        rel.Candidate("src-a", "a-square", SQUARE, "valid"),
        rel.Candidate("src-a", "a-bowtie", BOWTIE, "invalid_geometry", "Self-intersection[..]"),
        rel.Candidate("src-a", "a-holed", HOLED, "valid"),
        rel.Candidate("src-b", "b-square", SQUARE, "valid"),            # the same shape in another source: kept apart
        rel.Candidate("src-b", "b-big", BIG, "valid"),
        rel.Candidate("src-b", "b-missing-validity", Polygon(sqm(100, 100, 200, 200))),     # no validity -> unverified
    ])
    out = idx.search(*at(150, 150))
    assert out["status"] == "complete" and out["complete"] is True
    assert [(f["source_id"], f["feature_ref"], f["evaluation"], f["relation"], f["geometry_state"]["validity"])
            for f in out["features"]] == [
        ("src-a", "a-bowtie", "pending_geometry", None, "invalid_geometry"),     # pending and inside at one point
        ("src-a", "a-holed", "evaluated", "inside", "valid"),
        ("src-a", "a-square", "evaluated", "inside", "valid"),
        ("src-b", "b-big", "evaluated", "inside", "valid"),                       # overlapping valid polygons: each listed
        ("src-b", "b-missing-validity", "pending_geometry", None, "unverified"),
        ("src-b", "b-square", "evaluated", "inside", "valid")]
    hole = idx.search(*at(500, 500))
    assert {f["feature_ref"]: f["relation"] for f in hole["features"]} == {
        "a-bowtie": None, "a-square": "inside", "b-big": "inside", "b-square": "inside"}     # a-holed (outside) not listed
    far = idx.search(*at(4000, 4000))
    assert [f["feature_ref"] for f in far["features"]] == ["b-big"]
    none = idx.search(*at(6000, 6000))
    assert none == {"status": "complete", "complete": True, "features": []}     # nothing listed; not "safe" (provider)
    edge = idx.search(*at(1000, 1000))
    assert {f["feature_ref"]: f["relation"] for f in edge["features"]} == {
        "a-bowtie": None, "a-square": "on_boundary", "a-holed": "on_boundary", "b-square": "on_boundary", "b-big": "inside"}
    assert len(idx) == 6
    for text in ("safe", "no_match", "candidate", "depth", "max"):
        assert text not in repr(out)


def test_search_never_returns_a_partial_list() -> None:
    many = [rel.Candidate("s", f"z{i:03d}", SQUARE, "valid") for i in range(10)]
    idx = rel.ComponentIndex(many)
    assert len(idx.search(*at(500, 500), max_features=10)["features"]) == 10
    over = idx.search(*at(500, 500), max_features=9)
    assert over == {"status": "limit_exceeded", "complete": False, "features": None,
                    "limit": {"type": "max_features", "value": 9}}
    assert rel.ComponentIndex(many).search(*at(5000, 5000), max_features=0)["status"] == "complete"   # 0 hits

    class Broken(rel.ComponentIndex):
        def _search(self, x, y):
            raise shapely.errors.GEOSException("TopologyException at 139.1 35.2")
    failed = Broken(many).search(*at(500, 500))
    assert failed == {"status": "failed", "complete": False, "features": None}           # no detail, no coordinates
    with pytest.raises(rel.RelationInputError):
        idx.search(float("nan"), 35.0)


# --- the flood code as the reference ----------------------------------------------------------------------
# Synthetic region 13 = lon 139.000-139.010, lat 35.000-35.010 (~910 m x 1,110 m), see test_flood_provider.
SHAPES = [
    feat(poly(sqm(-1500, -2000, 3500, 3000)), 1),                                     # ~5 km valid square over the region
    feat(poly(sqm(100, 100, 800, 130)), 2),                                            # thin corridor (30 m x 700 m)
    feat(poly(ring((100, 300), (400, 300), (400, 600), (300, 600), (300, 400), (200, 400), (200, 600), (100, 600), (100, 300))), 3),
    feat(poly(sqm(500, 300, 800, 600), sqm(600, 400, 700, 500)), 4),                   # hole
    feat(poly([ll(x + 450, y + 750) for x, y in [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0), (0, 100), (100, 100),
                                                    (100, 0), (0, 0), (-100, 0), (0, -100), (0, 0)]]), 5),   # B1
    feat(poly(ring((600, 700), (750, 700), (720, 760), (780, 760), (750, 700), (850, 700), (850, 950), (600, 950), (600, 700))), 6),
    feat({"type": "MultiPolygon", "coordinates": [[sqm(100, 800, 250, 950)], [sqm(250, 800, 400, 950)]]}, 1),   # shared edge
    feat({"type": "MultiPolygon", "coordinates": [[sqm(150, 650, 350, 780)], [ring((150, 650), (350, 780), (350, 650), (150, 780), (150, 650))]]}, 2),
]


@pytest.fixture
def shapes(data, tmp_path):
    from test_flood_provider import source as src
    write_a31a(data / "a31a" / "A31a-25_13_10_GEOJSON.zip", "13", {"1300000001": SHAPES})
    write_a31a(data / "a31a" / "A31a-25_83_10_GEOJSON.zip", "83",                     # source B: the same U and squares
               {"8303000001": [{**f, "properties": {**f["properties"], "A31a_201": "8303000001", "A31a_203": "83"}}
                               for f in SHAPES[:3]]})
    regions = write_regions(data, [src("src-a", "東京都（合成）", "13", "13", ["a31a/A31a-25_13_10_GEOJSON.zip"]),
                                   src("src-b", "関東地方整備局（合成）", "83", "83", ["a31a/A31a-25_83_10_GEOJSON.zip"])])
    build_index(regions, tmp_path / "shapes.sqlite")
    return regions, tmp_path / "shapes.sqlite"


def common_index_from(index_path):
    """The shared modules on the geometry of the flood index: validity recomputed from the coordinates
    (compared with the stored class), relation on that validity."""
    db = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
    rows = db.execute("SELECT source_id, product_ref, feature_index, polygon_index, zone_ref, usable, reason, "
                      "invalid_detail, wkb FROM components ORDER BY rowid").fetchall()
    db.close()
    features: dict[tuple, list] = {}
    for r in rows:
        features.setdefault((r[1], r[2]), []).append(r)
    cands, checked = [], 0
    for comps in features.values():
        geoms = [shapely.from_wkb(r[8]) for r in comps]
        polys = [[[list(p) for p in g.exterior.coords]] + [[list(p) for p in i.coords] for i in g.interiors] for g in geoms]
        classes = val.classify_components(polys)
        for r, c in zip(comps, classes):
            assert (c.usable, None if c.usable else c.validity) == (bool(r[5]), r[6])     # the stored flood class
            if c.validity == "invalid_geometry":
                assert c.detail == r[7]
            checked += 1
            cands.append(rel.Candidate(r[0], r[4], r[8], c.validity, c.detail))
    return rel.ComponentIndex(cands), checked


def compare_points(provider, idx, points):
    seen = {"inside": 0, "on_boundary": 0, "pending_geometry": 0}
    for lon, lat in points:
        section = provider.lookup(lat, lon)
        if section["status"] in ("not_available", "error"):
            continue
        listed = [s["source_id"] for s in section["sources"]]
        out = idx.search(lon, lat)
        assert out["complete"]
        got = {(sid, k): set() for sid in listed for k in ("zones", "boundary_contacts", "unknowns")}
        for f in out["features"]:
            if f["source_id"] not in listed:
                continue
            key = {"inside": "zones", "on_boundary": "boundary_contacts", None: "unknowns"}[f["relation"]]
            got[(f["source_id"], key)].add(f["feature_ref"])
            seen[f["relation"] or f["evaluation"]] += 1
        want = {(s["source_id"], k): {z["zone_ref"] for z in s[k]} for s in section["sources"]
                for k in ("zones", "boundary_contacts", "unknowns")}
        assert got == want, (lon, lat)
        order = [f["feature_ref"] for f in out["features"] if f["source_id"] in listed]
        assert order == sorted(order, key=lambda r: (listed.index(next(f["source_id"] for f in out["features"]
                                                                       if f["feature_ref"] == r)), r))
    return seen


def special_points(index_path):
    """Every vertex, every edge midpoint and every bounding-box corner / edge midpoint of the index."""
    db = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True)
    pts = []
    for minx, miny, maxx, maxy, wkb in db.execute("SELECT minx, miny, maxx, maxy, wkb FROM components"):
        g = shapely.from_wkb(wkb)
        for r in [g.exterior, *g.interiors]:
            c = list(r.coords)
            pts += c + [((ax + bx) / 2, (ay + by) / 2) for (ax, ay), (bx, by) in zip(c, c[1:])]
        pts += [(minx, miny), (maxx, maxy), (minx, maxy), (maxx, miny), ((minx + maxx) / 2, miny), (maxx, (miny + maxy) / 2)]
    db.close()
    return [(x, y) for x, y in pts if 139.0 <= x <= 139.0105 and 35.0 <= y <= 35.0105]


def grid(step=0.0002):
    n = int(round(0.0104 / step))
    return [(round(LON0 + i * step, 7), round(LAT0 + j * step, 7)) for i in range(n + 1) for j in range(n + 1)]


def test_equal_to_the_flood_provider_on_its_fixture(data, tmp_path) -> None:
    regions = two_sources(data)
    build_index(regions, tmp_path / "i.sqlite")
    provider = FloodProvider(regions, tmp_path / "i.sqlite")
    idx, checked = common_index_from(tmp_path / "i.sqlite")
    assert checked == 6                       # A: 5 kept (the far feature is not indexed), B: 1 in region 13
    seen = compare_points(provider, idx, grid() + special_points(tmp_path / "i.sqlite"))
    assert all(seen.values()), seen


def test_equal_to_the_flood_provider_on_large_thin_u_hole_b1_and_overlaps(shapes) -> None:
    regions, index_path = shapes
    provider = FloodProvider(regions, index_path)
    idx, checked = common_index_from(index_path)
    assert checked == 10 + 3
    seen = compare_points(provider, idx, grid() + special_points(index_path))
    assert all(seen.values()), seen
    centre = idx.search(*ll(450, 550))        # the ~5 km square, more than 2 km from each of its edges
    assert [(f["relation"], f["geometry_state"]["validity"]) for f in centre["features"] if f["source_id"] == "src-a"] == \
        [("inside", "valid")]
    b1 = idx.search(*ll(500, 800))            # inside B1's doubled square and the 5 km square
    assert sorted((f["source_id"], str(f["relation"]), f["geometry_state"]["validity"]) for f in b1["features"]) == \
        [("src-a", "None", "invalid_geometry"), ("src-a", "inside", "valid"), ("src-b", "inside", "valid")]


# --- dependencies and wiring ------------------------------------------------------------------------------
def test_shared_modules_depend_on_no_hazard_and_repair_nothing() -> None:
    code = ("import sys, hererisk.common.polygon.validity, hererisk.common.polygon.relation; "
            "print(sorted(m for m in sys.modules if m.startswith(('hererisk.flood', 'hererisk.location', 'hererisk.research'))))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": str(REPO / "src")})
    assert out.stdout.strip() == "[]"
    for name in ("validity.py", "relation.py"):
        text = (REPO / "src/hererisk/common/polygon" / name).read_text(encoding="utf-8")
        code_only = "\n".join(line.split("#")[0] for line in text.split('"""')[-1].splitlines())
        for banned in ("make_valid", "buffer(", "simplify", "union", "A31a", "depth", "river", "flood", "safe"):
            assert banned not in code_only, (name, banned)
        assert not any("぀" <= ch <= "鿿" for ch in text), name           # no user-facing Japanese text


# Phase 4-M: the tsunami provider is the first user; flood (and everything else) still does not use it
USERS = {("tsunami", "a40.py"), ("tsunami", "index.py"), ("location", "tsunami_provider.py")}


def test_used_only_by_the_tsunami_provider() -> None:
    for path in (REPO / "src/hererisk").rglob("*.py"):
        if "research" in path.parts or path.parts[-3:-1] == ("common", "polygon") or path.parts[-2:] in USERS:
            continue
        text = path.read_text(encoding="utf-8")
        assert "hererisk.common.polygon." not in text and "hererisk.common.polygon import" not in text, path
