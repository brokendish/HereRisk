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

Phase 4-I (``MESSAGE_VERSION`` v0.2): every code also has ``cause``, the direct cause of the reason
(``CAUSES``: the source's geometry, the search scope, the analysis method, the point's position, the
coverage, HereRisk's index, the analysis scope, processing, a result), and ``background_cause`` only
where it holds by the definition of the code (never inferred per record). A cause other than
``source_geometry`` is not a statement about the source data (a search limit is not a data defect).
A text may hold placeholders (``{max_radius_m}``) for the parameters the definition declares in
``params``; ``resolve_reason(..., params=...)`` fills them with checked numbers only, and without a
valid value the declared ``fallback`` text (no number) is used. Templates are never evaluated
(no ``str.format``); a placeholder is never shown.

Wording rules (checked by tests): an undecided result is never called safe; "境界上" only where the
point was found on a boundary line; a shape inconsistency of the source is not called an error of the
data or a lack of maintenance; GPS accuracy is not a polygon defect and is not described here.
"""

from __future__ import annotations

import re
import threading
from typing import Any, Iterable

MESSAGE_VERSION = "v0.2"
DEFAULT_LOCALE = "ja"
CATEGORIES = ("geometry", "coverage", "data", "processing", "result")
CAUSES = {
    "source_geometry": "原典の形の事実（無効な形状・輪郭の接点・交点・面積0の環）",
    "search_scope": "探索の条件（探索半径など）による。原典の品質の評価ではない",
    "analysis_method": "解析方式の限界・適用条件による",
    "point_position": "地点と区域の形の位置関係（境界線上など）",
    "coverage": "データの対象地域・登録範囲による",
    "index_data": "HereRiskの索引・データの世代の問題",
    "analysis_scope": "診断の対象外",
    "processing": "処理の上限・失敗",
    "result": "結果（定義した条件の成立）",
}
# parameters a text may use: name -> (min exclusive, max inclusive); numbers only
PARAM_RANGES = {"max_radius_m": (0.0, 10000.0)}
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


def _d(code, category, concept, priority, message, detail, *, cause, background_cause=None, params=(),
       fallback=None):
    text = {"message": message, "detail": detail}
    if fallback:
        text["fallback"] = {"message": fallback[0], "detail": fallback[1]}
    d = {"code": code, "category": category, "concept": concept, "priority": priority, "scope": "common",
         "cause": cause, "params": tuple(params), "text": {"ja": text}}
    if background_cause:
        d["background_cause"] = background_cause
    return d


COMMON: dict[str, dict[str, Any]] = {d["code"]: d for d in (
    # data / processing: nothing below can be relied on
    _d("diag_index_not_complete", "data", "data_inconsistency", 10,
       "判定に使用するデータの準備が完了していません。",
       "診断用の索引が作成途中または不完全なため、診断を行っていません。", cause="index_data"),
    _d("diag_index_identity_mismatch", "data", "data_inconsistency", 11,
       "判定に使用するデータの整合性を確認できませんでした。",
       "診断用の索引が、現在使用している区域データの索引から作られたものと確認できないため、診断結果を使用していません。", cause="index_data"),
    _d("zone_ref_not_in_diag_index", "data", "data_inconsistency", 12,
       "判定に使用するデータの整合性を確認できませんでした。",
       "対象の区域が診断用の索引に含まれていないため、診断を行っていません。", cause="index_data"),
    _d("zone_ref_not_in_provider_unknowns", "data", "data_inconsistency", 13,
       "この区域は診断の対象ではありません。",
       "正式な検索で判定保留とされた区域だけを診断します。この区域はその対象に含まれていません。", cause="analysis_scope"),
    _d("diagnosis_limit_exceeded", "processing", "processing_failure", 14,
       "診断の対象となる区域が多すぎるため、参考の解析結果を表示できません。",
       "診断の対象件数が上限を超えたため、一部だけの結果は返していません。正式な判定には影響しません。", cause="processing"),
    _d("diagnosis_failed", "processing", "processing_failure", 15,
       "判定の処理が完了しませんでした。",
       "診断処理が失敗したため、結果がありません。正式な判定には影響しません。", cause="processing"),
    _d("diagnosis_timeout", "processing", "processing_failure", 16,
       "判定の処理が時間内に完了しませんでした。",
       "診断処理が制限時間を超えたため中断しました。正式な判定には影響しません。", cause="processing"),
    _d("diagnosis_busy", "processing", "processing_failure", 18,
       "混み合っているため、参考の解析を実行できませんでした。",
       "同時に処理できる診断の数を超えたため、診断を行っていません。時間をおいて再度お試しください。正式な判定には影響しません。", cause="processing"),
    # coverage
    _d("outside_service_region", "coverage", "outside_coverage", 20,
       "この地点は、登録している区域データの対象地域の外です。",
       "登録している区域データの対象地域（提供範囲）に含まれないため、判定していません。該当がないことを意味しません。", cause="coverage"),
    _d("service_region_boundary", "coverage", "coverage_boundary", 21,
       "提供データの対象地域の境界付近にあるため、判定できません。",
       "地点が区域データの対象地域の境界から一定距離内にあるため、対象地域の内外を確定していません。", cause="coverage"),
    # geometry: the point and the boundary line
    _d("on_boundary", "geometry", "on_boundary", 30,
       "対象区域の境界上にあるため、区域内かどうかを確定できません。",
       "地点が原典の区域の境界線上に位置するため、内側または外側として確定していません。", cause="point_position"),
    _d("zone_boundary_contact", "geometry", "on_boundary", 31,
       "対象区域の境界上にあるため、区域内かどうかを確定できません。",
       "地点が原典の区域の境界線に接しているため、区域内として確定していません。", cause="point_position"),
    # geometry: the source shape
    _d("pending_geometry_zone", "geometry", "geometry_inconsistency", 40,
       "区域データの形状に不整合がある範囲のため、区域内かどうかを確定できません。",
       "地点が、形状の検査で不整合が見つかった区域の範囲（外接矩形）に入るため、判定を保留しています。", cause="source_geometry"),
    _d("invalid_geometry", "geometry", "geometry_inconsistency", 41,
       "区域データの形状に不整合があるため、この区域では判定できません。",
       "原典の区域の形状が、形状の検査（GEOS）で有効と判定されなかったため、判定に使用していません。", cause="source_geometry"),
    _d("feature_invalid_component", "geometry", "geometry_inconsistency", 42,
       "区域データの形状に不整合があるため、この区域では判定できません。",
       "原典で同じ区域を構成する図形どうしが重なるなど、区域全体として有効と判定されなかったため、判定に使用していません。", cause="source_geometry"),
    _d("feature_level_invalidity_not_analyzed", "geometry", "geometry_inconsistency", 43,
       "区域データの形状に不整合があるため、正確に判定できません。",
       "区域を構成する図形どうしの不整合は、診断の対象外のため、判定を保留しています。", cause="analysis_method", background_cause="source_geometry"),
    _d("defect_within_decision_radius", "geometry", "geometry_inconsistency", 44,
       "判定に必要な範囲に、区域データの輪郭が接する・交わる箇所があるため、判定を保留しています。",
       "地点の周辺で判定に使う範囲の中に、区域の輪郭が接する・交わる箇所があります。原典の形状の不整合とは限りませんが、"
       "この範囲では内外の読みを確定していません。", cause="source_geometry"),
    _d("defect_within_max_radius", "geometry", "geometry_inconsistency", 45,
       "元の区域データの境界に不整合があるため、正確に判定できません。",
       "この区域データの形状には不整合があります。周辺の輪郭からは内外を読めましたが、調べる範囲の中に輪郭が接する・交わる箇所が"
       "あるため、その読みを確定していません。", cause="source_geometry"),
    _d("defect_location_unknown", "geometry", "geometry_inconsistency", 46,
       "区域データの形状に不整合があるため、正確に判定できません。",
       "形状の不整合の位置を特定できなかったため、判定を保留しています。", cause="analysis_method", background_cause="source_geometry"),
    # geometry: the reading is not settled
    _d("orientation_unknown", "geometry", "boundary_interpretation_uncertain", 50,
       "区域データの輪郭の向きを確定できず、区域内かどうかを判断できません。",
       "輪郭の向き（内側がどちらか）を区域データから決められないため、判定を保留しています。", cause="source_geometry"),
    _d("ambiguous_nearest", "geometry", "boundary_interpretation_uncertain", 51,
       "近くに複数の区域境界があり、どちらの側かを区別できないため、判定を保留しています。",
       "地点から同じ距離に複数の境界があり、それぞれから読める内外が一致しないため、判定を保留しています。", cause="analysis_method"),
    _d("local_far_disagree", "geometry", "boundary_interpretation_uncertain", 52,
       "区域の境界の解釈が定まらないため、判定結果を確定できません。",
       "近くの境界から読んだ内外と、区域全体の輪郭から求めた内外が一致しないため、判定を保留しています。", cause="analysis_method"),
    _d("even_odd_winding_disagree", "geometry", "boundary_interpretation_uncertain", 53,
       "区域の境界の解釈が定まらないため、判定結果を確定できません。",
       "区域の輪郭を数える2つの方法で内外が一致しないため、判定を保留しています。", cause="analysis_method"),
    _d("no_local_boundary", "geometry", "local_information_insufficient", 60,
       "周辺{max_radius_m}mの範囲では判定に必要な区域の境界を確認できないため、判定を保留しています。",
       "設定した探索範囲（半径{max_radius_m}m）の中に区域の境界がありませんでした。探索範囲による結果で、"
       "区域データの不整合を示すものではありません。", cause="search_scope", params=("max_radius_m",),
       fallback=("周辺の探索範囲では判定に必要な区域の境界を確認できないため、判定を保留しています。",
                 "設定した探索範囲の中に区域の境界がありませんでした。探索範囲による結果で、区域データの不整合を示すものではありません。")),
    # result
    _d("all_conditions_met", "result", "conditions_met", 90,
       "参考の解釈です。正式な判定ではありません。",
       "定義した診断の条件をすべて満たしましたが、原典の正式な区域として判定したものではありません。", cause="result"),
)}
UNKNOWN_REASON = {"code": None, "category": "data", "concept": "information_missing", "priority": 99, "scope": "common",
                  "cause": None, "params": (),
                  "text": {"ja": {"message": "判定の理由を表示できません。",
                                  "detail": "この理由コードの説明が登録されていません。理由コードはそのまま保持しています。"}}}

_HAZARDS: dict[str, dict[str, dict[str, Any]]] = {}
_LOCK = threading.Lock()


_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def _check_definition(d: dict[str, Any]) -> None:
    """Category, concept, cause, declared parameters and texts (placeholders declared, a fallback
    without placeholders whenever a text has one)."""
    if d["category"] not in CATEGORIES or d["concept"] not in CONCEPTS:
        raise ValueError("unknown category or concept")
    if d.get("cause") not in CAUSES or d.get("background_cause", "source_geometry") not in CAUSES:
        raise ValueError("unknown cause")
    params = set(d.get("params") or ())
    if not params <= set(PARAM_RANGES):
        raise ValueError("unknown message parameter")
    for t in d["text"].values():
        if not (t.get("message", "").strip() and t.get("detail", "").strip()):
            raise ValueError("empty message")
        used = set(_PLACEHOLDER.findall(t["message"] + t["detail"]))
        if not used <= params:
            raise ValueError("a text uses an undeclared parameter")
        if "{" in _PLACEHOLDER.sub("", t["message"] + t["detail"]) or "}" in _PLACEHOLDER.sub("", t["message"] + t["detail"]):
            raise ValueError("a stray brace in a text")
        fb = t.get("fallback")
        if used and not (fb and fb.get("message", "").strip() and fb.get("detail", "").strip()):
            raise ValueError("a text with parameters needs a fallback")
        if fb and ("{" in fb["message"] + fb["detail"] or "}" in fb["message"] + fb["detail"]):
            raise ValueError("a fallback must not use parameters")


for _d_ in COMMON.values():
    _check_definition(_d_)


def register_hazard_messages(hazard_type: str, definitions: Iterable[dict[str, Any]]) -> None:
    """Hazard wording. Each definition: code, scope == hazard_type, text {locale: {message, detail[, fallback]}};
    category / concept / priority / cause / params are taken from the common code unless given (a
    hazard-only code must give category, concept, priority and cause)."""
    table = {}
    for d in definitions:
        base = COMMON.get(d["code"])
        if d.get("scope") != hazard_type:
            raise ValueError("a hazard definition must have scope == hazard_type")
        if base is None and not all(k in d for k in ("category", "concept", "priority", "cause")):
            raise ValueError("a hazard-only code needs category, concept, priority and cause")
        if base is not None and any(k in d and d[k] != base[k] for k in ("cause", "background_cause", "params")):
            raise ValueError("a hazard cannot change the cause or the parameters of a common code")
        merged = {**(base or {"params": ()}), **d}
        _check_definition(merged)
        table[d["code"]] = merged
    with _LOCK:
        _HAZARDS[hazard_type] = table


def _param_text(value: Any, name: str) -> str | None:
    """The display text of a parameter value, or None when it is not a valid number in range."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None                                    # strings (even digits) are never inserted
    v = float(value)
    low, high = PARAM_RANGES[name]
    if not (v == v and low < v <= high):              # NaN / inf / out of range
        return None
    r = round(v, 3)
    return str(int(r)) if r == int(r) else f"{r:g}"


def _fill(text: dict[str, Any], declared: tuple, params: dict[str, Any] | None) -> tuple[str, str, dict | None]:
    """(message, detail, applied parameters) with every placeholder filled, else the fallback."""
    used = set(_PLACEHOLDER.findall(text["message"] + text["detail"]))
    if not used:
        return text["message"], text["detail"], None
    values = {n: _param_text((params or {}).get(n), n) for n in used if n in declared}
    if len(values) != len(used) or None in values.values():
        return text["fallback"]["message"], text["fallback"]["detail"], None
    sub = lambda t: _PLACEHOLDER.sub(lambda m: values[m.group(1)], t)   # noqa: E731 - plain substitution
    return sub(text["message"]), sub(text["detail"]), {n: (params or {})[n] for n in used}


def resolve_reason(code: str, hazard_type: str | None = None, locale: str = DEFAULT_LOCALE,
                   params: dict[str, Any] | None = None) -> dict[str, Any]:
    """The message definition of one code: the hazard's own, else the common one, else a generic one
    that keeps the code (``known: false``). ``params`` fills the parameters the code declares (others are
    ignored); a missing or invalid value gives the text without the number."""
    d = (_HAZARDS.get(hazard_type) or {}).get(code) if hazard_type else None
    d = d or COMMON.get(code)
    known = d is not None
    d = d or UNKNOWN_REASON
    text = d["text"].get(locale)
    fallback = text is None
    text = text or d["text"][DEFAULT_LOCALE]
    loc = DEFAULT_LOCALE if fallback else locale
    message, detail, applied = _fill(text, tuple(d.get("params") or ()), params)
    out = {"code": code, f"message_{loc}": message, f"detail_{loc}": detail, "category": d["category"],
           "concept": d["concept"], "cause": d.get("cause"), "scope": d["scope"], "priority": d["priority"],
           "known": known, "hazard_type": hazard_type, "message_version": MESSAGE_VERSION}
    if d.get("background_cause"):
        out["background_cause"] = d["background_cause"]
    if applied:
        out["params"] = applied
    if fallback:
        out["locale_fallback"] = DEFAULT_LOCALE
    return out


def resolve_reasons(codes: Iterable[str], hazard_type: str | None = None, locale: str = DEFAULT_LOCALE,
                    params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Every code, in the given order (none dropped, unknown ones kept), and one representative chosen
    by ``priority`` then code (independent of the order of ``codes``). ``params`` as for ``resolve_reason``."""
    resolved = [resolve_reason(c, hazard_type, locale, params) for c in codes]
    rep = min(resolved, key=lambda r: (r["priority"], str(r["code"]))) if resolved else None
    return {"reasons": [r["code"] for r in resolved], "messages": resolved, "representative": rep,
            "message_version": MESSAGE_VERSION}


# Phase 4-G: what a diagnostic interpretation reads (the result), apart from the reason codes (why it is
# or is not decided). Same mechanism: common neutral text, a hazard registers its own wording.
RESULT_KINDS = {
    "candidate_inside": "参考解析で区域の内側と解釈された（原典の区分あり）",
    "candidate_inside_class_unknown": "参考解析で区域の内側と解釈された（原典の区分を確認できない）",
    "candidate_outside": "参考解析で区域の外側と解釈された",
    "diagnostic_notice": "参考解析の結果全体に添える注記",
}


def _res(kind, message, detail):
    return {"kind": kind, "scope": "common", "text": {"ja": {"message": message, "detail": detail}}}


COMMON_RESULTS: dict[str, dict[str, Any]] = {d["kind"]: d for d in (
    _res("candidate_inside", "参考解析では、この区域に含まれると解釈されました。",
         "元の区域データを独自に解析した結果です。正式な判定ではありません。"),
    _res("candidate_inside_class_unknown", "参考解析では、この区域に含まれると解釈されました。",
         "元の区域データを独自に解析した結果です。正式な判定ではありません。原典の区分を確認できないため、区分は示していません。"),
    _res("candidate_outside", "参考解析では、この区域の外側と解釈されました。",
         "元の区域データを独自に解析した結果です。正式な判定ではなく、該当しないことを確定したものではありません。"),
    _res("diagnostic_notice", "HereRiskが元の区域データを独自に解析した参考情報です。正式な判定ではありません。",
         "公式データによる判定は official_assessment にあります。参考解析は、正式な検索で判定保留とされた区域だけを対象にしています。"),
)}
_HAZARD_RESULTS: dict[str, dict[str, dict[str, Any]]] = {}


def register_hazard_results(hazard_type: str, definitions: Iterable[dict[str, Any]]) -> None:
    """Hazard wording of the result kinds (``RESULT_KINDS`` only; no new kinds)."""
    table = {}
    for d in definitions:
        if d.get("scope") != hazard_type or d.get("kind") not in RESULT_KINDS:
            raise ValueError("a hazard result needs scope == hazard_type and a known kind")
        if not all(t.get("message", "").strip() and t.get("detail", "").strip() for t in d["text"].values()):
            raise ValueError("empty message")
        table[d["kind"]] = d
    with _LOCK:
        _HAZARD_RESULTS[hazard_type] = table


def resolve_result(kind: str, hazard_type: str | None = None, locale: str = DEFAULT_LOCALE) -> dict[str, Any]:
    """The text of one result kind: the hazard's own, else the common one. Unknown kinds raise (a
    result is produced by code, never taken from data)."""
    d = ((_HAZARD_RESULTS.get(hazard_type) or {}).get(kind) if hazard_type else None) or COMMON_RESULTS[kind]
    text = d["text"].get(locale)
    fallback = text is None
    text = text or d["text"][DEFAULT_LOCALE]
    loc = DEFAULT_LOCALE if fallback else locale
    out = {"kind": kind, f"message_{loc}": text["message"], f"detail_{loc}": text["detail"], "scope": d["scope"],
           "hazard_type": hazard_type, "message_version": MESSAGE_VERSION}
    if fallback:
        out["locale_fallback"] = DEFAULT_LOCALE
    return out


def catalog(hazard_type: str | None = None) -> dict[str, Any]:
    """Every definition (common, or common with the hazard's wording) for a settings / data screen."""
    codes = sorted(set(COMMON) | set(_HAZARDS.get(hazard_type, {})))
    return {"message_version": MESSAGE_VERSION, "concepts": CONCEPTS, "assessment_kinds": ASSESSMENT_KINDS,
            "hazard_type": hazard_type, "reasons": [resolve_reason(c, hazard_type) for c in codes],
            "results": [resolve_result(k, hazard_type) for k in RESULT_KINDS]}
