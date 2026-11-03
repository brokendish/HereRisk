"""Phase 4-N.3: the Source Resolver (which registered sources to search) on synthetic data.

The Location Resolver (Phase 4-N.2) is real; registrations are synthetic. The current FloodProvider /
TsunamiProvider on their synthetic fixtures are the reference for the source choice. The state table of
the contract (3.4) is checked here with a reference mapping, apart from the Source Resolver itself (it
does not decide a Location API status).
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("shapely")

from hererisk.flood.index import build_index as build_flood_index        # noqa: E402
from hererisk.flood.registry import load_flood_sources                    # noqa: E402
from hererisk.location.admin_index import build_index as build_admin     # noqa: E402
from hererisk.location.flood_provider import FloodProvider               # noqa: E402
from hererisk.location.resolver import LocationResolver                  # noqa: E402
from hererisk.location.source_resolver import (SourceEntry, SourceRegistry, SourceRegistryError,   # noqa: E402
                                               SourceResolver, entries_from_registrations)
from hererisk.location.tsunami_provider import TsunamiProvider           # noqa: E402
from hererisk.tsunami.index import build_index as build_tsunami_index    # noqa: E402
from hererisk.tsunami.registry import load_tsunami_sources               # noqa: E402
from test_flood_provider import data, two_sources                        # noqa: E402,F401
from test_location_resolver import F13, F14, feature, m, poly, regions_file, sq, write_n03   # noqa: E402
from test_tsunami_provider import regions_file as t_regions_file, t_source, write_a40   # noqa: E402

REPO = Path(__file__).resolve().parents[2]
F38 = [feature("38201", poly(sq(132.70, 33.80, 132.80, 33.90)), "テスト愛媛", "松山市（合成）")]


@pytest.fixture
def world(tmp_path):
    write_n03(tmp_path / "N03-20260101_13_GML.zip", "13", F13)
    write_n03(tmp_path / "N03-20260101_14_GML.zip", "14", F14)
    write_n03(tmp_path / "N03-20260101_38_GML.zip", "38", F38)
    regions = regions_file(tmp_path, ["13", "14", "38"])
    build_admin(regions, tmp_path / "admin.sqlite")
    res = LocationResolver(tmp_path / "admin.sqlite", regions_file=regions)
    yield res
    res.close()


def registry(*entries):
    return SourceRegistry([SourceEntry(h, s, tuple(p)) for h, s, p in entries])


def ids(sel):
    return [(s["source_id"], s["service_region_relation"]) for s in sel.sources]


# 1. selection rules ---------------------------------------------------------------------------------------
def test_one_prefecture_inside_and_border(world) -> None:
    sr = SourceResolver(registry(("flood", "f-13", ["13"])), world)
    inside = sr.select("flood", world.resolve(35.002, 139.006))
    assert inside.complete and ids(inside) == [("f-13", "inside")] and inside.missing == ()
    assert inside.coverage == "full" and inside.region_state == "inside" and inside.hazard_registered
    border = sr.select("flood", world.resolve(35.002, 139.008 + m(5)))        # 5 m into 14
    assert ids(border) == [("f-13", "boundary")]
    assert border.missing == ({"prefecture_code": "14", "reason": "no_source_registered"},)
    assert border.coverage == "partial" and border.region_state == "region_boundary"


def test_multi_prefecture_source_is_one_entry_and_its_inner_border_is_not_an_edge(world) -> None:
    sr = SourceResolver(registry(("flood", "f-kanto", ["13", "14"])), world)
    for d in (0.0, 5.0, -5.0):
        sel = sr.select("flood", world.resolve(35.002, 139.008 + m(d)))
        assert ids(sel) == [("f-kanto", "inside")] and sel.missing == () and sel.region_state == "inside"
    coast = sr.select("flood", world.resolve(35.008 + 5 / 111320.0, 139.010))  # the outer edge of the pair
    assert ids(coast) == [("f-kanto", "boundary")]


def test_both_sides_of_a_border_and_registration_order(world) -> None:
    sr = SourceResolver(registry(("flood", "f-14", ["14"]), ("flood", "f-13", ["13"]), ("flood", "f-13b", ["13"]),
                                 ("tsunami", "t-14", ["14"])), world)
    sel = sr.select("flood", world.resolve(35.002, 139.008 - m(5)))
    assert [s for s, _ in ids(sel)] == ["f-14", "f-13", "f-13b"]               # registration order, separate sources
    assert {r for _, r in ids(sel)} == {"boundary"} and sel.missing == ()
    t = sr.select("tsunami", world.resolve(35.002, 139.008 - m(5)))
    assert ids(t) == [("t-14", "boundary")] and t.missing == ({"prefecture_code": "13", "reason": "no_source_registered"},)
    only_14 = sr.select("flood", world.resolve(35.002, 139.011))
    assert ids(only_14) == [("f-14", "inside")]


def test_no_source_unregistered_hazard_and_outside(world) -> None:
    sr = SourceResolver(registry(("flood", "f-13", ["13"])), world)
    in_14 = sr.select("flood", world.resolve(35.002, 139.011))                 # 14 has no flood source
    assert in_14.complete and in_14.sources == () and in_14.region_state is None
    assert in_14.missing == ({"prefecture_code": "14", "reason": "no_source_registered"},) and in_14.hazard_registered
    nothing = sr.select("landslide", world.resolve(35.002, 139.006))           # a hazard with no registration at all
    assert nothing.sources == () and nothing.hazard_registered is False and nothing.missing[0]["prefecture_code"] == "13"
    sea = sr.select("flood", world.resolve(35.05, 139.05))
    assert sea.complete and sea.sources == () and sea.missing == () and sea.location_status == "outside_registered_area"
    assert sea.location_coverage == "partial"                                  # outside cannot be told from unregistered


def test_any_prefecture_by_registration_only(world) -> None:
    sr = SourceResolver(registry(("tsunami", "local-a40-2023-38", ["38"])), world)
    sel = sr.select("tsunami", world.resolve(33.85, 132.75))
    assert ids(sel) == [("local-a40-2023-38", "inside")]
    text = (REPO / "src/hererisk/location/source_resolver.py").read_text(encoding="utf-8").split('"""', 2)[-1]
    for code in ('"13"', '"14"', '"38"', "'13'", "'14'"):
        assert code not in text                                                # no prefecture in the code


def test_failed_and_busy_location_give_no_selection(world, monkeypatch) -> None:
    sr = SourceResolver(registry(("flood", "f-13", ["13"])), world)
    import sqlite3
    monkeypatch.setattr(world, "_read", lambda *a: (_ for _ in ()).throw(sqlite3.DatabaseError("disk")))
    failed = sr.select("flood", world.resolve(35.002, 139.006))
    assert not failed.complete and failed.sources is None and failed.reason == "location_read_failed"
    monkeypatch.undo()
    loc = world.resolve(35.002, 139.008)
    held = [world._pool.get() for _ in range(len(world._all))]
    world._acquire_wait_s = 0.01
    busy = sr.select("flood", loc)
    assert not busy.complete and busy.sources is None and busy.reason == "location_busy"
    for c in held:
        world._pool.put(c)


def test_registration_errors(world) -> None:
    for bad in ([SourceEntry("flood", "f-13", ("13",)), SourceEntry("flood", "f-13", ("13",))],    # twice
                [SourceEntry("flood", "f-13", ("13", "13"))], [SourceEntry("flood", "f-13", ())],
                [SourceEntry("flood", "f-13", ("48",))], [SourceEntry("flood", "f-13", ["13"])],
                [SourceEntry("Flood", "f-13", ("13",))], [SourceEntry("flood", "F 13", ("13",))], ["not an entry"]):
        with pytest.raises(SourceRegistryError):
            SourceRegistry(bad)
    with pytest.raises(SourceRegistryError):
        SourceResolver(registry(("flood", "f-27", ["27"])), world)            # no N03 for 27 in the resolver
    with pytest.raises(SourceRegistryError):
        entries_from_registrations("flood", [{"source_id": "f-13"}])
    assert SourceRegistry([SourceEntry("flood", "f-13", ("13",)), SourceEntry("tsunami", "f-13", ("13",))]).hazards() == \
        ("flood", "tsunami")                                                   # the same id in two hazards is two sources


def test_parallel_selections_do_not_mix(world) -> None:
    sr = SourceResolver(registry(("flood", "f-13", ["13"]), ("flood", "f-14", ["14"]), ("flood", "f-all", ["13", "14"])), world)
    pts = [(35.0 + j * 0.0004, 139.0 + i * 0.0004) for i in range(-2, 33) for j in range(-2, 22)]
    first = [sr.select("flood", world.resolve(*p)).view() for p in pts]
    with cf.ThreadPoolExecutor(max_workers=16) as pool:
        again = list(pool.map(lambda p: sr.select("flood", world.resolve(*p)).view(), pts))
    assert again == first


# 2. the Location API state table (contract 3.4), checked apart from the resolver ----------------------------
def status_for(sel, searched):
    """Reference mapping S-1..S-5. ``searched``: per selected source (zones, pending, contacts, ok)."""
    if not sel.complete or any(not r["ok"] for r in searched):
        return "error"
    if not sel.sources:
        return "not_available"
    if any(r["zones"] for r in searched):
        return "available"
    if sel.missing or sel.region_state == "region_boundary" or any(r["pending"] or r["contacts"] for r in searched):
        return "unknown"
    return "no_match"


def test_missing_never_becomes_no_match(world) -> None:
    sr = SourceResolver(registry(("tsunami", "t-13", ["13"])), world)
    empty = {"zones": False, "pending": False, "contacts": False, "ok": True}
    for d in (5.0, -5.0, 9.9, -9.9):
        sel = sr.select("tsunami", world.resolve(35.002, 139.008 + m(d)))
        assert sel.missing and status_for(sel, [empty] * len(sel.sources)) == "unknown"            # INV-2, SR-d
        assert status_for(sel, [{**empty, "zones": True}] * len(sel.sources)) == "available"
        assert status_for(sel, [{**empty, "ok": False}] * len(sel.sources)) == "error"             # INV-3
    inside = sr.select("tsunami", world.resolve(35.002, 139.006))
    assert status_for(inside, [empty]) == "no_match"                                               # INV-1 holds
    two = SourceResolver(registry(("tsunami", "t-13", ["13"]), ("tsunami", "t-14", ["14"])), world)
    border = two.select("tsunami", world.resolve(35.002, 139.008))
    assert status_for(border, [empty, {**empty, "ok": False}]) == "error"                           # SR-e


# 3. equal to the current providers on their fixtures ------------------------------------------------------------
def grid():
    return [(35.0 + j * 0.0005, 139.0 + i * 0.0005) for i in range(-2, 64) for j in range(-2, 24)] + \
        [(35.005, 139.010 + d / 91188.0) for d in (0.0, 5.0, -5.0, 9.9, -9.9, 10.5, -10.5)]


def compare(provider, sr, hazard, res):
    for lat, lon in grid():
        section = provider.lookup(lat, lon)
        want = [] if section["status"] == "not_available" else \
            [(s["source_id"], s["service_region_relation"]) for s in section["sources"]]
        sel = sr.select(hazard, res.resolve(lat, lon))
        assert sel.complete and ids(sel) == want, (lat, lon)
        assert sel.region_state == (section.get("region_state") if want else None), (lat, lon)


@pytest.mark.parametrize("b_prefs", [("13",), ("13", "14")])
def test_equal_to_the_flood_provider(data, tmp_path, b_prefs) -> None:
    regions = two_sources(data, b_prefs=b_prefs)
    build_flood_index(regions, tmp_path / "f.sqlite")
    build_admin(regions, tmp_path / "admin.sqlite")
    res = LocationResolver(tmp_path / "admin.sqlite", regions_file=regions)
    sr = SourceResolver(SourceRegistry(entries_from_registrations("flood", load_flood_sources(regions))), res)
    compare(FloodProvider(regions, tmp_path / "f.sqlite"), sr, "flood", res)
    res.close()


def test_equal_to_the_tsunami_provider(data, tmp_path) -> None:
    (data / "a40").mkdir()
    write_a40(data / "a40" / "A40-23_13_GML.zip")
    regions = t_regions_file(data, [t_source()])
    build_tsunami_index(regions, tmp_path / "t.sqlite")
    build_admin(regions, tmp_path / "admin.sqlite")
    res = LocationResolver(tmp_path / "admin.sqlite", regions_file=regions)
    sr = SourceResolver(SourceRegistry(entries_from_registrations("tsunami", load_tsunami_sources(regions))), res)
    compare(TsunamiProvider(regions, tmp_path / "t.sqlite"), sr, "tsunami", res)
    res.close()


# 4. dependencies --------------------------------------------------------------------------------------------------
def test_source_resolver_depends_on_no_hazard_and_holds_no_geometry(world) -> None:
    code = ("import sys, hererisk.location.source_resolver; print(sorted(m for m in sys.modules if m.startswith("
            "('hererisk.flood', 'hererisk.tsunami', 'hererisk.common.polygon', 'hererisk.research'))))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": str(REPO / "src")})
    assert out.stdout.strip() == "[]"
    text = (REPO / "src/hererisk/location/source_resolver.py").read_text(encoding="utf-8")
    assert "import shapely" not in text and "sqlite3" not in text and "STRtree" not in text
    sr = SourceResolver(registry(("flood", "f-13", ["13"])), world)
    assert json.dumps(sr.select("flood", world.resolve(35.002, 139.006)).view())        # plain data only
    for path in (REPO / "src/hererisk").rglob("*.py"):
        if "research" in path.parts or path.name == "source_resolver.py":
            continue
        assert "source_resolver" not in path.read_text(encoding="utf-8"), path            # not wired in yet
