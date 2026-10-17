"""Production approval store: administrator-managed approval records (Phase 1-F).

The store is a directory OUTSIDE the repository, created and maintained by an
administrator (docs/operations/elevation-production-runbook-v0.1.md)::

    <approval_root>/
      revocations.json            required (may list no revocation)
      approvals/<approval_id>.json

Trust boundary (decided on what is actually opened, never on path strings):

* the root is opened from ``/`` without following any symlink; the root and
  ``approvals/`` must be directories owned by the running user or root, and
  not writable by group / others;
* every record is a regular, single-link file with the same owner rule and
  no group / other write permission, at most ``MAX_RECORD_BYTES``;
* the root must not lie inside the repository (configuration / schema roots)
  and must not carry the fixture data-root marker, so committed files, fixture
  trees and fixture roots can never act as a production approval store;
* any unreadable, malformed or self-inconsistent record (``record_sha256``)
  makes the whole store unusable (fail closed).

``record_sha256`` detects accidental or partial edits; it is not a signature.
Authenticity rests on the file ownership / permission rules above and on the
administrator procedure (registration, audit). Nothing in this code creates,
completes or "fixes" an approval record.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from hererisk.common.config import ConfigurationError, parse_strict_json, validate_with_schema
from hererisk.common.storage import (
    FIXTURE_ROOT_MARKER,
    StorageError,
    _chain_within,
    _open_dir_chain,
)

RECORD_SCHEMA_ID = "hererisk-production-approval-v0.1"
REVOCATIONS_SCHEMA_ID = "hererisk-approval-revocations-v0.1"
REVOCATIONS_FILE = "revocations.json"
APPROVALS_DIR = "approvals"
MAX_RECORD_BYTES = 64 * 1024
MAX_RECORDS = 256
MAX_TILES = 1024
_FILE_RE = re.compile(r"^(apr-[a-z0-9][a-z0-9-]{2,62})\.json$")
_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC

_TS = {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"}
_REF = {"type": "string", "minLength": 1, "maxLength": 256}
_HTTPS = {"type": "string", "pattern": "^https://[^\\s?#@]+$"}
_PREF = {"type": "string", "pattern": "^(0[1-9]|[1-3][0-9]|4[0-7])$"}
_APPROVAL_ID = {"type": "string", "pattern": "^apr-[a-z0-9][a-z0-9-]{2,62}$"}

APPROVAL_RECORD_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema", "approval_id", "execution_context", "api_id", "source_ref",
                 "operations", "region_codes", "tiles", "definition", "valid_from",
                 "expires_at", "approved_by", "approval_basis_ref", "record_sha256"],
    "allOf": [
        {"if": {"properties": {"operations": {"contains": {"const": "download"}}}},
         "then": {"required": ["acquisition"]}, "else": {"not": {"required": ["acquisition"]}}},
        {"if": {"properties": {"operations": {"contains": {"const": "publish"}}}},
         "then": {"required": ["publication"]}, "else": {"not": {"required": ["publication"]}}},
    ],
    "properties": {
        "schema": {"const": RECORD_SCHEMA_ID},
        "approval_id": _APPROVAL_ID,
        "execution_context": {"const": "production"},
        "api_id": {"type": "string", "pattern": "^[a-z][a-z0-9-]*$"},
        "source_ref": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]*$",
                       "not": {"pattern": "^fixture-"}},
        "operations": {"type": "array", "minItems": 1, "uniqueItems": True,
                       "items": {"enum": ["download", "normalize", "validate", "publish"]}},
        "region_codes": {"type": "array", "minItems": 1, "uniqueItems": True, "items": _PREF},
        "tiles": {"type": "array", "minItems": 1, "maxItems": MAX_TILES, "uniqueItems": True,
                  "items": {"type": "object", "additionalProperties": False,
                            "required": ["z", "x", "y"],
                            "properties": {"z": {"type": "integer", "minimum": 0, "maximum": 30},
                                           "x": {"type": "integer", "minimum": 0},
                                           "y": {"type": "integer", "minimum": 0}}}},
        "definition": {"type": "object", "additionalProperties": False,
                       "required": ["revision", "raw_sha256"],
                       "properties": {"revision": _REF,
                                      "raw_sha256": {"type": "string",
                                                     "pattern": "^[0-9a-f]{64}$"}}},
        "valid_from": _TS,
        "expires_at": _TS,
        "approved_by": _REF,
        "approval_basis_ref": _REF,
        "acquisition": {"type": "object", "additionalProperties": False,
                        "required": ["allowed_host", "max_tiles_per_run", "max_tile_bytes",
                                     "max_pending_acquisitions"],
                        "properties": {
                            "allowed_host": {"type": "string",
                                             "pattern": "^[a-z0-9.-]+\\.[a-z]{2,}$"},
                            "max_tiles_per_run": {"type": "integer", "minimum": 1,
                                                  "maximum": MAX_TILES},
                            "max_tile_bytes": {"type": "integer", "minimum": 1,
                                               "maximum": 1048576},
                            "max_pending_acquisitions": {"type": "integer", "minimum": 1,
                                                         "maximum": 64}}},
        "publication": {"type": "object", "additionalProperties": False,
                        "required": ["license", "attribution_url", "attribution_text",
                                     "eligibility_status", "eligibility_ref"],
                        "properties": {"license": _REF, "attribution_url": _HTTPS,
                                       "attribution_text": _REF,
                                       "eligibility_status": {"const": "approved"},
                                       "eligibility_ref": _REF}},
        "record_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
}

REVOCATIONS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["schema", "revoked"],
    "properties": {
        "schema": {"const": REVOCATIONS_SCHEMA_ID},
        "revoked": {"type": "array", "uniqueItems": True,
                    "items": {"type": "object", "additionalProperties": False,
                              "required": ["approval_id", "revoked_at", "reason_ref"],
                              "properties": {"approval_id": _APPROVAL_ID, "revoked_at": _TS,
                                             "reason_ref": _REF}}},
    },
}


class ApprovalStoreError(Exception):
    """The store cannot be trusted or read. Messages are fixed (no paths)."""


def record_digest(record: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical JSON of a record without ``record_sha256``."""
    body = {k: v for k, v in record.items() if k != "record_sha256"}
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ApprovalStore:
    records: tuple[Mapping[str, Any], ...]
    revoked: frozenset[str]


def _trusted(st: os.stat_result) -> bool:
    return st.st_uid in (os.geteuid(), 0) and not st.st_mode & (stat.S_IWGRP | stat.S_IWOTH)


def _open_dir(parent_fd: int, name: str) -> int:
    try:
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent_fd)
    except OSError as exc:
        raise ApprovalStoreError("store directory unavailable") from exc
    if not _trusted(os.fstat(fd)):
        os.close(fd)
        raise ApprovalStoreError("store directory not trusted")
    return fd


def _read(dir_fd: int, name: str) -> bytes:
    try:
        fd = os.open(name, _READ_FLAGS, dir_fd=dir_fd)
    except OSError as exc:
        raise ApprovalStoreError("store file unavailable") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or not _trusted(st):
            raise ApprovalStoreError("store file not trusted")
        if st.st_size > MAX_RECORD_BYTES:
            raise ApprovalStoreError("store file too large")
        data = os.read(fd, MAX_RECORD_BYTES + 1)
        if len(data) > MAX_RECORD_BYTES:
            raise ApprovalStoreError("store file too large")
        return data
    finally:
        os.close(fd)


def _parse(data: bytes, schema: Mapping[str, Any]) -> Any:
    try:
        doc = parse_strict_json(data)
        validate_with_schema(doc, schema)
    except ConfigurationError as exc:
        raise ApprovalStoreError("store file invalid") from exc
    return doc


def load_store(approval_root: Path, *, protected_roots: tuple[Path, ...]) -> ApprovalStore:
    """Read and verify the whole store; any problem raises ApprovalStoreError."""
    root = Path(approval_root)
    if not root.is_absolute():
        raise ApprovalStoreError("approval root must be absolute")
    try:
        # Opened component by component from "/"; a symlink anywhere fails, so
        # the given path is already canonical once this succeeds.
        root_fd, chain = _open_dir_chain(root)
    except StorageError as exc:
        raise ApprovalStoreError("approval root unavailable") from exc
    try:
        if _chain_within(root, chain, protected_roots):
            raise ApprovalStoreError("approval root inside the repository")
        if not _trusted(os.fstat(root_fd)):
            raise ApprovalStoreError("approval root not trusted")
        try:
            os.stat(FIXTURE_ROOT_MARKER, dir_fd=root_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise ApprovalStoreError("fixture data root is not an approval store")
        revocations = _parse(_read(root_fd, REVOCATIONS_FILE), REVOCATIONS_SCHEMA)
        approvals_fd = _open_dir(root_fd, APPROVALS_DIR)
        try:
            names = sorted(os.listdir(approvals_fd))
            if len(names) > MAX_RECORDS:
                raise ApprovalStoreError("too many approval records")
            records = []
            for name in names:
                match = _FILE_RE.match(name)
                if not match:
                    raise ApprovalStoreError("unexpected entry in approvals")
                record = _parse(_read(approvals_fd, name), APPROVAL_RECORD_SCHEMA)
                if record["approval_id"] != match.group(1):
                    raise ApprovalStoreError("approval id does not match file name")
                if record_digest(record) != record["record_sha256"]:
                    raise ApprovalStoreError("approval record digest mismatch")
                if record["valid_from"] >= record["expires_at"]:
                    raise ApprovalStoreError("approval validity window invalid")
                records.append(record)
        finally:
            os.close(approvals_fd)
    finally:
        os.close(root_fd)
    revoked = frozenset(r["approval_id"] for r in revocations["revoked"])
    return ApprovalStore(tuple(records), revoked)
