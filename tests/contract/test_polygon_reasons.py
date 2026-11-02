"""Phase 4-F: shared polygon reason codes, Japanese messages, and their connection to the flood diagnosis."""

from __future__ import annotations

import itertools
import re
import subprocess
import sys
from pathlib import Path

import pytest

from hererisk.common import polygon_reasons as pr
from hererisk.flood import adoption, reason_messages
from hererisk.flood.reason_messages import explain

REPO = Path(__file__).resolve().parents[2]
ADOPTION_CODES = {c for codes in adoption.REASONS.values() for c in codes} | {"all_conditions_met"}
PROVIDER_CODES = {"pending_geometry_zone", "zone_boundary_contact", "service_region_boundary",   # status reasons
                  "outside_service_region", "invalid_geometry", "feature_invalid_component",    # reason / unknowns
                  "flood_response_limit_exceeded"}
BANNED = ("安全", "誤って", "誤り", "間違", "整備が不足", "不備", "危険")


def all_texts(hazard=None):
    for c in sorted(set(pr.COMMON) | {d["code"] for d in reason_messages.FLOOD}):
        r = pr.resolve_reason(c, hazard)
        yield c, r["message_ja"], r["detail_ja"]


def test_every_known_code_has_non_empty_japanese_text() -> None:
    for code in ADOPTION_CODES | PROVIDER_CODES:
        r = pr.resolve_reason(code, "flood")
        assert r["known"] and r["message_ja"].strip() and r["detail_ja"].strip(), code
        assert r["category"] in pr.CATEGORIES and r["concept"] in pr.CONCEPTS and r["message_version"] == "v0.1"
    for code in ADOPTION_CODES - {"flood_response_limit_exceeded"}:
        assert pr.resolve_reason(code)["known"], code                       # common text without a hazard


def test_wording_rules() -> None:
    for hazard in (None, "flood"):
        for code, msg, detail in all_texts(hazard):
            assert not any(b in msg + detail for b in BANNED), (code, msg)
            if "境界上" in msg + detail or "境界線上" in msg + detail:
                assert pr.resolve_reason(code, hazard)["concept"] == "on_boundary", code
    for code, msg, detail in all_texts(None):                              # common text is hazard neutral
        assert "浸水" not in msg + detail and "津波" not in msg + detail, code
    assert "GPS" not in "".join(m + d for _, m, d in all_texts("flood"))   # positioning is another concept


def test_flood_wording_and_fallback() -> None:
    r = pr.resolve_reason("on_boundary", "flood")
    assert r["message_ja"] == "浸水想定区域の境界上にあるため、区域内かどうかを確定できません。" and r["scope"] == "flood"
    assert pr.resolve_reason("on_boundary")["message_ja"].startswith("対象区域の境界上") and \
        pr.resolve_reason("on_boundary")["scope"] == "common"
    fb = pr.resolve_reason("orientation_unknown", "flood")                 # no flood wording -> common
    assert fb["scope"] == "common" and fb["message_ja"] == "区域データの輪郭の向きを確定できず、区域内かどうかを判断できません。"
    other = pr.resolve_reason("ambiguous_nearest", "tsunami")               # a hazard with no catalog yet
    assert other["scope"] == "common" and other["hazard_type"] == "tsunami"
    assert pr.resolve_reason("diag_index_identity_mismatch", "flood")["message_ja"] == \
        "判定に使用するデータの整合性を確認できませんでした。"
    en = pr.resolve_reason("on_boundary", "flood", locale="en")
    assert en["locale_fallback"] == "ja" and en["message_ja"]               # future locales: explicit fallback


def test_unknown_code_is_kept() -> None:
    r = pr.resolve_reason("brand_new_reason", "flood")
    assert r["code"] == "brand_new_reason" and r["known"] is False and r["message_ja"].strip()
    rs = pr.resolve_reasons(["on_boundary", "brand_new_reason"], "flood")
    assert rs["reasons"] == ["on_boundary", "brand_new_reason"]


def test_representative_is_by_priority_not_order() -> None:
    codes = ["defect_within_max_radius", "service_region_boundary", "no_local_boundary"]
    reps = {pr.resolve_reasons(list(p), "flood")["representative"]["code"] for p in itertools.permutations(codes)}
    assert reps == {"service_region_boundary"}
    assert pr.resolve_reasons([])["representative"] is None
    priorities = [d["priority"] for d in pr.COMMON.values()]
    assert len(priorities) == len(set(priorities))                          # no tie between common codes


def test_register_rules() -> None:
    with pytest.raises(ValueError):
        pr.register_hazard_messages("landslide", [{"code": "x_only", "scope": "landslide",
                                                   "text": {"ja": {"message": "m", "detail": "d"}}}])
    with pytest.raises(ValueError):
        pr.register_hazard_messages("landslide", [{"code": "on_boundary", "scope": "landslide",
                                                   "text": {"ja": {"message": " ", "detail": "d"}}}])
    pr.register_hazard_messages("landslide-test", [{"code": "on_boundary", "scope": "landslide-test",
                                                    "text": {"ja": {"message": "警戒区域の境界上にあるため、区域内かどうかを確定できません。",
                                                                    "detail": "地点が原典の区域の境界線上にあります。"}}}])
    r = pr.resolve_reason("on_boundary", "landslide-test")
    assert r["scope"] == "landslide-test" and r["category"] == "geometry" and r["priority"] == pr.COMMON["on_boundary"]["priority"]


def test_common_module_is_independent() -> None:
    code = "import sys, hererisk.common.polygon_reasons; print(sorted(m for m in sys.modules if m.startswith(('hererisk.flood', 'hererisk.location', 'shapely', 'numpy'))))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": str(REPO / "src")})
    assert out.stdout.strip() == "[]"
    text = (REPO / "src/hererisk/common/polygon_reasons.py").read_text(encoding="utf-8")
    assert "import hererisk.flood" not in text and "from hererisk.flood" not in text and "from hererisk.location" not in text


def ctx(**kw):
    return {"status": "complete", "identity_ok": True, "in_provider_unknowns": True,
            "service_region_relation": "inside", **kw}


def test_explain_keeps_every_reason_and_the_classification() -> None:
    comp = {"reason": "invalid_geometry", "ring_count": 3}
    rec = adoption.classify(ctx(service_region_relation="boundary"), comp,
                            {"local": {"outcome": "inside", "radius_m": 10, "winding": 1, "parity_inside": False},
                             "defect_within_max": (40.0, "touch")})
    assert rec["reasons"] == ["service_region_boundary", "even_odd_winding_disagree", "defect_within_max_radius"]
    e = explain({**rec, "source_id": "src-a", "zone_ref": "loc-zn-x", "method": "m"})
    assert e["technical"]["reasons"] == rec["reasons"] and len(e["technical"]["messages"]) == 3
    assert e["assessment_kind"] == "undetermined" and e["technical"]["official"] is False
    assert e["user"]["message_ja"] == pr.resolve_reason("service_region_boundary", "flood")["message_ja"]
    assert e["technical"]["source_id"] == "src-a" and e["technical"]["zone_ref"] == "loc-zn-x"
    cand = explain(adoption.classify(ctx(), comp, {"local": {"outcome": "outside", "radius_m": 5, "winding": 0,
                                                             "parity_inside": False}, "defect_within_max": None}))
    assert cand["assessment_kind"] == "diagnostic_candidate" and "正式な判定ではありません" in cand["user"]["message_ja"]
    rej = explain(adoption.classify(ctx(identity_ok=False), comp, None))
    assert rej["assessment_kind"] == "not_applicable"
    for outcome, code in adoption.LOCAL_UNDETERMINED.items():               # every local outcome is explained
        e = explain(adoption.classify(ctx(), comp, {"local": {"outcome": outcome}, "defect_within_max": None}))
        assert e["technical"]["messages"][0]["code"] == code and e["technical"]["messages"][0]["known"]


def test_contract_document_lists_every_code() -> None:
    doc = (REPO / "docs/api/polygon-reason-catalog-v0.1.md").read_text(encoding="utf-8")
    table = doc[doc.index("## 6."):doc.index("## 7.")]
    listed = set(re.findall(r"^\| `([a-z_]+)` \|", table, re.M))
    assert listed == set(pr.COMMON) | {"flood_response_limit_exceeded"}
    for code, d in pr.COMMON.items():
        assert d["text"]["ja"]["message"] in doc, code
