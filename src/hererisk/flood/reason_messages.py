"""Flood wording for the shared polygon reason catalog (Phase 4-F), and the explanation of a diagnosis.

Registered as hazard type ``flood`` in ``hererisk.common.polygon_reasons`` on import. Only the wording
differs from the common text ("浸水想定区域"); codes, categories, concepts and priorities stay the
common ones. ``explain`` turns a Phase 4-E classification record (``hererisk.flood.adoption``) into
the two layers: user messages and technical details, keeping every reason code and the source
identifiers. It never changes the classification and is not an official answer.

Phase 4-G: the flood wording of the result kinds (``register_hazard_results``) and ``interpret``, one
element of ``diagnostic.interpretations`` of ``GET /api/v1/diagnostics/flood``
(``hererisk.location.flood_diagnostics``). The source's depth class is shown only for a candidate read
as inside, as the source gives it; never computed, never guessed for any other result.
"""

from __future__ import annotations

from typing import Any

from hererisk.common.polygon_reasons import (ASSESSMENT_KINDS, register_hazard_messages, register_hazard_results,
                                             resolve_reasons, resolve_result)

HAZARD_TYPE = "flood"
KIND_OF = {"candidate": "diagnostic_candidate", "undetermined": "undetermined", "rejected": "not_applicable"}


def _f(code, message, detail, **extra):
    return {"code": code, "scope": HAZARD_TYPE, "text": {"ja": {"message": message, "detail": detail}}, **extra}


FLOOD = [
    _f("on_boundary", "浸水想定区域の境界上にあるため、区域内かどうかを確定できません。",
       "現在地が原典の浸水想定区域の境界線上に位置するため、内側または外側として確定していません。"),
    _f("zone_boundary_contact", "浸水想定区域の境界上にあるため、区域内かどうかを確定できません。",
       "地点が原典の浸水想定区域の境界線に接しているため、区域内として確定していません。"),
    _f("pending_geometry_zone", "浸水想定区域のデータの形状に不整合がある範囲のため、区域内かどうかを確定できません。",
       "地点が、形状の検査で不整合が見つかった浸水想定区域の範囲（外接矩形）に入るため、判定を保留しています。"
       "浸水しないことを意味しません。"),
    _f("defect_within_max_radius", "元の区域データの境界に不整合があるため、正確に判定できません。",
       "周辺の輪郭からは浸水想定区域の内外を読めましたが、調べる範囲の中に輪郭の不整合箇所があるため、その読みを確定していません。"),
    _f("defect_within_decision_radius", "判定に必要な範囲で、区域データの形状に不整合が見つかりました。",
       "地点の周辺で判定に使う範囲の中に、浸水想定区域の輪郭が自身と接する・交わる箇所があるため、判定を保留しています。"),
    _f("no_local_boundary", "周辺の境界情報だけでは、浸水想定区域内かどうかを確実に判定できません。",
       "調べる範囲の中に浸水想定区域の境界がなく、周辺の情報だけでは内外を確定できないため、判定を保留しています。"),
    _f("outside_service_region", "この地点は、登録している浸水想定区域データの対象地域の外です。",
       "登録している浸水想定区域データの対象地域（提供範囲）に含まれないため、判定していません。"
       "浸水しないことを意味しません。"),
    _f("flood_response_limit_exceeded", "該当する浸水想定区域が多すぎるため、結果を表示できません。",
       "該当件数が上限を超えたため、一部だけの結果は返していません。",
       category="processing", concept="processing_failure", priority=17),
]
register_hazard_messages(HAZARD_TYPE, FLOOD)


def _r(kind, message, detail):
    return {"kind": kind, "scope": HAZARD_TYPE, "text": {"ja": {"message": message, "detail": detail}}}


FLOOD_RESULTS = [
    _r("candidate_inside", "この浸水深の想定区域に含まれる可能性があります。",
       "元の区域データを独自に解析した結果です。正式な判定ではありません。浸水深は原典の区分をそのまま示しています。"),
    _r("candidate_inside_class_unknown", "この浸水想定区域に含まれる可能性があります。",
       "元の区域データを独自に解析した結果です。正式な判定ではありません。原典の浸水深区分を確認できないため、浸水深は示していません。"),
    _r("candidate_outside", "参考解析では、この想定区域の外側と解釈されました。",
       "元の区域データを独自に解析した結果です。正式な判定ではなく、浸水しないことを意味しません。"
       "ほかの浸水想定区域や、登録していない情報に該当する場合があります。"),
    _r("diagnostic_notice", "HereRiskが元の浸水想定区域データを独自に解析した参考情報です。正式な判定ではありません。",
       "公式データによる判定は official_assessment にあります。参考解析は、正式な検索で判定保留とされた区域だけを対象にしています。"),
]
register_hazard_results(HAZARD_TYPE, FLOOD_RESULTS)


def explain(record: dict[str, Any], locale: str = "ja") -> dict[str, Any]:
    """User and technical layers of one classification record (``adoption.classify`` / ``diagnose``)."""
    kind = KIND_OF[record["classification"]]
    r = resolve_reasons(record["reasons"], HAZARD_TYPE, locale)
    return {
        "assessment_kind": kind, "assessment_label_ja": ASSESSMENT_KINDS[kind]["ja"],
        "user": {"message_ja": r["representative"]["message_ja"] if r["representative"] else None,
                 "certainty": "diagnostic_only"},
        "technical": {"classification": record["classification"], "reasons": r["reasons"], "messages": r["messages"],
                      "hazard_type": HAZARD_TYPE, "source_id": record.get("source_id"),
                      "zone_ref": record.get("zone_ref"), "method": record.get("method"),
                      "adoption_version": record.get("adoption_version"), "relation": record.get("relation"),
                      "depth_class_in_source": record.get("depth_class_in_source"),
                      "official": False, "message_version": r["message_version"]},
    }


def _depth_class(dc: Any) -> dict[str, Any] | None:
    """The source's depth class when it is usable as given (class_code and label present), else None."""
    ok = isinstance(dc, dict) and all(isinstance(dc.get(k), str) and dc[k].strip() for k in ("class_code", "label"))
    return dict(dc) if ok else None


def _text(resolved: dict[str, Any]) -> dict[str, str]:
    """message_<locale> / detail_<locale> of a resolved definition (not message_version)."""
    return {k: v for k, v in resolved.items() if k != "message_version" and k.startswith(("message_", "detail_"))}


def interpret(record: dict[str, Any], locale: str = "ja") -> dict[str, Any]:
    """One diagnostic interpretation for the API (Phase 4-G) from a ``DiagIndex.diagnose`` record."""
    e = explain(record, locale)
    cls, depth = record["classification"], None
    if cls == "candidate" and record.get("relation") == "inside":
        depth = _depth_class(record.get("depth_class_in_source"))
        kind = "candidate_inside" if depth else "candidate_inside_class_unknown"
    elif cls == "candidate" and record.get("relation") == "outside":
        kind = "candidate_outside"
    else:
        kind = cls                                          # undetermined / rejected: the reason explains it
    if kind.startswith("candidate_"):
        message = {"kind": kind, **_text(resolve_result(kind, HAZARD_TYPE, locale))}
    else:
        rep = resolve_reasons(record["reasons"], HAZARD_TYPE, locale)["representative"]
        message = {"code": rep["code"], **_text(rep)}
    return {"source_id": record.get("source_id"), "zone_ref": record.get("zone_ref"),
            "classification": cls, "relation": record.get("relation") if cls == "candidate" else None,
            "interpretation": kind, "assessment_kind": e["assessment_kind"],
            "assessment_label_ja": e["assessment_label_ja"], "certainty": "diagnostic_only", "official": False,
            "depth_class_in_source": depth, "message": message,
            "reasons": e["technical"]["reasons"],
            "reason_messages": [{"code": m["code"], "known": m["known"], **_text(m)} for m in e["technical"]["messages"]],
            "method": record.get("method"), "adoption_version": record.get("adoption_version")}
