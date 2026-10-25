"""Section states and the shape check applied to every provider answer.

A provider returns one section (a dict). ``check_section`` makes sure the section is one of the
contract shapes; anything else becomes an ``error`` section, so a broken provider can never be
shown as a result. States (docs/api/location-api-v0.1.md section 4):

* available     - data with usage rights matched the point
* no_match      - the data was searched and no feature matched (NOT a statement of safety)
* unknown       - the result cannot be determined with the available information
* not_available - the data / provider is not connected or not usable
* error         - the call or the processing failed
"""

from __future__ import annotations

import math
from typing import Any, Mapping

AVAILABLE, NO_MATCH, UNKNOWN, NOT_AVAILABLE, ERROR = "available", "no_match", "unknown", "not_available", "error"
STATES = (AVAILABLE, NO_MATCH, UNKNOWN, NOT_AVAILABLE, ERROR)

HAZARDS = ("flood", "tsunami", "storm_surge", "landslide")

NOTICES = {
    AVAILABLE: "公式データの情報があります。分類は原典の表記のままです。",
    NO_MATCH: "検索したデータの区域に含まれませんでした。安全であることを意味しません。",
    UNKNOWN: "判定に必要な情報が不足しているため、結果を確定できません。",
    NOT_AVAILABLE: "このデータはまだ利用できません。安全・危険のどちらも示しません。",
    ERROR: "情報を取得できませんでした。安全・危険のどちらも示しません。",
}

# Public error messages; internal exception text is never copied into a response.
ERROR_MESSAGES = {
    "provider_failed": "情報の取得処理に失敗しました。",
    "timeout": "情報の取得が時間内に終わりませんでした。",
    "invalid_provider_result": "取得した情報の形式を確認できませんでした。",
    "synthetic_not_allowed": "この環境では合成データを返せません。",
    "upstream_unreachable": "接続先のAPIに接続できませんでした。",
    "upstream_rejected": "接続先のAPIが要求を受け付けませんでした。",
    "upstream_retrieval_failed": "接続先のAPIがデータを取得できませんでした。",
}


def error_section(provider: str, code: str) -> dict[str, Any]:
    return {"status": ERROR, "provider": provider, "synthetic": False,
            "error": {"code": code, "message": ERROR_MESSAGES[code]}, "notice": NOTICES[ERROR]}


def not_available_section(provider: str) -> dict[str, Any]:
    return {"status": NOT_AVAILABLE, "provider": provider, "synthetic": False, "notice": NOTICES[NOT_AVAILABLE]}


def _is_number(value: Any) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _valid(kind: str, s: Mapping[str, Any]) -> bool:
    status = s.get("status")
    if status not in STATES or not isinstance(s.get("provider"), str) or type(s.get("synthetic")) is not bool:
        return False
    if status == ERROR:
        return isinstance(s.get("error"), Mapping)
    if kind == "address":
        result = s.get("result")
        if status == AVAILABLE:
            return isinstance(result, Mapping) and isinstance(result.get("display_name"), str) \
                and result.get("is_confirmed_address") in (True, False)
        return result is None
    if kind == "elevation":
        result = s.get("result")
        if status == AVAILABLE:
            return isinstance(result, Mapping) and _is_number(result.get("elevation_m")) and result.get("unit") == "m"
        return result is None or (isinstance(result, Mapping) and result.get("elevation_m") is None)
    results = s.get("results")
    if status == AVAILABLE:
        return isinstance(results, list) and len(results) > 0 and all(isinstance(r, Mapping) and isinstance(r.get("source"), Mapping) for r in results)
    if status == NO_MATCH:   # an explicit empty list, plus which data was searched
        return results == [] and isinstance(s.get("searched_sources"), list) and len(s["searched_sources"]) > 0
    return results is None   # unknown / not_available never look like an empty result list


def check_section(kind: str, provider: str, section: Any, *, allow_synthetic: bool) -> dict[str, Any]:
    """Return the section if it has a contract shape, else an ``error`` section."""
    if not isinstance(section, Mapping) or not _valid(kind, section):
        return error_section(provider, "invalid_provider_result")
    if section["synthetic"] and not allow_synthetic:
        return error_section(provider, "synthetic_not_allowed")
    out = dict(section)
    out["notice"] = ("【合成データ】" if out["synthetic"] else "") + NOTICES[out["status"]]
    return out
