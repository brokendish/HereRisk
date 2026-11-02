"""GET /api/v1/location?lat=<latitude>&lon=<longitude> — request validation and the response.

Phase 4-E: with the flood Shadow diagnosis on (``--flood-settings`` with ``diagnosis.shadow_enabled``),
``GET /api/v1/diagnostics/flood-shadow`` (no query) returns its counters (no positions). Without it
that path is ``not_found`` as before.

Phase 4-G: with the diagnostic API on (``diagnosis.api_enabled``), ``GET /api/v1/diagnostics/flood?lat=&lon=``
returns the official flood section and HereRisk's diagnostic interpretation side by side
(``hererisk.location.flood_diagnostics``). The query rules are those of ``/api/v1/location``. Without it
that path is ``not_found``. ``/api/v1/location`` is unchanged either way.

Pure request -> response function (no sockets). Check order: path -> method -> query.
Input rules (docs/api/location-api-v0.1.md section 3): exactly the two parameters ``lat`` and
``lon``, each once, plain decimal numbers, lat -90..90 and lon -180..180. Nothing is clamped,
wrapped or swapped. Invalid input -> 422 ``invalid_input``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import parse_qsl

from hererisk.location.orchestrator import SCHEMA_VERSION, Orchestrator

PATH = "/api/v1/location"
DIAGNOSTICS_PATH = "/api/v1/diagnostics/flood-shadow"
FLOOD_DIAGNOSIS_PATH = "/api/v1/diagnostics/flood"
MAX_QUERY_CHARS = 256
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]{0,2})(?:\.[0-9]{1,15})?\Z")

ERRORS = {
    "invalid_input": (422, "緯度（lat）・経度（lon）を十進数で指定してください。lat は -90〜90、lon は -180〜180 です。"),
    "not_found": (404, "このエンドポイントはありません。"),
    "method_not_allowed": (405, "このメソッドは利用できません。"),
    "internal_error": (500, "処理に失敗しました。"),
}


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body)


class _Rejected(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def parse_point(query: str) -> tuple[float, float]:
    if len(query) > MAX_QUERY_CHARS:
        raise _Rejected("invalid_input")
    try:
        pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise _Rejected("invalid_input") from exc
    names = [k for k, _ in pairs]
    if sorted(names) != ["lat", "lon"]:   # missing, repeated or unknown parameters
        raise _Rejected("invalid_input")
    values = dict(pairs)
    if not all(_NUMBER.match(values[k]) for k in ("lat", "lon")):
        raise _Rejected("invalid_input")   # rejects '', 'nan', 'inf', '1e3', '+1', ' 1', hex ...
    lat, lon = float(values["lat"]), float(values["lon"])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise _Rejected("invalid_input")
    return lat, lon


class LocationApi:
    def __init__(self, orchestrator: Orchestrator, *, diagnostics: Callable[[], dict[str, Any]] | None = None,
                 flood_diagnosis: Callable[[float, float], dict[str, Any]] | None = None) -> None:
        self._orchestrator = orchestrator
        self._diagnostics = diagnostics
        self._flood_diagnosis = flood_diagnosis

    def handle(self, method: str, path: str, query: str) -> Response:
        try:
            if self._diagnostics is not None and path == DIAGNOSTICS_PATH:
                if method != "GET":
                    raise _Rejected("method_not_allowed")
                if query:
                    raise _Rejected("invalid_input")
                return _json(200, {"schema_version": SCHEMA_VERSION, "flood_shadow": self._diagnostics()})
            if self._flood_diagnosis is not None and path == FLOOD_DIAGNOSIS_PATH:
                if method != "GET":
                    raise _Rejected("method_not_allowed")
                lat, lon = parse_point(query)
                return _json(200, self._flood_diagnosis(lat, lon))
            if path != PATH:
                raise _Rejected("not_found")
            if method != "GET":
                raise _Rejected("method_not_allowed")
            lat, lon = parse_point(query)
            return _json(200, self._orchestrator.locate(lat, lon))
        except _Rejected as rejected:
            return _error(rejected.code)
        except Exception:  # noqa: BLE001 - never leak details
            return _error("internal_error")


def _error(code: str) -> Response:
    status, message = ERRORS[code]
    extra = {"Allow": "GET"} if code == "method_not_allowed" else {}
    return _json(status, {"schema_version": SCHEMA_VERSION, "error": {"code": code, "message": message}}, extra)


def _json(status: int, doc: Any, extra: dict[str, str] | None = None) -> Response:
    body = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", **(extra or {})}
    return Response(status, headers, body)
