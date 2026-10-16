"""Common Configuration Manager (minimal).

Resolves configuration by identifier ``(scope, api_id, config_kind)`` using a
single placement rule, validates it, and returns an immutable snapshot.

Implemented now:
  * identifier allow-list (no arbitrary paths, no cross-API lookup)
  * bounded reads of regular files (no symlink at the final component)
  * strict JSON parsing (UTF-8, duplicate keys and NaN/Infinity rejected)
  * JSON Schema (Draft 2020-12 + FormatChecker) validation; only local ``#...``
    references are allowed and nothing is ever retrieved (no network)
  * semantic checks for Source Definitions (region <-> source_ref consistency)
  * immutable snapshot holding the exact raw bytes and their SHA-256

Not implemented (UNDECIDED in the contracts): Data Manager persistent overrides,
per-request overrides, change history, ``conf/common`` kinds.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

import jsonschema
from referencing import Registry

# Allowed configuration identifiers. Adding an API = adding an entry here plus
# the files under api/<api_id>/conf/. Format of this list is UNDECIDED upstream.
KNOWN_CONFIGS: frozenset[tuple[str, str, str]] = frozenset({("api", "elevation", "sources")})

_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
PREFECTURE_CODES: tuple[str, ...] = tuple(f"{i:02d}" for i in range(1, 48))

# Upper bound for any configuration / schema / authorization file (bytes).
MAX_CONFIG_BYTES = 1024 * 1024
_REF_KEYS = ("$ref", "$dynamicRef")


class ConfigurationError(Exception):
    """Configuration is invalid. Text is for logs/tests only, never for users."""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, value in pairs:
        if key in obj:
            raise ConfigurationError(f"duplicate key {key!r}")
        obj[key] = value
    return obj


def _reject_constant(name: str) -> Any:
    raise ConfigurationError(f"non-standard JSON constant {name}")


def parse_strict_json(raw: bytes) -> Any:
    """Parse UTF-8 JSON rejecting duplicate keys, BOM and NaN/Infinity."""
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ConfigurationError("not UTF-8") from exc
    if text.startswith("﻿"):
        raise ConfigurationError("BOM not allowed")
    try:
        return json.loads(
            text, object_pairs_hook=_reject_duplicates, parse_constant=_reject_constant
        )
    except json.JSONDecodeError as exc:
        raise ConfigurationError("JSON syntax error") from exc


def freeze(value: Any) -> Any:
    """Deep-freeze parsed JSON into read-only mappings and tuples."""
    if isinstance(value, dict):
        return MappingProxyType({k: freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(freeze(v) for v in value)
    return value


def thaw(value: Any) -> Any:
    """Inverse of :func:`freeze` (plain dicts/lists, for JSON serialisation)."""
    if isinstance(value, Mapping):
        return {k: thaw(v) for k, v in value.items()}
    if isinstance(value, tuple):
        return [thaw(v) for v in value]
    return value


def read_limited(path: Path, max_bytes: int = MAX_CONFIG_BYTES) -> bytes:
    """Read a regular file (final component not a symlink) of at most ``max_bytes``."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError as exc:
        raise ConfigurationError("configuration file unreadable") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise ConfigurationError("configuration file is not a regular file")
        if st.st_size > max_bytes:
            raise ConfigurationError("configuration file too large")
        data = os.read(fd, max_bytes + 1)
        if len(data) > max_bytes:
            raise ConfigurationError("configuration file too large")
        return data
    except OSError as exc:
        raise ConfigurationError("configuration file unreadable") from exc
    finally:
        os.close(fd)


def _check_local_refs(node: Any) -> None:
    """Allow only same-document references; forbid base-URI changes."""
    if isinstance(node, Mapping):
        for key, value in node.items():
            if key in _REF_KEYS and not (isinstance(value, str) and value.startswith("#")):
                raise ConfigurationError("non-local schema reference")
            if key == "$id":
                raise ConfigurationError("schema $id not allowed")
            _check_local_refs(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            _check_local_refs(value)


def _deny_retrieve(uri: str) -> Any:
    raise ConfigurationError("schema retrieval disabled")


# Empty registry whose retrieval always fails: jsonschema never fetches a URI.
_NO_RETRIEVAL = Registry(retrieve=_deny_retrieve)  # type: ignore[call-arg]


def validate_with_schema(data: Any, schema: Mapping[str, Any]) -> None:
    _check_local_refs(schema)
    validator_cls = jsonschema.Draft202012Validator
    try:
        validator_cls.check_schema(schema)
        validator = validator_cls(
            schema, format_checker=jsonschema.FormatChecker(), registry=_NO_RETRIEVAL
        )
        errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    except ConfigurationError:
        raise
    except Exception as exc:  # noqa: BLE001 - unresolvable refs, bad schema
        raise ConfigurationError("schema unusable") from exc
    if errors:
        raise ConfigurationError(f"schema violation at {list(errors[0].absolute_path)}")


def assert_persistable(value: Any) -> None:
    """Refuse values that must not be written to snapshots or records.

    Every string that looks like a URL must be ``https`` with no userinfo,
    query, fragment or explicit port. The offending value is never echoed.
    """
    if isinstance(value, Mapping):
        for key, item in value.items():
            assert_persistable(key)
            assert_persistable(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            assert_persistable(item)
    elif isinstance(value, str) and ("://" in value or value.lower().startswith(("http:", "https:"))):
        try:
            parts = urlsplit(value)
            port = parts.port
        except ValueError as exc:
            raise ConfigurationError("URL not persistable") from exc
        if (
            parts.scheme != "https"
            or not parts.hostname
            or "@" in parts.netloc
            or port is not None
            or parts.query
            or parts.fragment
            or "?" in value
            or "#" in value
        ):
            raise ConfigurationError("URL not persistable")


def load_validated_json(path: Path, schema: Mapping[str, Any]) -> tuple[bytes, Any]:
    """Shared primitive: bounded read, strict-parse, schema-validate."""
    raw = read_limited(path)
    data = parse_strict_json(raw)
    validate_with_schema(data, schema)
    return raw, data


@dataclass(frozen=True)
class ConfigSnapshot:
    """Immutable, validated configuration as loaded at run start."""

    scope: str
    api_id: str
    config_kind: str
    raw_bytes: bytes
    raw_sha256: str
    data: Mapping[str, Any]


def _validate_source_definition(api_id: str, data: Mapping[str, Any]) -> None:
    """Semantic checks shared by every API's ``sources`` definition."""
    if data.get("hazard") != api_id:
        raise ConfigurationError("hazard does not match api_id")
    prefectures = data["prefectures"]
    if tuple(sorted(prefectures)) != PREFECTURE_CODES:
        raise ConfigurationError("prefecture code set is not 01..47")
    sources = data["sources"]
    for code, region in prefectures.items():
        for ref in region["source_refs"]:
            if ref not in sources:
                raise ConfigurationError(f"region {code} references unknown source")


SEMANTIC_VALIDATORS: dict[str, Callable[[str, Mapping[str, Any]], None]] = {
    "sources": _validate_source_definition,
}


class ConfigurationManager:
    """Resolve and validate configuration by identifier.

    ``definition_root`` holds ``api/<api_id>/conf/<kind>.json``;
    ``schema_root`` holds ``api/<api_id>/conf/<kind>.schema.json``. In
    production both are the repository root. A fixture run points
    ``definition_root`` at a fixture tree while schemas always come from the
    repository, so fixture definitions are checked against the real contract.
    """

    def __init__(self, definition_root: Path, schema_root: Path) -> None:
        self.definition_root = Path(definition_root)
        self.schema_root = Path(schema_root)

    @staticmethod
    def _relative(api_id: str, kind: str, suffix: str) -> Path:
        return Path("api") / api_id / "conf" / f"{kind}{suffix}"

    def definition_path(self, scope: str, api_id: str, kind: str) -> Path:
        self._check_identifier(scope, api_id, kind)
        return self.definition_root / self._relative(api_id, kind, ".json")

    @staticmethod
    def _check_identifier(scope: str, api_id: str, kind: str) -> None:
        if not (_ID_RE.match(api_id) and _ID_RE.match(kind)):
            raise ConfigurationError("malformed configuration identifier")
        if (scope, api_id, kind) not in KNOWN_CONFIGS:
            raise ConfigurationError("configuration identifier not allowed")

    def load(self, scope: str, api_id: str, kind: str) -> ConfigSnapshot:
        self._check_identifier(scope, api_id, kind)
        schema_path = self.schema_root / self._relative(api_id, kind, ".schema.json")
        schema = parse_strict_json(read_limited(schema_path))
        raw, data = load_validated_json(self.definition_path(scope, api_id, kind), schema)
        semantic = SEMANTIC_VALIDATORS.get(kind)
        if semantic is not None:
            semantic(api_id, data)
        # Definitions are persisted verbatim in run snapshots: refuse secrets now.
        assert_persistable(data)
        return ConfigSnapshot(
            scope=scope,
            api_id=api_id,
            config_kind=kind,
            raw_bytes=raw,
            raw_sha256=sha256_hex(raw),
            data=freeze(data),
        )
