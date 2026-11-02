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
        assert r["category"] in pr.CATEGORIES and r["concept"] in pr.CONCEPTS and r["message_version"] == "v0.2"
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
    doc = (REPO / "docs/api/polygon-reason-catalog-v0.2.md").read_text(encoding="utf-8")
    table = doc[doc.index("## 6."):doc.index("## 7.")]
    listed = set(re.findall(r"^\| `([a-z_]+)` \|", table, re.M))
    assert listed == set(pr.COMMON) | {"flood_response_limit_exceeded"}
    for code, d in pr.COMMON.items():
        assert d["text"]["ja"]["message"] in doc, code


def test_result_messages_phase_4g() -> None:
    """Result kinds (what was read) are kept apart from reason codes (why) and follow the same wording rules."""
    for hazard in (None, "flood", "tsunami"):
        for kind in pr.RESULT_KINDS:
            r = pr.resolve_result(kind, hazard)
            text = r["message_ja"] + r["detail_ja"]
            assert r["message_ja"].strip() and r["detail_ja"].strip() and r["message_version"] == "v0.2"
            assert not any(b in text for b in BANNED) and "境界上" not in text, (hazard, kind)
            assert "正式な判定ではありません" in text or "正式な判定ではなく" in text, (hazard, kind)
            if hazard != "flood":
                assert "浸水" not in text and r["scope"] == "common"
    assert pr.resolve_result("candidate_inside", "flood")["message_ja"] == "この浸水深の想定区域に含まれる可能性があります。"
    assert pr.resolve_result("candidate_outside", "flood")["message_ja"] == "参考解析では、この想定区域の外側と解釈されました。"
    assert "浸水しないことを意味しません" in pr.resolve_result("candidate_outside", "flood")["detail_ja"]
    assert "浸水深は示していません" in pr.resolve_result("candidate_inside_class_unknown", "flood")["detail_ja"]
    with pytest.raises(KeyError):
        pr.resolve_result("no_such_kind", "flood")
    with pytest.raises(ValueError):
        pr.register_hazard_results("x", [{"kind": "new_kind", "scope": "x", "text": {"ja": {"message": "m", "detail": "d"}}}])
    assert {r["kind"] for r in pr.catalog("flood")["results"]} == set(pr.RESULT_KINDS)
    for code in ("diagnosis_limit_exceeded", "diagnosis_busy", "diagnosis_timeout", "diagnosis_failed"):
        r = pr.resolve_reason(code, "flood")
        assert r["known"] and r["category"] == "processing" and "正式な判定には影響しません" in r["detail_ja"]
        assert r["cause"] == "processing"



# --- Phase 4-I: cause, message parameters, v0.2 wording ------------------------------------------------
# v0.1 (Phase 4-F / 4-G) attributes, frozen: code, category, concept, priority, scope must not change
V01_ATTRIBUTES = {
    'all_conditions_met': ('result', 'conditions_met', 90, 'common'),
    'ambiguous_nearest': ('geometry', 'boundary_interpretation_uncertain', 51, 'common'),
    'defect_location_unknown': ('geometry', 'geometry_inconsistency', 46, 'common'),
    'defect_within_decision_radius': ('geometry', 'geometry_inconsistency', 44, 'common'),
    'defect_within_max_radius': ('geometry', 'geometry_inconsistency', 45, 'common'),
    'diag_index_identity_mismatch': ('data', 'data_inconsistency', 11, 'common'),
    'diag_index_not_complete': ('data', 'data_inconsistency', 10, 'common'),
    'diagnosis_busy': ('processing', 'processing_failure', 18, 'common'),
    'diagnosis_failed': ('processing', 'processing_failure', 15, 'common'),
    'diagnosis_limit_exceeded': ('processing', 'processing_failure', 14, 'common'),
    'diagnosis_timeout': ('processing', 'processing_failure', 16, 'common'),
    'even_odd_winding_disagree': ('geometry', 'boundary_interpretation_uncertain', 53, 'common'),
    'feature_invalid_component': ('geometry', 'geometry_inconsistency', 42, 'common'),
    'feature_level_invalidity_not_analyzed': ('geometry', 'geometry_inconsistency', 43, 'common'),
    'flood:defect_within_decision_radius': ('geometry', 'geometry_inconsistency', 44, 'flood'),
    'flood:defect_within_max_radius': ('geometry', 'geometry_inconsistency', 45, 'flood'),
    'flood:flood_response_limit_exceeded': ('processing', 'processing_failure', 17, 'flood'),
    'flood:no_local_boundary': ('geometry', 'local_information_insufficient', 60, 'flood'),
    'flood:on_boundary': ('geometry', 'on_boundary', 30, 'flood'),
    'flood:outside_service_region': ('coverage', 'outside_coverage', 20, 'flood'),
    'flood:pending_geometry_zone': ('geometry', 'geometry_inconsistency', 40, 'flood'),
    'flood:zone_boundary_contact': ('geometry', 'on_boundary', 31, 'flood'),
    'invalid_geometry': ('geometry', 'geometry_inconsistency', 41, 'common'),
    'local_far_disagree': ('geometry', 'boundary_interpretation_uncertain', 52, 'common'),
    'no_local_boundary': ('geometry', 'local_information_insufficient', 60, 'common'),
    'on_boundary': ('geometry', 'on_boundary', 30, 'common'),
    'orientation_unknown': ('geometry', 'boundary_interpretation_uncertain', 50, 'common'),
    'outside_service_region': ('coverage', 'outside_coverage', 20, 'common'),
    'pending_geometry_zone': ('geometry', 'geometry_inconsistency', 40, 'common'),
    'service_region_boundary': ('coverage', 'coverage_boundary', 21, 'common'),
    'zone_boundary_contact': ('geometry', 'on_boundary', 31, 'common'),
    'zone_ref_not_in_diag_index': ('data', 'data_inconsistency', 12, 'common'),
    'zone_ref_not_in_provider_unknowns': ('data', 'data_inconsistency', 13, 'common'),
}


def test_v01_attributes_unchanged() -> None:
    now = {c: (d["category"], d["concept"], d["priority"], d["scope"]) for c, d in pr.COMMON.items()}
    for d in reason_messages.FLOOD:
        r = pr.resolve_reason(d["code"], "flood")
        now["flood:" + d["code"]] = (r["category"], r["concept"], r["priority"], r["scope"])
    assert now == V01_ATTRIBUTES


CAUSE_EXPECTED = {"invalid_geometry": "source_geometry", "feature_invalid_component": "source_geometry",
                  "no_local_boundary": "search_scope", "ambiguous_nearest": "analysis_method",
                  "local_far_disagree": "analysis_method", "on_boundary": "point_position",
                  "service_region_boundary": "coverage", "diag_index_identity_mismatch": "index_data",
                  "diagnosis_timeout": "processing", "all_conditions_met": "result"}


def test_every_known_code_has_a_cause() -> None:
    for code in ADOPTION_CODES | PROVIDER_CODES | set(pr.COMMON):
        r = pr.resolve_reason(code, "flood")
        assert r["cause"] in pr.CAUSES, code
        assert r.get("background_cause", "source_geometry") in pr.CAUSES
    for code, cause in CAUSE_EXPECTED.items():
        assert pr.resolve_reason(code)["cause"] == cause == pr.resolve_reason(code, "flood")["cause"], code
    assert pr.resolve_reason("flood_response_limit_exceeded", "flood")["cause"] == "processing"
    assert pr.resolve_reason("brand_new_reason", "flood")["cause"] is None          # unknown: kept, no cause guessed
    assert "background_cause" not in pr.resolve_reason("no_local_boundary", "flood")  # not inferred
    # the search scope is never a source-geometry cause, the source geometry codes are
    assert {c for c, d in pr.COMMON.items() if d["cause"] == "search_scope"} == {"no_local_boundary"}


def test_search_radius_parameter() -> None:
    for hazard, word in ((None, "区域"), ("flood", "浸水想定区域")):
        for radius in (100, 50, 25.5):
            r = pr.resolve_reason("no_local_boundary", hazard, params={"max_radius_m": radius})
            shown = f"{radius:g}"
            assert r["message_ja"] == f"周辺{shown}mの範囲では判定に必要な{word}の境界を確認できないため、判定を保留しています。"
            assert f"半径{shown}m" in r["detail_ja"] and "不整合を示すものではありません" in r["detail_ja"]
            assert r["params"] == {"max_radius_m": radius}
        for bad in (None, {}, {"max_radius_m": None}, {"max_radius_m": "100"}, {"max_radius_m": "100m; <b>"},
                    {"max_radius_m": float("nan")}, {"max_radius_m": float("inf")}, {"max_radius_m": -1},
                    {"max_radius_m": 0}, {"max_radius_m": True}, {"max_radius_m": 10 ** 6}, {"other": 5}):
            r = pr.resolve_reason("no_local_boundary", hazard, params=bad)
            text = r["message_ja"] + r["detail_ja"]
            assert "{" not in text and "}" not in text and "m の" not in text and not any(ch.isdigit() for ch in text), bad
            assert "params" not in r and r["message_ja"].startswith("周辺の探索範囲では")
    r = pr.resolve_reason("on_boundary", "flood", params={"max_radius_m": 100})     # undeclared: ignored
    assert "params" not in r and "100" not in r["message_ja"]
    assert pr.resolve_reason("no_local_boundary", "flood", locale="en", params={"max_radius_m": 50})["locale_fallback"] == "ja"
    # no template text is ever left visible
    for hazard in (None, "flood"):
        for c in set(pr.COMMON) | {d["code"] for d in reason_messages.FLOOD}:
            r = pr.resolve_reason(c, hazard)
            assert "{" not in r["message_ja"] + r["detail_ja"], c


def test_parameter_registration_rules() -> None:
    base = {"code": "no_local_boundary", "scope": "x-test"}
    with pytest.raises(ValueError):          # placeholder without a fallback
        pr.register_hazard_messages("x-test", [{**base, "text": {"ja": {"message": "{max_radius_m}m", "detail": "d"}}}])
    with pytest.raises(ValueError):          # undeclared parameter
        pr.register_hazard_messages("x-test", [{**base, "text": {"ja": {"message": "{user_text}", "detail": "d",
                                                                   "fallback": {"message": "m", "detail": "d"}}}}])
    with pytest.raises(ValueError):          # format-style attribute access is not a placeholder: stray brace
        pr.register_hazard_messages("x-test", [{**base, "text": {"ja": {"message": "{max_radius_m.__class__}", "detail": "d",
                                                                   "fallback": {"message": "m", "detail": "d"}}}}])
    with pytest.raises(ValueError):          # a hazard cannot change the cause of a common code
        pr.register_hazard_messages("x-test", [{**base, "cause": "source_geometry",
                                                "text": {"ja": {"message": "m", "detail": "d"}}}])
    with pytest.raises(ValueError):          # a hazard-only code needs a cause
        pr.register_hazard_messages("x-test", [{"code": "x_only", "scope": "x-test", "category": "processing",
                                                "concept": "processing_failure", "priority": 70,
                                                "text": {"ja": {"message": "m", "detail": "d"}}}])


def test_v02_wording() -> None:
    d = pr.resolve_reason("defect_within_decision_radius", "flood")
    assert d["message_ja"] == "判定に必要な範囲に、区域データの輪郭が接する・交わる箇所があるため、判定を保留しています。"
    assert "不整合とは限りません" in d["detail_ja"] and "不整合が見つかりました" not in d["message_ja"]
    assert pr.resolve_reason("ambiguous_nearest", "flood")["message_ja"] == \
        "近くに複数の区域境界があり、どちらの側かを区別できないため、判定を保留しています。"
    assert pr.resolve_reason("defect_within_max_radius", "flood")["message_ja"] == "元の区域データの境界に不整合があるため、正確に判定できません。"
    for c, dd in pr.COMMON.items():           # a search / method cause never claims a data inconsistency in its message
        if dd["cause"] in ("search_scope", "analysis_method", "point_position", "coverage"):
            m = pr.resolve_reason(c, "flood")["message_ja"]
            if dd.get("background_cause") != "source_geometry":
                assert "不整合" not in m, c


def test_record_parameters_and_representative() -> None:
    comp = {"reason": "invalid_geometry", "ring_count": 1}
    rec = adoption.classify(ctx(), comp, {"local": {"outcome": "no_boundary_within_max_radius", "radius_m": 50},
                                          "defect_within_max": None})
    assert rec["reasons"] == ["no_local_boundary"] and rec["evidence"]["stopped_at_m"] == 50
    e = explain(rec)
    assert e["user"]["message_ja"].startswith("周辺50mの範囲では") and e["technical"]["messages"][0]["cause"] == "search_scope"
    it = reason_messages.interpret({**rec, "source_id": "s", "zone_ref": "z"})
    assert it["message"]["cause"] == "search_scope" and "周辺50m" in it["message"]["message_ja"]
    other = adoption.classify(ctx(), comp, {"local": {"outcome": "on_boundary", "radius_m": 5}, "defect_within_max": None})
    assert reason_messages.message_params(other) == {}                    # no radius for another outcome
    both = adoption.classify(ctx(service_region_relation="boundary"), comp,
                             {"local": {"outcome": "no_boundary_within_max_radius", "radius_m": 100}, "defect_within_max": None})
    r = explain(both)
    assert both["reasons"] == ["service_region_boundary", "no_local_boundary"]          # none dropped
    assert r["technical"]["reasons"] == both["reasons"] and r["user"]["message_ja"].startswith("提供データの対象地域")
    assert [m["cause"] for m in r["technical"]["messages"]] == ["coverage", "search_scope"]
