"""Execution authorization, with production and fixture contexts kept apart.

Production: the approval store / verification method is UNDECIDED in the
contracts, so :class:`ProductionAuthorizer` always returns APPROVAL_REQUIRED.
No production acquisition can be authorized by this code.

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
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol

from hererisk.common.config import (
    ConfigSnapshot,
    ConfigurationError,
    freeze,
    load_validated_json,
)
from hererisk.common.result import PipelineError

FIXTURE_PREFIX = "fixture-"
OPERATIONS = ("download", "normalize", "validate")


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


class ProductionAuthorizer:
    """No production approval mechanism exists yet: always BLOCKED."""

    context = ExecutionContext.PRODUCTION

    def authorize(self, **_: Any) -> Authorization:
        raise PipelineError("APPROVAL_REQUIRED", "production approval store not implemented")


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
    # The acquisition safety policy belongs to download grants only.
    "if": {"properties": {"operation": {"const": "download"}}},
    "then": {"required": ["policy"]},
    "else": {"not": {"required": ["policy"]}},
    "properties": {
        "authorization_ref": _FIXTURE_ID,
        "execution_context": {"const": "fixture"},
        "api_id": {"type": "string", "pattern": "^[a-z][a-z0-9-]*$"},
        "operation": {"enum": ["download", "normalize", "validate"]},
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
                    policy=freeze(doc.get("policy", {})),
                )
        raise PipelineError("APPROVAL_REQUIRED", "no matching fixture grant")
