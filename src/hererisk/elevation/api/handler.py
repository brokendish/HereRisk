"""POST /api/v1/elevation — request validation, evaluation and the 7-key response.

Pure request -> response function (no sockets) following
docs/api/elevation-contract-v0.1.md sections 3-5: the check order is
path -> method -> Content-Type / Encoding -> body size -> query -> JSON syntax /
duplicates -> keys / types / values -> selection -> entity integrity ->
read / quality -> no-data or value. The first failure ends processing.

Nothing about the request position is logged: logs carry a server-generated
request_id, the public status / error code and the duration only.

With a ``BearerAuth`` (Phase 1-G; required for the private_experiment API),
authentication is checked FIRST - before path, method, body, selection or any
read of published data - and a failure ends with 401 ``unauthorized``. Neither
the token nor the Authorization header is ever logged or echoed.
"""

from __future__ import annotations

import json
import math
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from hererisk.common.api_auth import BearerAuth
from hererisk.common.config import ConfigurationError, parse_strict_json
from hererisk.common.logging import StructuredLogger
from hererisk.elevation.api.published import PublishedDataset, PublishedSet, public_dataset
from hererisk.elevation.lookup.core import locate_pixel, lookup_elevation
from hererisk.elevation.publish.registry import RegistryError
from hererisk.elevation.validate.core import CandidateRejected, validate_candidate

PATH = "/api/v1/elevation"

# (HTTP status, status, error.code, message) — elevation contract section 5.
ERRORS: dict[str, tuple[int, str, str]] = {
    "no_coverage": (200, "no_data", "この地点を評価できる公開データがありません。"),
    "elevation_nodata": (200, "no_data", "この地点の標高データはありません。"),
    "data_unavailable": (503, "retrieval_failed", "標高データを取得できませんでした。"),
    "published_data_missing": (500, "indeterminate", "公開データの整合性を確認できません。"),
    "dataset_integrity_error": (500, "indeterminate", "公開データの整合性を確認できません。"),
    "data_quality_error": (500, "indeterminate", "標高データの品質を確認できません。"),
    "ambiguous_dataset": (500, "indeterminate", "標高データを一意に選択できません。"),
    "invalid_input": (400, "invalid_request", "緯度・経度を含むリクエストが不正です。"),
    "request_too_large": (413, "invalid_request", "リクエストが大きすぎます。"),
    "method_not_allowed": (405, "invalid_request", "このメソッドは利用できません。"),
    "unsupported_media_type": (415, "invalid_request", "この形式のリクエストは利用できません。"),
    "not_found": (404, "invalid_request", "このエンドポイントはありません。"),  # P4
    "unauthorized": (401, "invalid_request", "認証が必要です。"),  # Bearer token (Phase 1-G)
    "internal_error": (500, "retrieval_failed", "標高取得処理に失敗しました。"),
}


@dataclass(frozen=True)
class Settings:
    request_body_max_bytes: int
    evaluation_timeout_ms: int


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> dict[str, Any]:
        return json.loads(self.body)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ms(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{moment.microsecond // 1000:03d}Z"


class _Rejected(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ElevationApi:
    def __init__(self, published: PublishedSet, settings: Settings, logger: StructuredLogger,
                 *, clock: Callable[[], datetime] = _now,
                 monotonic: Callable[[], float] = time.monotonic,
                 auth: BearerAuth | None = None) -> None:
        self._auth = auth
        self._published = published
        self._settings = settings
        self._logger = logger.bind(module="elevation-api", api_id="elevation", run_id=None)
        self._clock = clock
        self._monotonic = monotonic

    # -- entry -------------------------------------------------------------------------
    def authenticated(self, headers: Mapping[str, str]) -> bool:
        """True if no authentication is configured or the credential is valid."""
        return self._auth is None or self._auth.check(headers)

    def handle(self, method: str, path: str, query: str, headers: Mapping[str, str],
               body: bytes) -> Response:
        started = self._monotonic()
        log = self._logger.bind(request_id=uuid.uuid4().hex)
        location = None
        try:
            if not self.authenticated(headers):
                raise _Rejected("unauthorized")
            lat, lon = self._accept(method, path, query, headers, body)
        except _Rejected as rejected:
            return self._respond(log, rejected.code, location=None, dataset=None,
                                 evaluated=False)
        except Exception:  # noqa: BLE001 - never leak details
            return self._respond(log, "internal_error", location=None, dataset=None,
                                 evaluated=False)
        location = {"lat": lat, "lon": lon}
        try:
            return self._evaluate(log, location, lat, lon, started)
        except Exception:  # noqa: BLE001
            return self._respond(log, "internal_error", location=location, dataset=None,
                                 evaluated=True)

    # -- input -----------------------------------------------------------------------------
    def _accept(self, method: str, path: str, query: str, headers: Mapping[str, str],
                body: bytes) -> tuple[float, float]:
        lower = {k.lower(): v for k, v in headers.items()}
        if path != PATH:
            raise _Rejected("not_found")
        if method != "POST":
            raise _Rejected("method_not_allowed")
        media, _, params = (lower.get("content-type") or "").partition(";")
        if media.strip().lower() != "application/json":
            raise _Rejected("unsupported_media_type")
        for param in filter(None, (p.strip() for p in params.split(";"))):
            name, _, value = param.partition("=")
            if name.strip().lower() != "charset" or value.strip().strip('"').lower() != "utf-8":
                raise _Rejected("unsupported_media_type")
        if (lower.get("content-encoding") or "identity").strip().lower() != "identity":
            raise _Rejected("unsupported_media_type")
        if len(body) > self._settings.request_body_max_bytes:
            raise _Rejected("request_too_large")
        if query:
            raise _Rejected("invalid_input")
        try:
            doc = parse_strict_json(body)  # UTF-8, no BOM, duplicate keys / NaN rejected
        except ConfigurationError as exc:
            raise _Rejected("invalid_input") from exc
        if not isinstance(doc, dict) or set(doc) != {"lat", "lon"}:
            raise _Rejected("invalid_input")
        lat, lon = doc["lat"], doc["lon"]
        for value in (lat, lon):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise _Rejected("invalid_input")  # bool, str, null, 1e309 (inf) ...
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise _Rejected("invalid_input")  # never clamped / wrapped / swapped
        return lat, lon

    # -- evaluation ------------------------------------------------------------------------
    def _evaluate(self, log, location, lat: float, lon: float, started: float) -> Response:
        candidates = self._published.covering(lat, lon)
        if not candidates:
            return self._respond(log, "no_coverage", location=location, dataset=None)
        if len(candidates) > 1:
            return self._respond(log, "ambiguous_dataset", location=location, dataset=None)
        published: PublishedDataset = candidates[0]
        public = public_dataset(published.dataset)
        try:
            data = self._published.read_entity(published)
        except RegistryError as exc:
            if exc.kind == "missing":
                return self._respond(log, "published_data_missing", location=location, dataset=None)
            if exc.kind == "integrity":
                return self._respond(log, "dataset_integrity_error", location=location, dataset=None)
            return self._respond(log, "data_unavailable", location=location, dataset=public)
        z, x, y = published.tile
        try:
            candidate = parse_strict_json(data)
            validate_candidate(candidate, expected_tile={"z": z, "x": x, "y": y})
            value = lookup_elevation(candidate, locate_pixel(lat, lon, z))
        except (ConfigurationError, CandidateRejected, ValueError) as exc:  # noqa: F841
            return self._respond(log, "data_quality_error", location=location, dataset=public)
        if (self._monotonic() - started) * 1000 > self._settings.evaluation_timeout_ms:
            return self._respond(log, "data_unavailable", location=location, dataset=public)
        if value is None:
            return self._respond(log, "elevation_nodata", location=location, dataset=public)
        return self._respond(log, None, location=location, dataset=public,
                             result={"elevation_m": value / 100})

    # -- output ----------------------------------------------------------------------------
    def _respond(self, log, code: str | None, *, location, dataset, result=None,
                 evaluated: bool = True) -> Response:
        if code is None:
            http, status, error = 200, "success", None
        else:
            http, status, message = ERRORS[code]
            error = {"code": code, "message": message}
        document = {
            "hazard": "elevation",
            "location": location,
            "status": status,
            "result": result if code is None else None,
            "dataset": dataset,
            "error": error,
            "evaluated_at": _ms(self._clock()) if evaluated and location is not None else None,
        }
        headers = {"Content-Type": "application/json", "Cache-Control": "no-store"}
        if code == "method_not_allowed":
            headers["Allow"] = "POST"
        if code == "unauthorized":
            headers["WWW-Authenticate"] = "Bearer"
        level = "INFO" if status in ("success", "no_data") else (
            "WARNING" if status == "invalid_request" else "ERROR")
        log.log(level, f"request {status}", error_code=code)
        body = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return Response(http, headers, body)
