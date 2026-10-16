"""Acquisition Record and commit marker (contract sections 5 and 6).

Records are append-only: written once under a new name, never replaced.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from hererisk.common.config import validate_with_schema

RECORD_SCHEMA_VERSION = "0.1"
MARKER_SCHEMA_VERSION = "0.1"

_UUID = {"type": "string", "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"}
_SHA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_STR = {"type": "string", "minLength": 1}
_HTTPS = {"type": "string", "pattern": "^https://[^\\s@?#]+$"}
_REL = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._/-]*$", "not": {"pattern": "\\.\\."}}


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(props),
        "properties": props,
    }


RECORD_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    **_obj(
        {
            "record_schema_version": {"const": RECORD_SCHEMA_VERSION},
            "acquisition_id": _UUID,
            "run_id": _UUID,
            "api_id": {"const": "elevation"},
            "provider": _obj({"id": _STR, "name": _STR}),
            "data_name": _STR,
            "data_type": {"const": "elevation_png"},
            "requested_url": _HTTPS,
            "effective_url": _HTTPS,
            "official_page_url": _HTTPS,
            "acquired_at": {
                "type": "string",
                "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$",
            },
            "management_prefectures": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"type": "string", "pattern": "^(0[1-9]|[1-3][0-9]|4[0-7])$"},
            },
            "tile": _obj(
                {
                    "z": {"type": "integer", "minimum": 0},
                    "x": {"type": "integer", "minimum": 0},
                    "y": {"type": "integer", "minimum": 0},
                }
            ),
            "size_bytes": {"type": "integer", "minimum": 1},
            "sha256": _SHA,
            "source_definition": _obj(
                {
                    "schema_version": _STR,
                    "definition_revision": _STR,
                    "source_ref": _STR,
                    "raw_sha256": _SHA,
                }
            ),
            "effective_configuration": _obj({"snapshot_ref": _REL, "sha256": _SHA}),
            "pipeline": _obj({"id": _STR, "version": _STR}),
            "original_version": {"type": ["string", "null"], "minLength": 1},
            "data_reference_date": {
                "type": ["string", "null"],
                "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}$",
            },
            "source_metadata_evidence": {"oneOf": [{"type": "null"}, _HTTPS]},
            "usage_snapshot": _obj(
                {
                    "terms_url": _HTTPS,
                    "attribution_text": _STR,
                    "review_ref": _STR,
                    "approval_ref": _STR,
                }
            ),
        }
    ),
    # source_metadata_evidence is required when any provider metadata is known.
    "if": {
        "anyOf": [
            {"properties": {"original_version": {"type": "string"}}},
            {"properties": {"data_reference_date": {"type": "string"}}},
        ]
    },
    "then": {"properties": {"source_metadata_evidence": _HTTPS}},
}

MARKER_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    **_obj(
        {
            "schema_version": {"const": MARKER_SCHEMA_VERSION},
            "acquisition_id": _UUID,
            "record_ref": _REL,
            "record_sha256": _SHA,
            "artifact_ref": _REL,
            "artifact_sha256": _SHA,
        }
    ),
}


def to_bytes(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def validate_record(record: Mapping[str, Any]) -> None:
    validate_with_schema(record, RECORD_SCHEMA)


def validate_marker(marker: Mapping[str, Any]) -> None:
    validate_with_schema(marker, MARKER_SCHEMA)
