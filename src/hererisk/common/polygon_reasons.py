"""Reason codes and Japanese messages for polygon-based judgements (Phase 4-F), shared by hazards.

The one place where reason codes get their user text. Codes are stable machine identifiers and never
change with the wording; the text is versioned by ``MESSAGE_VERSION``. Nothing here knows a hazard:
a hazard module registers its own wording with ``register_hazard_messages`` (e.g.
``hererisk.flood.reason_messages``), and ``resolve_reason`` falls back to the neutral common text
("対象区域", "区域データ"). No hazard meaning (depths, warning-zone classes) is interpreted here.

Each definition: ``code``, ``category`` (geometry / coverage / data / processing / result),
``concept`` (the shared meaning, ``CONCEPTS``), ``priority`` (smaller = shown first when one
representative message is needed; never the order of the reason list), ``scope`` (``common`` or the
hazard type), and per locale ``message`` (short, for users) and ``detail`` (why it is not decided).

Wording rules (checked by tests): an undecided result is never called safe; "境界上" only where the
point was found on a boundary line; a shape inconsistency of the source is not called an error of the
data or a lack of maintenance; GPS accuracy is not a polygon defect and is not described here.
"""

from __future__ import annotations

import threading
from typing import Any, Iterable

MESSAGE_VERSION = "v0.1"
DEFAULT_LOCALE = "ja"
CATEGORIES = ("geometry", "coverage", "data", "processing", "result")
CONCEPTS = {
    "inside": "対象区域の内側",
    "outside": "対象区域の外側",
    "on_boundary": "対象区域の境界線上",
    "geometry_inconsistency": "区域データの形状に不整合がある",
    "boundary_interpretation_uncertain": "境界の解釈が定まらない",
    "local_information_insufficient": "周辺の情報だけでは判断できない",
    "coverage_boundary": "データの対象地域の境界付近",
    "outside_coverage": "データの対象地域の外",
    "data_inconsistency": "入力データ・索引の整合性を確認できない",
    "processing_failure": "処理が完了しなかった",
    "information_missing": "判断に必要な情報がない",
    "conditions_met": "定義した条件をすべて満たした（参考解釈）",
}
# assessment kinds: the official answer is kept apart from diagnostic interpretations
ASSESSMENT_KINDS = {
    "official": {"ja": "公式データによる判定"},
    "diagnostic_candidate": {"ja": "参考解釈の候補（正式な判定ではありません）"},
    "undetermined": {"ja": "判定保留"},
    "not_applicable": {"ja": "判定対象外・利用不能"},
}


def _d(code, category, concept, priority, message, detail):
    return {"code": code, "category": category, "concept": concept, "priority": priority, "scope": "common",
            "text": {"ja": {"message": message, "detail": detail}}}


COMMON: dict[str, dict[str, Any]] = {d["code"]: d for d in (
    # data / processing: nothing below can be relied on
    _d("diag_index_not_complete", "data", "data_inconsistency", 10,
       "判定に使用するデータの準備が完了していません。",
       "診断用の索引が作成途中または不完全なため、診断を行っていません。"),
    _d("diag_index_identity_mismatch", "data", "data_inconsistency", 11,
       "判定に使用するデータの整合性を確認できませんでした。",
       "診断用の索引が、現在使用している区域データの索引から作られたものと確認できないため、診断結果を使用していません。"),
    _d("zone_ref_not_in_diag_index", "data", "data_inconsistency", 12,
       "判定に使用するデータの整合性を確認できませんでした。",
       "対象の区域が診断用の索引に含まれていないため、診断を行っていません。"),
    _d("zone_ref_not_in_provider_unknowns", "data", "data_inconsistency", 13,
       "この区域は診断の対象ではありません。",
       "正式な検索で判定保留とされた区域だけを診断します。この区域はその対象に含まれていません。"),
    _d("diagnosis_failed", "processing", "processing_failure", 15,
       "判定の処理が完了しませんでした。",
       "診断処理が失敗したため、結果がありません。正式な判定には影響しません。"),
    _d("diagnosis_timeout", "processing", "processing_failure", 16,
       "判定の処理が時間内に完了しませんでした。",
       "診断処理が制限時間を超えたため中断しました。正式な判定には影響しません。"),
    # coverage
    _d("outside_service_region", "coverage", "outside_coverage", 20,
       "この地点は、登録している区域データの対象地域の外です。",
       "登録している区域データの対象地域（提供範囲）に含まれないため、判定していません。該当がないことを意味しません。"),
    _d("service_region_boundary", "coverage", "coverage_boundary", 21,
       "提供データの対象地域の境界付近にあるため、判定できません。",
       "地点が区域データの対象地域の境界から一定距離内にあるため、対象地域の内外を確定していません。"),
    # geometry: the point and the boundary line
    _d("on_boundary", "geometry", "on_boundary", 30,
       "対象区域の境界上にあるため、区域内かどうかを確定できません。",
       "地点が原典の区域の境界線上に位置するため、内側または外側として確定していません。"),
    _d("zone_boundary_contact", "geometry", "on_boundary", 31,
       "対象区域の境界上にあるため、区域内かどうかを確定できません。",
       "地点が原典の区域の境界線に接しているため、区域内として確定していません。"),
    # geometry: the source shape
    _d("pending_geometry_zone", "geometry", "geometry_inconsistency", 40,
       "区域データの形状に不整合がある範囲のため、区域内かどうかを確定できません。",
       "地点が、形状の検査で不整合が見つかった区域の範囲（外接矩形）に入るため、判定を保留しています。"),
    _d("invalid_geometry", "geometry", "geometry_inconsistency", 41,
       "区域データの形状に不整合があるため、この区域では判定できません。",
       "原典の区域の形状が、形状の検査（GEOS）で有効と判定されなかったため、判定に使用していません。"),
    _d("feature_invalid_component", "geometry", "geometry_inconsistency", 42,
       "区域データの形状に不整合があるため、この区域では判定できません。",
       "原典で同じ区域を構成する図形どうしが重なるなど、区域全体として有効と判定されなかったため、判定に使用していません。"),
    _d("feature_level_invalidity_not_analyzed", "geometry", "geometry_inconsistency", 43,
       "区域データの形状に不整合があるため、正確に判定できません。",
       "区域を構成する図形どうしの不整合は、診断の対象外のため、判定を保留しています。"),
    _d("defect_within_decision_radius", "geometry", "geometry_inconsistency", 44,
       "判定に必要な範囲で、区域データの形状に不整合が見つかりました。",
       "地点の周辺で判定に使う範囲の中に、区域の輪郭が自身と接する・交わる箇所があるため、判定を保留しています。"),
    _d("defect_within_max_radius", "geometry", "geometry_inconsistency", 45,
       "元の区域データの境界に不整合があるため、正確に判定できません。",
       "周辺の輪郭からは内外を読めましたが、調べる範囲の中に輪郭の不整合箇所があるため、その読みを確定していません。"),
    _d("defect_location_unknown", "geometry", "geometry_inconsistency", 46,
       "区域データの形状に不整合があるため、正確に判定できません。",
       "形状の不整合の位置を特定できなかったため、判定を保留しています。"),
    # geometry: the reading is not settled
    _d("orientation_unknown", "geometry", "boundary_interpretation_uncertain", 50,
       "区域データの輪郭の向きを確定できず、区域内かどうかを判断できません。",
       "輪郭の向き（内側がどちらか）を区域データから決められないため、判定を保留しています。"),
    _d("ambiguous_nearest", "geometry", "boundary_interpretation_uncertain", 51,
       "周辺の区域境界が複雑なため、判定結果を確定できません。",
       "地点から同じ距離に複数の境界があり、それぞれから読める内外が一致しないため、判定を保留しています。"),
    _d("local_far_disagree", "geometry", "boundary_interpretation_uncertain", 52,
       "区域の境界の解釈が定まらないため、判定結果を確定できません。",
       "近くの境界から読んだ内外と、区域全体の輪郭から求めた内外が一致しないため、判定を保留しています。"),
    _d("even_odd_winding_disagree", "geometry", "boundary_interpretation_uncertain", 53,
       "区域の境界の解釈が定まらないため、判定結果を確定できません。",
       "区域の輪郭を数える2つの方法で内外が一致しないため、判定を保留しています。"),
    _d("no_local_boundary", "geometry", "local_information_insufficient", 60,
       "周辺の境界情報だけでは、区域内かどうかを確実に判定できません。",
       "調べる範囲の中に区域の境界がなく、周辺の情報だけでは内外を確定できないため、判定を保留しています。"),
    # result
    _d("all_conditions_met", "result", "conditions_met", 90,
       "参考の解釈です。正式な判定ではありません。",
       "定義した診断の条件をすべて満たしましたが、原典の正式な区域として判定したものではありません。"),
)}
UNKNOWN_REASON = {"code": None, "category": "data", "concept": "information_missing", "priority": 99, "scope": "common",
                  "text": {"ja": {"message": "判定の理由を表示できません。",
                                  "detail": "この理由コードの説明が登録されていません。理由コードはそのまま保持しています。"}}}

_HAZARDS: dict[str, dict[str, dict[str, Any]]] = {}
_LOCK = threading.Lock()


def register_hazard_messages(hazard_type: str, definitions: Iterable[dict[str, Any]]) -> None:
    """Hazard wording. Each definition: code, scope == hazard_type, text {locale: {message, detail}};
    category / concept / priority are taken from the common code unless given (a hazard-only code must
    give them)."""
    table = {}
    for d in definitions:
        base = COMMON.get(d["code"])
        if d.get("scope") != hazard_type:
            raise ValueError("a hazard definition must have scope == hazard_type")
        if base is None and not all(k in d for k in ("category", "concept", "priority")):
            raise ValueError("a hazard-only code needs category, concept and priority")
        merged = {**(base or {}), **d}
        if merged["category"] not in CATEGORIES or merged["concept"] not in CONCEPTS:
            raise ValueError("unknown category or concept")
        if not all(t.get("message", "").strip() and t.get("detail", "").strip() for t in merged["text"].values()):
            raise ValueError("empty message")
        table[d["code"]] = merged
    with _LOCK:
        _HAZARDS[hazard_type] = table


def resolve_reason(code: str, hazard_type: str | None = None, locale: str = DEFAULT_LOCALE) -> dict[str, Any]:
    """The message definition of one code: the hazard's own, else the common one, else a generic one
    that keeps the code (``known: false``)."""
    d = (_HAZARDS.get(hazard_type) or {}).get(code) if hazard_type else None
    d = d or COMMON.get(code)
    known = d is not None
    d = d or UNKNOWN_REASON
    text = d["text"].get(locale)
    fallback = text is None
    text = text or d["text"][DEFAULT_LOCALE]
    out = {"code": code, f"message_{locale if not fallback else DEFAULT_LOCALE}": text["message"],
           f"detail_{locale if not fallback else DEFAULT_LOCALE}": text["detail"], "category": d["category"],
           "concept": d["concept"], "scope": d["scope"], "priority": d["priority"], "known": known,
           "hazard_type": hazard_type, "message_version": MESSAGE_VERSION}
    if fallback:
        out["locale_fallback"] = DEFAULT_LOCALE
    return out


def resolve_reasons(codes: Iterable[str], hazard_type: str | None = None,
                    locale: str = DEFAULT_LOCALE) -> dict[str, Any]:
    """Every code, in the given order (none dropped, unknown ones kept), and one representative chosen
    by ``priority`` then code (independent of the order of ``codes``)."""
    resolved = [resolve_reason(c, hazard_type, locale) for c in codes]
    rep = min(resolved, key=lambda r: (r["priority"], str(r["code"]))) if resolved else None
    return {"reasons": [r["code"] for r in resolved], "messages": resolved, "representative": rep,
            "message_version": MESSAGE_VERSION}


def catalog(hazard_type: str | None = None) -> dict[str, Any]:
    """Every definition (common, or common with the hazard's wording) for a settings / data screen."""
    codes = sorted(set(COMMON) | set(_HAZARDS.get(hazard_type, {})))
    return {"message_version": MESSAGE_VERSION, "concepts": CONCEPTS, "assessment_kinds": ASSESSMENT_KINDS,
            "hazard_type": hazard_type, "reasons": [resolve_reason(c, hazard_type) for c in codes]}
