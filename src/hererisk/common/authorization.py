"""Execution authorization, with production and fixture contexts kept apart.

Production: :class:`ProductionAuthorizer` denies by default. It grants an
operation only when an administrator-managed approval store (outside the
repository, see :mod:`hererisk.common.approval_store`) holds exactly one
valid, unrevoked, unexpired record that explicitly lists that operation and
matches the API, source, regions, tiles and the exact Source Definition bytes.
Without an approval root it always returns APPROVAL_REQUIRED.

Fixture: :class:`FixtureAuthorizer` reads a fixture-only authorization file that
binds ``(api_id, operation, source_ref, regions)`` to the exact SHA-256 of the
fixture Source Definition bytes. Each operation has its own file next to the
download one (``download.json``, ``normalize.json``, ``validate.json``) and the
document's ``operation`` must equal the requested operation, so a download
grant is never read as permission for a later stage. Every identifier must carry the ``fixture-``
prefix, so a fixture approval can never be presented as a production approval,
and a changed definition invalidates the fixture approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlsplit

from hererisk.common.approval_store import ApprovalStoreError, load_store
from hererisk.common.config import (
    ConfigSnapshot,
    ConfigurationError,
    freeze,
    load_validated_json,
)
from hererisk.common.result import PipelineError

FIXTURE_PREFIX = "fixture-"
OPERATIONS = ("download", "normalize", "validate", "publish")


class ExecutionContext(str, Enum):
    PRODUCTION = "production"
    FIXTURE = "fixture"


@dataclass(frozen=True)
class Authorization:
    authorization_ref: str
    context: ExecutionContext
    api_id: str
    operation: str
    source_ref: str
    region_codes: tuple[str, ...]
    policy: Mapping[str, Any]


class Authorizer(Protocol):
    context: ExecutionContext

    def authorize(
        self,
        *,
        api_id: str,
        operation: str,
        source_ref: str,
        region_codes: tuple[str, ...],
        definition: ConfigSnapshot,
    ) -> Authorization: ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProductionAuthorizer:
    """Deny by default; grant only what an explicit approval record lists.

    Checks, in order (any failure -> APPROVAL_REQUIRED, before any network
    access or write, since the Orchestrator authorizes every stage first):

    1. an approval root was configured and the whole store verifies
       (trust boundary, schema, digest; see ``approval_store``);
    2. exactly one record matches api_id, source_ref, the operation (listed
       explicitly), every requested region (subset, never widened) and the
       exact Source Definition bytes (``definition.raw_sha256``); the Source
       Definition's ``approval_ref`` must name that record;
    3. the record is not revoked and ``valid_from <= now < expires_at``;
    4. download: the definition's tiles are a subset of the approved tiles
       and within ``max_tiles_per_run``; the URL template is HTTPS on the
       approved host;
    5. publish: publication terms and an ``approved`` publication eligibility
       are present and the attribution text equals the Source Definition's.
    """

    context = ExecutionContext.PRODUCTION

    def __init__(self, approval_root: Path | None = None, *,
                 protected_roots: tuple[Path, ...] = (),
                 clock: Callable[[], datetime] = _utc_now) -> None:
        self._root = approval_root
        self._protected = tuple(protected_roots)
        self._clock = clock

    def authorize(
        self,
        *,
        api_id: str,
        operation: str,
        source_ref: str,
        region_codes: tuple[str, ...],
        definition: ConfigSnapshot,
    ) -> Authorization:
        if self._root is None:
            raise PipelineError("APPROVAL_REQUIRED", "no production approval store configured")
        if operation not in OPERATIONS:
            raise PipelineError("APPROVAL_REQUIRED", "unknown operation")
        try:
            store = load_store(Path(self._root), protected_roots=self._protected)
        except ApprovalStoreError as exc:
            raise PipelineError("APPROVAL_REQUIRED", f"approval store rejected: {exc}") from exc
        try:
            source = definition.data["sources"][source_ref]
        except KeyError as exc:
            raise PipelineError("APPROVAL_REQUIRED", "source not defined") from exc
        matches = [r for r in store.records
                   if r["api_id"] == api_id and r["source_ref"] == source_ref
                   and operation in r["operations"]
                   and set(region_codes) <= set(r["region_codes"])
                   and r["definition"]["raw_sha256"] == definition.raw_sha256]
        if not matches:
            raise PipelineError("APPROVAL_REQUIRED", "no matching production approval")
        if len(matches) != 1:
            raise PipelineError("APPROVAL_REQUIRED", "ambiguous production approvals")
        record = matches[0]
        if source.get("approval_ref") != record["approval_id"]:
            raise PipelineError("APPROVAL_REQUIRED", "source definition names another approval")
        if record["approval_id"] in store.revoked:
            raise PipelineError("APPROVAL_REQUIRED", "production approval revoked")
        now = self._clock().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not record["valid_from"] <= now < record["expires_at"]:
            raise PipelineError("APPROVAL_REQUIRED", "production approval not in force")
        if operation == "download":
            policy = self._download_policy(record, source)
        elif operation == "publish":
            policy = self._publication_terms(record, source)
        else:
            policy = {}
        return Authorization(
            authorization_ref=record["approval_id"],
            context=self.context,
            api_id=api_id,
            operation=operation,
            source_ref=source_ref,
            region_codes=tuple(region_codes),
            policy=freeze(policy),
        )

    @staticmethod
    def _download_policy(record: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
        limits = record["acquisition"]
        acquisition = source.get("acquisition") or {}
        tiles = acquisition.get("tiles") or []
        approved = {(t["z"], t["x"], t["y"]) for t in record["tiles"]}
        requested = {(acquisition.get("zoom"), t.get("x"), t.get("y")) for t in tiles}
        if not tiles or not requested <= approved:
            raise PipelineError("APPROVAL_REQUIRED", "tiles not approved")
        if len(tiles) > limits["max_tiles_per_run"]:
            raise PipelineError("APPROVAL_REQUIRED", "more tiles than approved per run")
        url = urlsplit(str(acquisition.get("url_template", "")))
        if url.scheme != "https" or url.hostname != limits["allowed_host"] or url.port:
            raise PipelineError("APPROVAL_REQUIRED", "acquisition host not approved")
        return {
            "policy_id": record["approval_id"],
            "version": record["definition"]["revision"],
            "max_tile_bytes": limits["max_tile_bytes"],
            "max_tiles_per_request": limits["max_tiles_per_run"],
            "max_pending_acquisitions": limits["max_pending_acquisitions"],
        }

    @staticmethod
    def _publication_terms(record: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
        publication = record["publication"]
        if (source.get("usage") or {}).get("attribution_text") != publication["attribution_text"]:
            raise PipelineError("APPROVAL_REQUIRED", "attribution text differs from approval")
        return {"license": publication["license"],
                "attribution_url": publication["attribution_url"]}


_FIXTURE_ID = {"type": "string", "pattern": "^fixture-[a-z0-9-]+$"}

FIXTURE_AUTHORIZATION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "authorization_ref",
        "execution_context",
        "api_id",
        "operation",
        "grants",
    ],
    # The acquisition safety policy belongs to download grants only; publication
    # terms (licence / attribution URL) to publish grants only.
    "allOf": [
        {"if": {"properties": {"operation": {"const": "download"}}},
         "then": {"required": ["policy"]}, "else": {"not": {"required": ["policy"]}}},
        {"if": {"properties": {"operation": {"const": "publish"}}},
         "then": {"required": ["publication"]}, "else": {"not": {"required": ["publication"]}}},
    ],
    "properties": {
        "authorization_ref": _FIXTURE_ID,
        "execution_context": {"const": "fixture"},
        "api_id": {"type": "string", "pattern": "^[a-z][a-z0-9-]*$"},
        "operation": {"enum": list(OPERATIONS)},
        "grants": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["source_ref", "region_codes", "definition_raw_sha256"],
                "properties": {
                    "source_ref": _FIXTURE_ID,
                    "region_codes": {
                        "type": "array",
                        "minItems": 1,
                        "uniqueItems": True,
                        "items": {"type": "string", "pattern": "^(0[1-9]|[1-3][0-9]|4[0-7])$"},
                    },
                    "definition_raw_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                },
            },
        },
        "publication": {
            "type": "object",
            "additionalProperties": False,
            "required": ["license", "attribution_url"],
            "properties": {
                "license": {"type": "string", "minLength": 1},
                "attribution_url": {"type": "string", "pattern": "^https://[^\\s?#@]+$"},
            },
        },
        "policy": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "policy_id",
                "version",
                "max_tile_bytes",
                "max_tiles_per_request",
                "max_pending_acquisitions",
            ],
            "properties": {
                "policy_id": _FIXTURE_ID,
                "version": {"type": "string", "minLength": 1},
                "max_tile_bytes": {"type": "integer", "minimum": 1, "maximum": 16777216},
                "max_tiles_per_request": {"type": "integer", "minimum": 1},
                # Uncommitted acquisitions (.part) tolerated in the data root
                # before new runs are BLOCKED; bounds disk use without deleting.
                "max_pending_acquisitions": {"type": "integer", "minimum": 1},
            },
        },
    },
}


class FixtureAuthorizer:
    """Authorize fixture runs only, from a fixture authorization file."""

    context = ExecutionContext.FIXTURE

    def __init__(self, authorization_path: Path, production_definition_root: Path) -> None:
        self._path = Path(authorization_path)
        self._production_root = Path(production_definition_root).resolve()

    def authorize(
        self,
        *,
        api_id: str,
        operation: str,
        source_ref: str,
        region_codes: tuple[str, ...],
        definition: ConfigSnapshot,
    ) -> Authorization:
        if operation not in OPERATIONS:
            raise PipelineError("APPROVAL_REQUIRED", "unknown operation")
        path = self._path.with_name(f"{operation}.json")
        try:
            _, doc = load_validated_json(path, FIXTURE_AUTHORIZATION_SCHEMA)
        except ConfigurationError as exc:
            raise PipelineError("APPROVAL_REQUIRED", "fixture authorization invalid") from exc
        if path.resolve().is_relative_to(self._production_root / "api"):
            raise PipelineError("APPROVAL_REQUIRED", "fixture authorization in production conf")
        if doc["api_id"] != api_id or doc["operation"] != operation:
            raise PipelineError("APPROVAL_REQUIRED", "api/operation not granted")

        source = definition.data["sources"][source_ref]
        if not str(source["approval_ref"]).startswith(FIXTURE_PREFIX) or not str(
            source["usage"]["review_ref"]
        ).startswith(FIXTURE_PREFIX):
            raise PipelineError("APPROVAL_REQUIRED", "non-fixture approval in fixture run")

        for grant in doc["grants"]:
            if (
                grant["source_ref"] == source_ref
                and set(region_codes) <= set(grant["region_codes"])
                and grant["definition_raw_sha256"] == definition.raw_sha256
            ):
                return Authorization(
                    authorization_ref=doc["authorization_ref"],
                    context=self.context,
                    api_id=api_id,
                    operation=operation,
                    source_ref=source_ref,
                    region_codes=region_codes,
                    policy=freeze(doc.get("policy") or doc.get("publication") or {}),
                )
        raise PipelineError("APPROVAL_REQUIRED", "no matching fixture grant")
