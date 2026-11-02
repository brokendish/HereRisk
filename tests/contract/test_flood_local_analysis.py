"""Phase 4-C: local analysis of invalid polygons (PoC, diagnosis only) and the flood settings block.

Synthetic shapes in meters around (35.0, 139.0); nothing here is real data.
"""

from __future__ import annotations

import json
import math

import pytest

pytest.importorskip("shapely")

import shapely                                                      # noqa: E402

from hererisk.flood import settings                                 # noqa: E402
from hererisk.flood.index import build_index, main as flood_cli       # noqa: E402
from hererisk.flood.local_analysis import Prepared, plus_far, run, staged   # noqa: E402
from hererisk.location.flood_provider import FloodProvider            # noqa: E402
from test_flood_provider import data, two_sources                    # noqa: E402,F401  (fixture + helper)

LAT0, LON0 = 35.0, 139.0
KX, KY = 111320.0 * math.cos(math.radians(LAT0)), 111320.0
RADII = [5, 10, 25, 50, 100]


def ll(x, y):          # meters -> (lon, lat)
    return LON0 + x / KX, LAT0 + y / KY


def poly(*rings):
    return shapely.Polygon([ll(*p) for p in rings[0]], [[ll(*p) for p in r] for r in rings[1:]])


def at(prep, x, y):
    lon, lat = ll(x, y)
    evals = [prep.evaluate(lat, lon, r) for r in RADII]
    final = staged(evals, RADII)
    return [e["outcome"] for e in evals], final, plus_far(final, prep, lat, lon)


# an exterior ring pinched at V=(500, 0) around a triangle: an inverted hole (GEOS: Ring Self-intersection)
INVERTED = poly([(0, 0), (500, 0), (400, 300), (600, 300), (500, 0), (1000, 0), (1000, 1000), (0, 1000), (0, 0)])


def test_inverted_hole_is_read_from_the_original_vertices() -> None:
    assert not INVERTED.is_valid
    prep = Prepared(INVERTED)
    assert len(prep.defects) == 1 and not prep.defects_unlocated
    outs, final, _ = at(prep, 500, 200)                       # inside the pinched triangle: outside the zone
    assert outs[:4] == ["no_boundary_within_radius"] * 4 and final["outcome"] == "outside" and final["radius_m"] == 100
    assert final["winding"] == 0
    outs, final, _ = at(prep, 500, 992)                       # 8 m from the top edge
    assert final["outcome"] == "inside" and final["radius_m"] == 10
    outs, final, far = at(prep, 800, 500)                     # 200 m from every edge
    assert final["outcome"] == "no_boundary_within_max_radius"   # a clean neighbourhood alone proves nothing
    assert far["outcome"] == "inside" and far["by"] == "far_winding"   # comparison policy only
    outs, final, _ = at(prep, 510, 20)                        # 3 m from the triangle, 22 m from V
    assert outs[0] == "inside" and outs[2:] == ["defect_within_radius"] * 3


def test_valid_polygon_with_hole_matches_geos() -> None:
    g = poly([(0, 0), (300, 0), (300, 300), (0, 300), (0, 0)], [(100, 100), (100, 200), (200, 200), (200, 100), (100, 100)])
    prep = Prepared(g)
    assert g.is_valid and len(prep.defects) == 0
    for x, y in [(150, 150), (50, 150), (150, 97), (150, 103), (3, 3), (296, 150), (310, 150)]:
        _, final, _ = at(prep, x, y)
        lon, lat = ll(x, y)
        if final["outcome"] in ("inside", "outside"):
            assert (final["outcome"] == "inside") == g.contains(shapely.Point(lon, lat)), (x, y)
    assert at(prep, 300, 150)[1]["outcome"] == "on_boundary"
    reversed_rings = shapely.Polygon(g.exterior.coords[::-1], [g.interiors[0].coords[::-1]])
    assert at(Prepared(reversed_rings), 150, 103)[1]["outcome"] == "outside"   # orientation read per ring


def test_crossing_ring_lobe_is_inconsistent() -> None:
    # an asymmetric figure-eight: the small lobe runs the other way (winding -1)
    g = poly([(0, 0), (600, 600), (600, 400), (0, 1000), (0, 0)])
    prep = Prepared(g)
    assert not g.is_valid and len(prep.defects) == 1
    _, big, _ = at(prep, 50, 500)                             # the large lobe
    _, small, _ = at(prep, 590, 500)                          # the small, reversed lobe
    assert big["outcome"] == "inside"
    assert small["outcome"] == "inconsistent_winding" and small["winding"] == -1
    sym = poly([(0, 0), (500, 500), (500, 0), (0, 500), (0, 0)])                # zero signed area
    assert at(Prepared(sym), 480, 250)[1]["outcome"] == "orientation_unknown"


def test_settings_block() -> None:
    assert settings.load_settings(None)["local_analysis"] == settings.DEFAULT_LOCAL_ANALYSIS
    assert settings.radii(settings.DEFAULT_LOCAL_ANALYSIS) == [5, 10, 25, 50, 100]
    good = dict(settings.DEFAULT_LOCAL_ANALYSIS)
    for bad in ({**good, "enabled": True}, {**good, "enabled": 0}, {**good, "extra": 1},
                {k: v for k, v in good.items() if k != "max_radius_m"},
                {**good, "expansion_radii_m": [10, 10, 100]}, {**good, "expansion_radii_m": [3, 100]},
                {**good, "max_radius_m": 50}, {**good, "initial_radius_m": 0}, {**good, "initial_radius_m": True},
                {**good, "expansion_radii_m": [10, 2000], "max_radius_m": 2000}, {**good, "expansion_radii_m": "10"}):
        with pytest.raises(settings.FloodSettingsError):
            settings.check_local_analysis(bad)
    assert settings.check_local_analysis({**good, "initial_radius_m": 2.5, "expansion_radii_m": [], "max_radius_m": 2.5})
    d = settings.describe()["local_analysis"]
    assert set(d["fields"]) == set(good) and d["defaults"] == good


def test_poc_on_fixtures_is_reproducible_and_leaves_the_provider_alone(data, tmp_path, capsys) -> None:   # noqa: F811
    regions = two_sources(data)
    build_index(regions, tmp_path / "index.sqlite")
    index_bytes = (tmp_path / "index.sqlite").read_bytes()
    before = FloodProvider(regions, tmp_path / "index.sqlite").lookup(35.0075, 139.0072)
    kw = dict(index=tmp_path / "index.sqlite", per_category=5, per_rank=2, defect_points=5,
              extra_points=[(35.0075, 139.0072)])
    a, b = run(regions, **kw), run(regions, **kw)
    assert [(p["lat"], p["lon"]) for p in a["points"]] == [(p["lat"], p["lon"]) for p in b["points"]]
    s = a["summary"]
    assert s["pairs_invalid"] > 0 and s["control_valid_mismatches"] == 0
    assert s["radius_dependence"]["decided_reading_changes_with_radius"] == 0
    assert s["provider_unknowns_match"] == s["provider_checked_points"] > 0
    given = a["points"][0]
    assert given["category"] == "given" and given["pending"] == 1
    assert {"even_odd", "make_valid", "exterior_only"} <= set(given["pairs"][0]["reads"])
    assert (tmp_path / "index.sqlite").read_bytes() == index_bytes
    assert FloodProvider(regions, tmp_path / "index.sqlite").lookup(35.0075, 139.0072) == before
    # CLI: report, settings file, exit codes
    cfg = tmp_path / "flood-settings.json"
    cfg.write_text(json.dumps({"local_analysis": {**settings.DEFAULT_LOCAL_ANALYSIS, "expansion_radii_m": [20],
                                                  "max_radius_m": 20}}))
    args = ["local-analysis", "--regions", str(regions), "--index", str(tmp_path / "index.sqlite"),
            "--settings", str(cfg), "--per-category", "3", "--per-rank", "1", "--defect-points", "3",
            "--point", "35.0075,139.0072", "--report-dir", str(tmp_path / "reports")]
    assert flood_cli(args) == 0
    assert "DIAGNOSIS ONLY" in capsys.readouterr().out
    report = next((tmp_path / "reports").iterdir())
    summary = json.loads((report / "summary.json").read_text())
    assert summary["inputs"]["local_analysis"]["max_radius_m"] == 20
    cases = json.loads((report / "cases.json").read_text())
    assert cases[0]["group"] == "given" and (report / cases[0]["svg"]).read_text().startswith("<svg")
    cfg.write_text(json.dumps({"local_analysis": {**settings.DEFAULT_LOCAL_ANALYSIS, "enabled": True}}))
    assert flood_cli(args[:-2]) == 2
    assert flood_cli(["local-analysis", "--regions", str(regions), "--point", "x"]) == 2
    assert flood_cli(["local-analysis", "--regions", str(regions), "--source", "nope"]) == 3
