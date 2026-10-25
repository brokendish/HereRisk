"""ElevationProvider: the Location API ``elevation`` section from the existing Elevation API.

Calls ``POST /api/v1/elevation`` (docs/api/elevation-contract-v0.1.md) on 127.0.0.1 only, with
``{"lat": .., "lon": ..}`` and, if configured, a Bearer token read once from a 0600 file outside
Git. The token is never logged, echoed or put into a section.

Status mapping (docs/api/location-api-v0.1.md section 8.1):

    success          -> available     (result.elevation_m kept as is; 0 and negative are values)
    no_data          -> not_available (reason: the Elevation API error code, e.g. no_coverage)
    indeterminate    -> unknown       (reason: the Elevation API error code)
    retrieval_failed -> error         (upstream_retrieval_failed)
    invalid_request  -> error         (upstream_rejected; e.g. a token mismatch)

Anything else (unknown status, broken JSON, a non-numeric value, a location that is not the one
asked for, missing dataset fields) becomes ``error`` / ``invalid_provider_result``; it is never
turned into an elevation value.
"""

from __future__ import annotations

import http.client
import json
import math
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from hererisk.common.api_auth import TokenFileError, read_token_file
from hererisk.common.storage import is_within
from hererisk.location.model import AVAILABLE, NOT_AVAILABLE, UNKNOWN, error_section

ELEVATION_PATH = "/api/v1/elevation"
ALLOWED_HOST = "127.0.0.1"
MAX_RESPONSE_BYTES = 64 * 1024
DEFAULT_TIMEOUT_S = 1.5
REPO_ROOT = Path(__file__).resolve().parents[3]


class ElevationConfigError(ValueError):
    """Fixed messages only (never a path or a token)."""


def _is_number(v: Any) -> bool:
    return type(v) in (int, float) and math.isfinite(v)


class ElevationProvider:
    id = "elevation-api"

    def __init__(self, base_url: str, *, token_file: Path | None = None, fixture: bool = False,
                 timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        parts = urlsplit(base_url)
        if parts.scheme != "http" or parts.hostname != ALLOWED_HOST or parts.port is None \
                or parts.path not in ("", "/") or parts.query or parts.username or parts.password:
            raise ElevationConfigError("the Elevation API must be http://127.0.0.1:<port>")
        self._port = parts.port
        self._timeout_s = timeout_s
        self._fixture = fixture
        self._auth = None
        if token_file is not None:
            if is_within(Path(token_file), REPO_ROOT):
                raise ElevationConfigError("the token file must be outside the repository")
            try:
                self._auth = "Bearer " + read_token_file(Path(token_file))[0]
            except TokenFileError as exc:
                raise ElevationConfigError("token file rejected") from exc

    def lookup(self, lat: float, lon: float) -> dict[str, Any]:
        try:
            status, raw = self._post(lat, lon)
        except TimeoutError:
            return error_section(self.id, "timeout")
        except (OSError, http.client.HTTPException):
            return error_section(self.id, "upstream_unreachable")
        return self._map(status, raw, lat, lon)

    def _post(self, lat: float, lon: float) -> tuple[int, bytes]:
        body = json.dumps({"lat": lat, "lon": lon}).encode()
        headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
        if self._auth:
            headers["Authorization"] = self._auth
        conn = http.client.HTTPConnection(ALLOWED_HOST, self._port, timeout=self._timeout_s)
        try:
            conn.request("POST", ELEVATION_PATH, body=body, headers=headers)
            resp = conn.getresponse()
            return resp.status, resp.read(MAX_RESPONSE_BYTES + 1)
        finally:
            conn.close()

    def _map(self, http_status: int, raw: bytes, lat: float, lon: float) -> dict[str, Any]:
        if len(raw) > MAX_RESPONSE_BYTES:
            return error_section(self.id, "invalid_provider_result")
        try:
            doc = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return error_section(self.id, "invalid_provider_result")
        if not isinstance(doc, dict) or doc.get("hazard") != "elevation":
            return error_section(self.id, "invalid_provider_result")
        status = doc.get("status")
        if status == "invalid_request":
            return error_section(self.id, "upstream_rejected")
        if doc.get("location") != {"lat": lat, "lon": lon}:
            return error_section(self.id, "invalid_provider_result")
        code = (doc.get("error") or {}).get("code") if isinstance(doc.get("error"), dict) else None
        dataset = doc.get("dataset")
        source = _source(dataset) if dataset is not None else None
        synthetic = self._fixture or (source is not None and str(source["source_id"]).startswith("fixture"))
        base = {"provider": self.id, "synthetic": synthetic}
        if source is not None:
            base["source"] = source
        if status == "success":
            result = doc.get("result")
            value = result.get("elevation_m") if isinstance(result, dict) else None
            if http_status != 200 or not _is_number(value) or source is None:
                return error_section(self.id, "invalid_provider_result")
            return {**base, "status": AVAILABLE, "result": {"elevation_m": value, "unit": "m"}}
        if status in ("no_data", "indeterminate"):
            if doc.get("result") is not None or not isinstance(code, str):
                return error_section(self.id, "invalid_provider_result")
            return {**base, "status": NOT_AVAILABLE if status == "no_data" else UNKNOWN,
                    "result": None, "reason": code}
        if status == "retrieval_failed":
            return error_section(self.id, "upstream_retrieval_failed")
        return error_section(self.id, "invalid_provider_result")


def _source(dataset: Any) -> dict[str, Any] | None:
    """Elevation API ``dataset`` -> Location ``source``; only fields the Elevation API publishes."""
    try:
        out = {"source_id": dataset["id"], "organization": dataset["source"]["provider"],
               "data_version": dataset["publication_version"], "published_at": dataset["published_at"],
               "attribution": {"text": dataset["attribution"]["text"], "license": dataset["attribution"]["license"]}}
    except (KeyError, TypeError):
        return None
    if not all(isinstance(v, str) and v for v in (out["source_id"], out["organization"], out["data_version"],
                                                  out["attribution"]["text"], out["attribution"]["license"])):
        return None
    for key, value in (("page_url", dataset["source"].get("page_url")), ("data_reference_date", dataset.get("data_reference_date"))):
        if isinstance(value, str) and value:
            out[key] = value
    if isinstance(dataset["attribution"].get("url"), str):
        out["attribution"]["url"] = dataset["attribution"]["url"]
    return out
