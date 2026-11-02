"""Phase 4-B: flood verification against the source (synthetic fixtures of test_flood_provider).

The verifier must PASS a correct index, keep invalid-geometry points INDETERMINATE (never PASS), and
FAIL an index that differs from the source: a changed class, a lost feature, a wrong classification.
"""

from __future__ import annotations

import json
import shutil
import sqlite3

import pytest

pytest.importorskip("shapely")

from hererisk.flood import verify                                   # noqa: E402
from hererisk.flood.index import build_index, main as flood_cli       # noqa: E402
from test_flood_provider import data, two_sources                    # noqa: E402,F401  (fixture + helper)


@pytest.fixture
def built(data, tmp_path):   # noqa: F811
    regions = two_sources(data)
    build_index(regions, tmp_path / "index.sqlite")
    return regions, tmp_path / "index.sqlite"


def run(regions, index, **kw):
    return verify.run(regions, index, per_category=5, per_rank=3, **kw)


def test_correct_index_passes_and_invalid_stays_indeterminate(built) -> None:
    regions, index = built
    rep = run(regions, index, extra_points=[(35.0075, 139.0072), (35.0012, 139.0012)])
    v = rep["summary"]["verdicts"]
    assert v["FAIL"] == 0 and v["ERROR"] == 0 and v["PASS"] > 0 and v["OUT_OF_SCOPE"] > 0
    assert all(s["result"] == "PASS" for s in rep["reconciliation"]["sources"])
    assert all(f["match"] for f in rep["reconciliation"]["files"])
    given = [p for p in rep["points"] if p["category"] == "given"]
    assert given[0]["verdict"] == "INDETERMINATE"                     # inside the bow-tie's bounding box
    pending = given[0]["sources"]["src-a"]["pending"][0]
    assert pending["reason"].startswith("Self-intersection") or pending["reason"].startswith("Ring Self")
    assert set(pending["reads"]) == {"even_odd", "make_valid", "exterior_only"}   # diagnosis only
    assert given[1]["verdict"] == "PASS" and given[1]["sources"]["src-a"]["zones"][0]["rank"] == "2"
    assert "INDETERMINATE" not in [p["verdict"] for p in rep["points"] if p["category"] == "outside_region"]
    assert rep["summary"]["by_category"]["multi_source"]                # both sources overlap at one place


def test_same_seed_same_points(built) -> None:
    regions, index = built
    a = [(p["category"], p["lat"], p["lon"]) for p in run(regions, index)["points"]]
    b = [(p["category"], p["lat"], p["lon"]) for p in run(regions, index)["points"]]
    c = [(p["category"], p["lat"], p["lon"]) for p in run(regions, index, seed=7)["points"]]
    assert a == b and a != c


def _tamper(index, sql, tmp_path):
    copy = tmp_path / "tampered.sqlite"
    shutil.copy(index, copy)
    db = sqlite3.connect(copy)
    db.execute(sql)
    db.commit()
    db.close()
    return copy


def test_changed_depth_class_is_a_fail(built, tmp_path) -> None:
    regions, index = built
    bad = _tamper(index, "UPDATE components SET depth_class = replace(depth_class, '\"class_code\": \"2\"', "
                         "'\"class_code\": \"5\"') WHERE source_id = 'src-a' AND usable = 1", tmp_path)
    rep = run(regions, bad, extra_points=[(35.0012, 139.0012)])
    assert rep["reconciliation"]["sources"][0]["result"] == "FAIL"
    given = [p for p in rep["points"] if p["category"] == "given"][0]
    assert given["verdict"] == "FAIL" and any("attributes" in d for d in given["diffs"])


def test_lost_feature_and_wrong_class_are_fails(built, tmp_path) -> None:
    regions, index = built
    lost = _tamper(index, "DELETE FROM components WHERE source_id = 'src-b' AND usable = 1 AND minx < 139.01", tmp_path)
    rep = run(regions, lost, extra_points=[(35.0018, 139.0018)])
    src_b = rep["reconciliation"]["sources"][1]
    assert src_b["result"] == "FAIL" and any("missing from the index" in p for p in src_b["problems"])
    assert [p for p in rep["points"] if p["category"] == "given"][0]["verdict"] == "FAIL"
    flipped = _tamper(index, "UPDATE components SET usable = 1, reason = NULL WHERE reason = 'invalid_geometry'", tmp_path)
    rep = run(regions, flipped, extra_points=[(35.0075, 139.0072)])
    assert rep["reconciliation"]["sources"][0]["result"] == "FAIL"
    assert [p for p in rep["points"] if p["category"] == "given"][0]["verdict"] == "FAIL"


def test_cli_report_and_exit_codes(built, tmp_path, capsys) -> None:
    regions, index = built
    args = ["verify", "--regions", str(regions), "--index", str(index), "--per-category", "3", "--per-rank", "2",
            "--report-dir", str(tmp_path / "reports"), "--point", "35.0075,139.0072"]
    assert flood_cli(args) == 0
    out = capsys.readouterr().out
    assert "verdicts: PASS=" in out and "not a proof" in out
    report = next((tmp_path / "reports").iterdir())
    summary = json.loads((report / "summary.json").read_text())
    assert summary["inputs"]["seed"] == 20261102 and summary["program"]["geos"]
    cases = json.loads((report / "cases.json").read_text())
    assert cases and cases[0]["cause"].startswith("INDETERMINATE")
    assert len((report / "points.jsonl").read_text().splitlines()) == summary["summary"]["points"]
    bad = _tamper(index, "DELETE FROM components WHERE source_id = 'src-b'", tmp_path)
    assert flood_cli(["verify", "--regions", str(regions), "--index", str(bad), "--per-category", "2"]) == 1
    assert flood_cli(["verify", "--regions", str(regions), "--index", str(index), "--point", "x"]) == 2
    assert flood_cli(["verify", "--regions", str(regions), "--index", str(tmp_path / "none.sqlite")]) == 3
    assert flood_cli(["verify", "--regions", str(regions), "--index", str(index), "--source", "nope"]) == 3


def test_source_filter(built) -> None:
    regions, index = built
    rep = run(regions, index, source_ids=["src-b"])
    assert rep["inputs"]["sources"] == ["src-b"] and len(rep["reconciliation"]["sources"]) == 1
    assert rep["summary"]["verdicts"]["FAIL"] == 0
