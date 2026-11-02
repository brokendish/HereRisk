"""Phase 4-D: offline preparation of invalid flood polygons and the light local search (diagnosis only).

Synthetic A31a ZIPs in the official layout (helpers of test_flood_provider); nothing here is real data.
The light search must give exactly the Phase 4-C in-memory results, read no ZIP, and refuse an
incomplete or foreign preparation.
"""

from __future__ import annotations

import json
import math
import sqlite3
import subprocess
import sys

import pytest

pytest.importorskip("shapely")

import shapely                                                      # noqa: E402

from hererisk.flood import diag, local_analysis                     # noqa: E402
from hererisk.flood.index import build_index, main as flood_cli       # noqa: E402
from hererisk.location.flood_provider import FloodProvider            # noqa: E402
from test_flood_provider import feat, poly, source, write_a31a, write_isj, write_n03, write_regions, sq   # noqa: E402

LAT0, LON0 = 35.0, 139.0
KX, KY = 111320.0 * math.cos(math.radians(LAT0)), 111320.0
RADII = [5, 10, 25, 50, 100]


def ll(x, y):          # meters -> [lon, lat]
    return [LON0 + x / KX, LAT0 + y / KY]


def ring(*pts):
    return [ll(*p) for p in pts]


# pinched at (400, 0) around a triangle (inverted hole); a figure-eight with a reversed small lobe;
# a valid square with a hole whose corner touches the shell (legal contact)
INVERTED = ring((0, 0), (400, 0), (320, 240), (480, 240), (400, 0), (800, 0), (800, 800), (0, 800), (0, 0))
EIGHT = ring((0, 900), (500, 1400), (500, 1250), (0, 1800), (0, 900))
FEATURES = [feat(poly(INVERTED), 3), feat(poly(EIGHT), 2),
            feat(poly(ring((850, 100), (1050, 100), (1050, 300), (850, 300), (850, 100)),
                      ring((850, 100), (900, 150), (950, 150), (900, 120), (850, 100))), 1)]


@pytest.fixture
def prepared(tmp_path):
    d = tmp_path / "data"
    (d / "a31a").mkdir(parents=True)
    write_n03(d / "N03-20260101_13_GML.zip", "13", sq(138.99, 34.99, 139.03, 35.03), "テスト都")
    write_isj(d / "13_2025.csv", "13", "テスト都", 139.005)
    write_a31a(d / "a31a" / "A31a-25_13_10_GEOJSON.zip", "13", {"1300000001": FEATURES})
    regions = write_regions(d, [source("src-a", "東京都（合成）", "13", "13", ["a31a/A31a-25_13_10_GEOJSON.zip"])],
                            prefs=("13",))
    build_index(regions, tmp_path / "index.sqlite")
    out = diag.build(regions, tmp_path / "index.sqlite", tmp_path / "diag.sqlite")
    return regions, tmp_path / "index.sqlite", tmp_path / "diag.sqlite", out


def test_build_is_complete_and_checked(prepared) -> None:
    regions, index, path, out = prepared
    assert out["counts"]["comps"] == out["counts"]["pending_rows_in_flood_index"] == 2   # the two invalid shapes
    assert out["checks"]["ring_mismatches"] == 0 and out["checks"]["rings_checked"] == 2
    assert out["counts"]["defect_kinds"] == {"touch": 1, "crossing": 1}
    d = diag.DiagIndex(path, flood_index=index)
    assert d.meta["status"] == "complete" and d.meta["diagnosis_only"] is True
    assert d.meta["zip_sha256"] == json.loads(sqlite3.connect(index).execute(
        "SELECT value FROM meta WHERE key = 'zip_sha256'").fetchone()[0])
    assert not list(path.parent.glob("diag.sqlite.tmp-*"))


def test_light_search_equals_phase_4c(prepared) -> None:
    regions, index, path, _ = prepared
    d = diag.DiagIndex(path)
    geoms = {r[0]: shapely.from_wkb(r[1]) for r in
             sqlite3.connect(index).execute("SELECT zone_ref, wkb FROM components WHERE usable = 0")}
    seen = set()
    for x in range(-30, 1100, 37):
        for y in range(-30, 1850, 41):
            lon, lat = ll(x, y)
            for c in d.candidates(lat, lon):
                prep = local_analysis.Prepared(geoms[c["zone_ref"]])
                want = [prep.evaluate(lat, lon, r) for r in RADII]
                final = local_analysis.staged(want, RADII)
                far = local_analysis.plus_far(final, prep, lat, lon)
                got = d.analyze(c, lat, lon, RADII, all_radii=True)
                assert [e["outcome"] for e in got["per_radius"]] == [e["outcome"] for e in want], (x, y)
                assert got["local"]["outcome"] == final["outcome"] and got["local"]["radius_m"] == final["radius_m"]
                assert got["local"].get("edge_m") == final.get("edge_m")
                assert got["local_plus_far"]["outcome"] == far["outcome"]
                assert got["local_plus_far"].get("winding") == far.get("winding")
                dd, _ = d.defect_distance_m(c, lat, lon)
                assert round(dd, 2) == final["defect_m"]
                seen.add(got["local"]["outcome"])
    assert {"inside", "outside", "defect_within_radius", "no_boundary_within_max_radius",
            "inconsistent_winding"} <= seen


def test_case_classes(prepared) -> None:
    _, _, path, _ = prepared
    d = diag.DiagIndex(path)
    inv = next(c for c in d.candidates(*reversed(ll(100, 400))) if c["depth_class"]["class_code"] == "3")
    # A: a point on the ring: the local method stops (GEOS contains and the even-odd ray split there)
    lon, lat = INVERTED[6]
    assert d.analyze(inv, lat, lon, RADII)["local"]["outcome"] == "on_boundary"
    # B: decided at 5 m next to the triangle; the pinch vertex (22 m away) enters at 25 m
    lon, lat = ll(410, 20)
    outs = [e["outcome"] for e in d.analyze(inv, lat, lon, RADII, all_radii=True)["per_radius"]]
    assert outs[0] == "inside" and outs[2:] == ["defect_within_radius"] * 3
    assert d.analyze(inv, lat, lon, RADII)["per_radius"][-1]["radius_m"] == 5      # staged: stops at 5 m
    # inside the pinched triangle: outside the zone, from the far winding number
    lon, lat = ll(400, 160)
    assert d.analyze(inv, lat, lon, RADII)["local"]["outcome"] == "outside"


def test_refuses_foreign_or_incomplete_and_keeps_the_old_file(prepared, tmp_path) -> None:
    regions, index, path, _ = prepared
    before = path.read_bytes()
    db = sqlite3.connect(path)
    db.execute("UPDATE meta SET value = '\"building\"' WHERE key = 'status'")
    db.commit()
    db.close()
    with pytest.raises(diag.DiagIndexError, match="incomplete"):
        diag.DiagIndex(path)
    path.write_bytes(before)
    other = tmp_path / "other.sqlite"
    other.write_bytes(index.read_bytes())         # another build of the flood index
    db = sqlite3.connect(other)
    db.execute("UPDATE meta SET value = '\"2000-01-01T00:00:00Z\"' WHERE key = 'built_at'")
    db.commit()
    db.close()
    with pytest.raises(diag.DiagIndexError, match="another flood index"):
        diag.DiagIndex(path, flood_index=other)
    zip_path = regions.parent / "a31a" / "A31a-25_13_10_GEOJSON.zip"
    write_a31a(zip_path, "13", {"1300000001": FEATURES[:1]})      # the ZIP changed after the index
    with pytest.raises(diag.DiagIndexError, match="SHA-256"):
        diag.build(regions, index, path)
    assert path.read_bytes() == before and not list(path.parent.glob("diag.sqlite.tmp-*"))
    with pytest.raises(diag.DiagIndexError, match="not found"):
        diag.DiagIndex(tmp_path / "none.sqlite")


def test_lookup_needs_no_zip_and_no_shapely(prepared) -> None:
    _, _, path, _ = prepared
    code = ("import sys; from hererisk.flood.diag import DiagIndex; d = DiagIndex(sys.argv[1]); "
            "r = d.lookup(35.0018, 139.0011, [5, 10, 25, 50, 100]); "
            "assert r['diagnosis_only'] and r['components']; assert 'shapely' not in sys.modules; print('ok')")
    env = {"PYTHONPATH": str(diag.Path(diag.__file__).parents[2])}
    out = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, text=True, env=env, check=True)
    assert out.stdout.strip() == "ok"


def test_cli_compare_cases_bench_and_provider_unchanged(prepared, tmp_path, capsys) -> None:
    regions, index, path, _ = prepared
    before = FloodProvider(regions, index).lookup(*reversed(ll(410, 20)))
    rep = local_analysis.run(regions, index=index, per_category=4, per_rank=2, defect_points=4,
                             extra_points=[tuple(reversed(ll(410, 20))), tuple(reversed(INVERTED[6]))])
    base = local_analysis.write_report(rep, rep.pop("_geoms"), tmp_path / "reports")
    args = ["diag", "compare", "--diag-index", str(path), "--flood-index", str(index), "--baseline", str(base),
            "--report-dir", str(tmp_path / "reports")]
    assert flood_cli(args) == 0
    out = json.loads(capsys.readouterr().out.split("report:")[0])
    assert out["pairs_compared"] > 0 and out["pairs_mismatched"] == 0
    assert out["case_a_summary"]["machine_undetermined"] == out["case_a_summary"]["pairs"]
    cmp_dir = next(p for p in (tmp_path / "reports").iterdir() if p.name.startswith("flood-diag-compare-"))
    assert flood_cli(["diag", "cases", "--diag-index", str(path), "--cases", str(cmp_dir / "regression-cases.json")]) == 0
    capsys.readouterr()
    assert flood_cli(["diag", "bench", "--diag-index", str(path), "--points", str(cmp_dir / "bench-points.json"),
                      "--repeat", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["peak_rss_bytes"] > 0
    cfg = tmp_path / "s.json"
    cfg.write_text(json.dumps({"local_analysis": {"enabled": False, "initial_radius_m": 5, "expansion_radii_m": [20],
                                                  "max_radius_m": 20}}))
    assert flood_cli(args[:-2] + ["--settings", str(cfg)]) == 2          # other radii than the baseline
    assert flood_cli(["diag", "point", "--diag-index", str(path), "--point", "x"]) == 2
    assert flood_cli(["diag", "point", "--diag-index", str(tmp_path / "none.sqlite"), "--point", "35,139"]) == 3
    assert FloodProvider(regions, index).lookup(*reversed(ll(410, 20))) == before
