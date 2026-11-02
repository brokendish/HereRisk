"""Phase 4-J research: inside / outside of a point for valid and invalid polygons (synthetic only).

Pins the study's findings on synthetic geometry: the local search limit is not a property of the data,
far defects can change a point's relation (interpretation-dependent faces), and the per-ring winding
condition H2 separated every interpretation-dependent point found. Research code only: no product
module imports ``hererisk.research``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("shapely")

from hererisk.research import point_study as ps        # noqa: E402

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def report():
    return ps.run_synthetic(fuzz_n=300)


def pt(report, case, label):
    c = next(c for c in report["cases"] if c["name"].startswith(case))
    return next(p for p in c["points"] if p["label"] == label)


def test_valid_large_polygons_are_determinate_whatever_the_radius(report) -> None:
    p = pt(report, "C03", "centre")
    assert p["study"]["class"] == "determinate" and p["study"]["relation"] == "inside"
    assert {v["outcome"] for v in p["local"].values()} == {"no_boundary_within_max_radius"}   # even at 1,000 m
    q = pt(report, "C04", "middle")
    assert q["local"]["r100"]["outcome"] == "no_boundary_within_max_radius" and q["local"]["r500"]["outcome"] == "inside"
    assert pt(report, "C06", "hole centre")["study"]["relation"] == "outside"


def test_far_defects_can_decide_a_point(report) -> None:
    for case, label in (("C09", "inside the reversed lobe"), ("C10", "big lobe, 1.5 km from the crossing"),
                        ("C12", "hole outside shell"), ("C16", "inner square")):
        p = pt(report, case, label)
        assert p["study"]["class"] == "interpretation_dependent", (case, label)
        assert not p["facts"]["h2_per_ring_unit"]
        assert not any(v["conditions_met"] for v in p["local"].values())        # the local rule does not adopt it
    far = pt(report, "C10", "big lobe, 1.5 km from the crossing")
    assert far["facts"]["defect_m"] > 1000                                     # distance alone would miss it
    assert pt(report, "C10", "small lobe, 1.2 km from the crossing")["study"]["class"] == "interpretation_consistent"


def test_far_touch_does_not_change_membership(report) -> None:
    for label in ("far inside", "in the triangle", "far corner"):
        assert pt(report, "C08", label)["study"]["class"] == "interpretation_consistent"
    assert pt(report, "C11", "upper part")["study"]["relation"] == "inside"   # disconnected interior, same membership


def test_feature_level_overlap_and_boundary(report) -> None:
    f = pt(report, "C14", "in the overlap")
    assert f["feature_class"] == "interpretation_dependent"
    assert f["feature_interpretations"]["union"] == "inside" and f["feature_interpretations"]["parity_over_components"] == "outside"
    assert pt(report, "C15", "on an edge")["study"]["class"] == "on_boundary"


def test_h2_separates_every_dependent_point(report) -> None:
    for c in report["cases"]:
        for p in c["points"]:
            if "study" not in p or p["study"]["class"] in ("on_boundary", "determinate"):
                continue
            if p["facts"]["h2_per_ring_unit"] and p["study"]["class"] != "insufficient_evidence":
                assert p["study"]["class"] == "interpretation_consistent", (c["name"], p["label"])
    fz = report["fuzz"]
    assert fz["points_tested"] > 5000 and fz["violations_h2_found"] == 0


def test_research_is_not_imported_by_the_product() -> None:
    for path in (REPO / "src/hererisk").rglob("*.py"):
        if "research" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        assert "hererisk.research" not in text, path
