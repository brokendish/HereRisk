"""Phase 4-N.2: the Location Resolver (N03 index with SQLite R-tree) on synthetic N03 files.

Synthetic prefectures 13 and 14 around lon 139.00-139.012, lat 35.00-35.008, plus 47 tiny prefectures for
the national case. The in-memory ``N03Municipalities.locate`` and the providers' ``_Region.relation`` are the
reference. Nothing here is real data (the Tokyo / Kanagawa comparison is ``hererisk.research.resolver_compare``).
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import math
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

shapely = pytest.importorskip("shapely")

from hererisk.location import resolver as rv                          # noqa: E402
from hererisk.location.admin_index import AdminIndexError, build_index, main as admin_cli   # noqa: E402
from hererisk.location.flood_provider import _Region as FloodRegion    # noqa: E402
from hererisk.location.n03_municipality import MunicipalityDataError, N03Municipalities, _read_file   # noqa: E402
from hererisk.location.tsunami_provider import _Region as TsunamiRegion   # noqa: E402

REPO = Path(__file__).resolve().parents[2]
LAT = 35.004
KX = 111320.0 * math.cos(math.radians(LAT))       # the resolver's tolerance is on this (longitude) scale


def sq(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


def feature(code, geometry, pref_name, name):
    return {"type": "Feature", "properties": {"N03_001": pref_name, "N03_002": None, "N03_003": None,
                                              "N03_004": name, "N03_005": None, "N03_007": code},
            "geometry": geometry}


def poly(*rings):
    return {"type": "Polygon", "coordinates": list(rings)}


def write_n03(path, pref, features):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"N03-20260101_{pref}.geojson", json.dumps({"type": "FeatureCollection", "features": features},
                                                               ensure_ascii=False))
    return path


F13 = [
    feature("13101", poly(sq(139.000, 35.000, 139.002, 35.004)), "テスト都", "甲区"),     # 13101 in two features:
    feature("13101", poly(sq(139.002, 35.000, 139.004, 35.004)), "テスト都", "甲区"),     #   the seam x=139.002 is internal
    feature("13102", poly(sq(139.004, 35.000, 139.008, 35.004)), "テスト都", "乙区"),
    feature("13103", {"type": "MultiPolygon", "coordinates": [
        [sq(139.000, 35.004, 139.004, 35.008), sq(139.0015, 35.0055, 139.0025, 35.0065)],   # with a hole
        [sq(139.020, 35.020, 139.021, 35.021)]]}, "テスト都", "丙村"),                       # and an island
    feature("13000", poly(sq(139.004, 35.004, 139.008, 35.008)), "テスト都", "所属未定地"),
]
F14 = [feature("14101", poly(sq(139.008, 35.000, 139.012, 35.008)), "テスト県", "丁市")]


def regions_file(d, prefs, name="regions.json"):
    p = d / name
    p.write_text(json.dumps({"regions": [{"prefecture_code": c, "address_isj": f"{c}.csv",
                                          "address_n03": f"N03-20260101_{c}_GML.zip"} for c in prefs]}), encoding="utf-8")
    return p


@pytest.fixture
def n03(tmp_path):
    write_n03(tmp_path / "N03-20260101_13_GML.zip", "13", F13)
    write_n03(tmp_path / "N03-20260101_14_GML.zip", "14", F14)
    return tmp_path


@pytest.fixture
def both(n03):
    regions = regions_file(n03, ["13", "14"])
    build_index(regions, n03 / "admin.sqlite")
    res = rv.LocationResolver(n03 / "admin.sqlite", regions_file=regions)
    yield res
    res.close()


def m(x_m):            # metres east on the tolerance's scale -> degrees of longitude
    return x_m / KX


# 1. index ------------------------------------------------------------------------------------------------
def test_index_keeps_every_feature_with_an_rtree_entry(n03) -> None:
    regions = regions_file(n03, ["13", "14"])
    out = build_index(regions, n03 / "admin.sqlite")
    assert out["features"] == 6 and out["prefectures"] == ["13", "14"] and out["coverage"] == "partial"
    db = sqlite3.connect(n03 / "admin.sqlite")
    rows = db.execute("SELECT municipality_code, unassigned, minx, maxx, wkb FROM areas ORDER BY id").fetchall()
    assert [r[0] for r in rows] == ["13101", "13101", "13102", "13103", "13000", "14101"]       # not merged
    assert [r[1] for r in rows] == [0, 0, 0, 0, 1, 0]
    assert db.execute("SELECT count(*) FROM area_rtree").fetchone()[0] == 6
    want = [g for p in ("13", "14") for _, g, _ in _read_file(n03 / f"N03-20260101_{p}_GML.zip", p)[1]]
    assert all(shapely.from_wkb(r[4]).equals_exact(g, 0) for r, g in zip(rows, want))           # the source's geometry
    meta = {k: json.loads(v) for k, v in db.execute("SELECT key, value FROM meta")}
    db.close()
    assert meta["status"] == "complete" and meta["index_format"] == "hererisk-admin-index-v0.1"
    assert len(meta["files"]["13"]["sha256"]) == 64 and meta["files"]["13"]["reference_date"] == "2026-01-01"


def test_a_failed_build_keeps_the_existing_index(n03) -> None:
    regions = regions_file(n03, ["13", "14"])
    build_index(regions, n03 / "admin.sqlite")
    before = (n03 / "admin.sqlite").read_bytes()
    (n03 / "N03-20260101_14_GML.zip").write_bytes(b"not a zip")
    with pytest.raises(MunicipalityDataError):                # the existing N03 reader's checks stop the build
        build_index(regions, n03 / "admin.sqlite")
    assert (n03 / "admin.sqlite").read_bytes() == before and not list(n03.glob("admin.sqlite.tmp-*"))
    assert admin_cli(["build", "--regions", str(regions), "--output", str(n03 / "admin.sqlite")]) == 3


def test_resolver_opens_only_a_complete_matching_index(n03) -> None:
    regions = regions_file(n03, ["13", "14"])
    build_index(regions, n03 / "admin.sqlite")
    rv.LocationResolver(n03 / "admin.sqlite", regions_file=regions).close()
    with pytest.raises(AdminIndexError):
        rv.LocationResolver(n03 / "admin.sqlite", regions_file=regions_file(n03, ["13"], "r13.json"))   # registration
    write_n03(n03 / "N03-20260101_14_GML.zip", "14", F14 + F14)
    with pytest.raises(AdminIndexError):
        rv.LocationResolver(n03 / "admin.sqlite", regions_file=regions)                                  # file changed
    db = sqlite3.connect(n03 / "admin.sqlite")
    db.execute("UPDATE meta SET value = '\"building\"' WHERE key = 'status'")
    db.commit()
    db.close()
    with pytest.raises(AdminIndexError, match="incomplete"):
        rv.LocationResolver(n03 / "admin.sqlite")
    (n03 / "junk.sqlite").write_bytes(b"junk" * 100)
    with pytest.raises(AdminIndexError):
        rv.LocationResolver(n03 / "junk.sqlite")


# 2. states -----------------------------------------------------------------------------------------------
def test_inside_seam_and_unassigned(both) -> None:
    loc = both.resolve(35.002, 139.006)
    assert loc.status == "inside" and [x["code"] for x in loc.municipalities] == ["13102"]
    assert loc.prefectures == ({"code": "13", "relation": "inside"},) and loc.complete
    assert loc.municipalities[0]["name"] == "乙区" and loc.source["files"][0]["reference_date"] == "2026-01-01"
    seam = both.resolve(35.002, 139.002)                 # between the two features of 13101: not a boundary
    assert seam.status == "inside" and [x["code"] for x in seam.municipalities] == ["13101"]
    un = both.resolve(35.006, 139.006)
    assert un.status == "inside" and un.municipalities[0]["unassigned"] is True and un.municipalities[0]["name"] is None


def test_municipality_boundary_is_not_a_prefecture_boundary(both) -> None:
    for d in (0.0, 5.0, -5.0):
        loc = both.resolve(35.002, 139.004 + m(d))
        assert loc.status == "near_boundary" and [x["code"] for x in loc.municipalities] == ["13101", "13102"]
        assert loc.prefectures == ({"code": "13", "relation": "inside"},)
    assert both.resolve(35.002, 139.004 + m(10.5)).status == "inside"


def test_prefecture_border_keeps_both_candidates(both) -> None:
    for d in (0.0, 5.0, -5.0, 9.9, -9.9):
        loc = both.resolve(35.002, 139.008 + m(d))
        assert loc.status == "near_boundary", d
        assert {p["code"] for p in loc.prefectures} == {"13", "14"}                         # never forced to one
        assert {p["relation"] for p in loc.prefectures} == {"boundary"}
        assert both.region_relation(loc, {"13", "14"}) == "inside"                          # the seam of the set
        assert both.region_relation(loc, {"13"}) == both.region_relation(loc, {"14"}) == "boundary"
        inside_13 = [x for x in loc.municipalities if x["prefecture_code"] == "13"][0]["contains_point"]
        assert inside_13 is (d < 0)                                                         # which side, kept apart
    far = both.resolve(35.002, 139.008 - m(10.5))
    assert far.status == "inside" and both.region_relation(far, {"14"}) is None


def test_hole_island_and_outside(both) -> None:
    hole = both.resolve(35.006, 139.002)
    assert hole.status == "outside_registered_area" and hole.prefectures == ()
    assert both.resolve(35.0205, 139.0205).municipalities[0]["code"] == "13103"
    sea = both.resolve(35.05, 139.05)
    assert sea.status == "outside_registered_area" and sea.coverage == "partial"           # never "sea"
    coast = both.resolve(35.008 + 5 / 111320.0, 139.010)                                     # 5 m off the outer edge
    assert coast.status == "near_boundary" and coast.prefectures == ({"code": "14", "relation": "boundary"},)


def test_unregistered_neighbour(n03) -> None:
    regions = regions_file(n03, ["13"], "r13.json")
    build_index(regions, n03 / "a13.sqlite")
    res = rv.LocationResolver(n03 / "a13.sqlite", regions_file=regions)
    inside_14 = res.resolve(35.002, 139.010)
    assert inside_14.status == "outside_registered_area"                                    # not "sea", not "outside"
    near = res.resolve(35.002, 139.008 + m(5))
    assert near.status == "near_boundary" and near.prefectures == ({"code": "13", "relation": "boundary"},)
    assert res.region_relation(near, {"13"}) == "boundary" and res.region_relation(near, {"14"}) is None
    res.close()


def test_national_registration(tmp_path) -> None:
    regs = []
    for k in range(1, 48):
        c = f"{k:02d}"
        write_n03(tmp_path / f"N03-20260101_{c}_GML.zip", c,
                  [feature(f"{c}201", poly(sq(130 + k * 0.1, 33.0, 130.05 + k * 0.1, 33.05)), f"県{c}", "市")])
        regs.append(c)
    regions = regions_file(tmp_path, regs)
    assert build_index(regions, tmp_path / "all.sqlite")["coverage"] == "national"
    res = rv.LocationResolver(tmp_path / "all.sqlite", regions_file=regions)
    assert res.resolve(33.02, 130.12).municipalities[0]["code"] == "01201"
    assert res.resolve(30.0, 130.0).status == "outside_admin_area"
    res.close()


def test_bad_input_failure_and_busy(both, n03, monkeypatch) -> None:
    for lat, lon in ((float("nan"), 139.0), (35.0, float("inf")), (91.0, 139.0), (35.0, 181.0), ("35", 139.0), (True, 139.0)):
        with pytest.raises(rv.ResolverInputError):
            both.resolve(lat, lon)
    real = both._read
    monkeypatch.setattr(both, "_read", lambda *a: (_ for _ in ()).throw(sqlite3.DatabaseError("disk image is malformed")))
    f = both.resolve(35.002, 139.006)
    assert f.status == "failed" and not f.complete and f.prefectures == () and f.municipalities == ()
    assert f.reason == "read_failed" and "malformed" not in json.dumps(f.view())
    with pytest.raises(ValueError):
        both.region_relation(f, {"13"})                                                      # never guessed
    monkeypatch.setattr(both, "_read", real)
    one = rv.LocationResolver(n03 / "admin.sqlite", connections=1, acquire_wait_s=0.01)
    held = one._pool.get()
    busy = one.resolve(35.002, 139.006)
    assert busy.status == "failed" and busy.reason == "busy"
    one._pool.put(held)
    assert one.resolve(35.002, 139.006).status == "inside"
    one.close()


# 3. equal to the in-memory decisions -----------------------------------------------------------------------
def grid_points():
    pts = [(139.0 + i * 0.00025, 35.0 + j * 0.00025) for i in range(-4, 54) for j in range(-4, 38)]
    for x in (139.002, 139.004, 139.008, 139.012):
        for d in (0.0, 5.0, -5.0, 9.9, -9.9, 10.1, -10.1):
            pts += [(x + m(d), 35.002), (x + m(d), 35.006)]
    pts += [(139.0205, 35.0205), (139.002, 35.006), (139.0015 + m(5), 35.006)]
    return pts


def test_equal_to_n03_municipalities_and_region(both, n03) -> None:
    files = [(p, n03 / f"N03-20260101_{p}_GML.zip") for p in ("13", "14")]
    ref = N03Municipalities(files)
    polys = {p: [g for _, g, _ in _read_file(f, p)[1]] for p, f in files}
    regions = {s: (FloodRegion([g for p in s for g in polys[p]]), TsunamiRegion([g for p in s for g in polys[p]]))
               for s in (("13",), ("14",), ("13", "14"))}
    seen = set()
    for x, y in grid_points():
        loc = both.resolve(y, x)
        state, value = ref.locate(y, x)
        if loc.status == "inside":
            got = ("inside", loc.municipalities[0]["code"])
        elif loc.status == "near_boundary":
            got = ("ambiguous", [x_["code"] for x_ in loc.municipalities])
        else:
            got = ("outside", None)
        assert got == (state, value), (x, y)
        seen.add(loc.status)
        pt = shapely.Point(x, y)
        for s, (fr, tr) in regions.items():
            assert both.region_relation(loc, set(s)) == fr.relation(pt, y) == tr.relation(pt, y), (s, x, y)
    assert seen == {"inside", "near_boundary", "outside_registered_area"}


def test_parallel_resolves_are_identical(both) -> None:
    pts = grid_points()
    first = [both.resolve(y, x).view() for x, y in pts]
    with cf.ThreadPoolExecutor(max_workers=32) as pool:
        again = list(pool.map(lambda p: both.resolve(p[1], p[0]).view(), pts))
    assert again == first


def test_only_the_candidates_are_read(both, monkeypatch) -> None:
    assert not any(isinstance(v, shapely.Geometry) for v in vars(both).values())          # nothing loaded at start
    read = []
    real = both._read
    monkeypatch.setattr(both, "_read", lambda *a: read.append(len(r := real(*a))) or r)
    both.resolve(35.002, 139.006)
    both.resolve(35.0205, 139.0205)
    assert read == [1, 1]                                                                    # one area each, not all six


def test_resolver_depends_on_no_hazard_and_is_not_wired_in() -> None:
    code = ("import sys, hererisk.location.resolver, hererisk.location.admin_index; "
            "print(sorted(m for m in sys.modules if m.startswith(('hererisk.flood', 'hererisk.tsunami', "
            "'hererisk.common.polygon', 'hererisk.research'))))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": str(REPO / "src")})
    assert out.stdout.strip() == "[]"
    for path in (REPO / "src/hererisk").rglob("*.py"):
        if "research" in path.parts or path.name in ("resolver.py", "admin_index.py", "source_resolver.py"):
            continue                                       # Phase 4-N.3: the Source Resolver is its only user
        text = path.read_text(encoding="utf-8")
        assert "location.resolver" not in text and "admin_index" not in text, path       # no provider / API yet
    text = (REPO / "src/hererisk/location/resolver.py").read_text(encoding="utf-8")
    for banned in ("make_valid", "buffer(", "simplify(", "clip_by_rect("):
        assert banned not in text.split('"""')[-1], banned


def test_concurrent_decisions_are_bounded_by_the_slots(n03, monkeypatch) -> None:
    import threading
    import time as _time
    regions = regions_file(n03, ["13", "14"])
    build_index(regions, n03 / "admin.sqlite")
    res = rv.LocationResolver(n03 / "admin.sqlite", connections=3, acquire_wait_s=5.0)
    active, peak, lock = [0], [0], threading.Lock()
    real = res._resolve

    def counted(*a):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        try:
            _time.sleep(0.002)
            return real(*a)
        finally:
            with lock:
                active[0] -= 1
    monkeypatch.setattr(res, "_resolve", counted)
    with cf.ThreadPoolExecutor(max_workers=32) as pool:
        out = list(pool.map(lambda p: res.resolve(p[1], p[0]).status, grid_points()[:400]))
    assert peak[0] <= 3 and "failed" not in out                     # 32 callers, never more than 3 decisions at once
    loc = res.resolve(35.002, 139.008)
    held = [res._pool.get() for _ in range(3)]
    res._acquire_wait_s = 0.01
    with pytest.raises(rv.ResolverBusy):
        res.region_relation(loc, {"13", "14"})                       # busy is an error, never a guessed relation
    for c in held:
        res._pool.put(c)
    assert res.region_relation(loc, {"13", "14"}) == "inside"
    res.close()
