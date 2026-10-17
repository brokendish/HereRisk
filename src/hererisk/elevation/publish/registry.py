"""Dataset Registry (elevation) — schema, layout and verified reads.

Layout under ``<data_root>/elevation/rel/`` (Registry physical placement was
UNDECIDED; this is the Phase 1-D.4 proposal)::

    versions/<publication_version>/<dataset_id>.json   immutable published entity
    registry/<prefecture>/revisions/<revision>.json    immutable registry revision
    registry/<prefecture>/current.json                 pointer (atomically replaced)

The pointer names one revision and its SHA-256. Publishing never modifies or
deletes revisions or entities, so a reader holding an old revision keeps
working (old-generation protection). Registry fields follow
docs/architecture/dataset-registry-v0.1.md; values specific to this API are
documented in docs/pipeline/elevation-publish-api-v0.1.md.

One dataset = one Z/X/Y tile; its published entity is the validated
``hererisk-elevation-cm-json-v0.1`` candidate (byte-identical copy).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any

from hererisk.common.config import ConfigurationError, parse_strict_json, validate_with_schema
from hererisk.common.result import PipelineError
from hererisk.common.storage import REGISTRY_POINTER, ApiDataArea, Loc, MissingError, StorageError

REGISTRY_SCHEMA_VERSION = "0.1"
POINTER_SCHEMA_VERSION = "0.1"
ENTITY_FORMAT = "hererisk-elevation-cm-json-v0.1"
COVERAGE_MODE = "xyz_tile"
MAX_REGISTRY_BYTES = 4 * 1024 * 1024
MAX_POINTER_BYTES = 4 * 1024
MAX_ENTITY_BYTES = 1024 * 1024
_PREF = "^(0[1-9]|[1-3][0-9]|4[0-7])$"
_ID = "^[a-z0-9][a-z0-9-]{0,127}$"
_TS = "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
_HTTPS = "^https://[^\\s?#@]+$"
_COVERAGE_REF = re.compile(r"^xyz:([0-9]{1,2})/([0-9]{1,10})/([0-9]{1,10})$")


def _obj(props: dict[str, Any], optional: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False,
            "required": [k for k in props if k not in optional], "properties": props}


_STR = {"type": "string", "minLength": 1}
DATASET_SCHEMA = _obj({
    "id": {"type": "string", "pattern": _ID},
    "name": _STR,
    "hazard": {"const": "elevation"},
    "coverage": _obj({
        "ref": {"type": "string", "pattern": _COVERAGE_REF.pattern},
        "mode": {"const": COVERAGE_MODE},
        "bbox": {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "number"}},
        "prefectures": {"type": "array", "minItems": 1, "uniqueItems": True,
                        "items": {"type": "string", "pattern": _PREF}},
        "crs": {"const": "EPSG:4326"},
    }),
    "source": _obj({
        "provider": _STR,
        "page_url": {"type": "string", "pattern": _HTTPS},
        "format": {"const": "png"},
        "retrieved_at": {"type": "string", "pattern": _TS},
        "filename": _STR,
    }),
    "acquisition": _obj({
        "method": {"const": "http"},
        "url": {"type": "string", "pattern": _HTTPS},
        "parameters": _obj({
            "layer": _STR, "z": {"type": "integer"}, "x": {"type": "integer"},
            "y": {"type": "integer"}, "acquisition_id": _STR,
            "source_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        }),
    }),
    "pipeline": _obj({"id": _STR, "name": _STR, "version": _STR}),
    "validation": _obj({
        "status": {"const": "passed"},
        "profile": _STR,
        "validated_at": {"type": "string", "pattern": _TS},
    }),
    "publication": _obj({
        "version": _STR,
        "path": {"type": "string", "pattern": "^versions/[A-Za-z0-9][A-Za-z0-9._-]*/[a-z0-9][a-z0-9-]*\\.json$"},
        "format": {"const": ENTITY_FORMAT},
        "published_at": {"type": "string", "pattern": _TS},
        "filename": _STR,
        "checksum": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    }),
    "attribution": _obj({
        "text": _STR,
        "license": _STR,
        "url": {"type": "string", "pattern": _HTTPS},
    }),
})
REGISTRY_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    **_obj({
        "schema_version": {"const": REGISTRY_SCHEMA_VERSION},
        "prefecture_code": {"type": "string", "pattern": _PREF},
        "registry_revision": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]*$"},
        "datasets": {"type": "array", "items": DATASET_SCHEMA},
    }),
}
POINTER_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    **_obj({
        "schema_version": {"const": POINTER_SCHEMA_VERSION},
        "prefecture_code": {"type": "string", "pattern": _PREF},
        "registry_revision": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._-]*$"},
        "registry_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
        "previous_revision": {"type": ["string", "null"]},
    }),
}


class RegistryError(PipelineError):
    """Registry / published entity problem. ``kind`` refines the error_code:

    ``missing``   (entity or revision absent where the registry says it is)
    ``integrity`` (schema, reference, version or checksum mismatch)
    ``unavailable`` (I/O failure reading)
    """

    def __init__(self, kind: str, detail: str = "") -> None:
        code = {"missing": "RECOVERY_REQUIRED", "integrity": "RECOVERY_REQUIRED",
                "unavailable": "STORAGE_INTEGRITY_FAILED"}[kind]
        super().__init__(code, f"{kind}: {detail}" if detail else kind)
        self.kind = kind


@dataclass(frozen=True)
class RegistrySnapshot:
    prefecture_code: str
    pointer: dict[str, Any]
    registry: dict[str, Any]
    registry_bytes: bytes


def to_bytes(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def pointer_loc(prefecture: str) -> Loc:
    return Loc(("rel", "registry", prefecture, REGISTRY_POINTER))


def revision_loc(prefecture: str, revision: str) -> Loc:
    return Loc(("rel", "registry", prefecture, "revisions", f"{revision}.json"))


def entity_loc(path: str) -> Loc:
    return Loc(("rel", *path.split("/")))


def tile_of(dataset: dict[str, Any]) -> tuple[int, int, int]:
    match = _COVERAGE_REF.match(dataset["coverage"]["ref"])
    if match is None:
        raise RegistryError("integrity", "coverage ref")
    return tuple(int(v) for v in match.groups())  # type: ignore[return-value]


def tile_bbox(z: int, x: int, y: int) -> list[float]:
    """[west, south, east, north] in degrees (EPSG:4326) of an XYZ tile."""
    n = 2 ** z

    def lat(row: int) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * row / n))))

    return [x / n * 360 - 180, lat(y + 1), (x + 1) / n * 360 - 180, lat(y)]


def _read(area: ApiDataArea, loc: Loc, limit: int) -> bytes:
    try:
        return area.read_bytes(loc, limit)
    except MissingError as exc:
        raise RegistryError("missing", "file absent") from exc
    except StorageError as exc:
        if exc.error_code == "STORAGE_INTEGRITY_FAILED":
            raise RegistryError("integrity", "not a valid committed file") from exc
        raise RegistryError("unavailable", "read failed") from exc


def check_registry(document: dict[str, Any], prefecture: str) -> None:
    try:
        validate_with_schema(document, REGISTRY_SCHEMA)
    except ConfigurationError as exc:
        raise RegistryError("integrity", "registry schema") from exc
    if document["prefecture_code"] != prefecture:
        raise RegistryError("integrity", "prefecture mismatch")
    ids = [d["id"] for d in document["datasets"]]
    if len(ids) != len(set(ids)):
        raise RegistryError("integrity", "duplicate dataset id")
    for dataset in document["datasets"]:
        z, x, y = tile_of(dataset)
        params = dataset["acquisition"]["parameters"]
        if (params["z"], params["x"], params["y"]) != (z, x, y) or not 0 <= z <= 30 \
                or not (0 <= x < 2 ** z and 0 <= y < 2 ** z):
            raise RegistryError("integrity", "tile reference")
        publication = dataset["publication"]
        if publication["path"] != f"versions/{publication['version']}/{publication['filename']}" \
                or publication["filename"] != f"{dataset['id']}.json":
            raise RegistryError("integrity", "publication path")


def read_current(area: ApiDataArea, prefecture: str) -> RegistrySnapshot | None:
    """Verified current registry of a prefecture, or None if never published."""
    loc = pointer_loc(prefecture)
    if not area.entry_exists(loc):
        return None
    try:
        pointer = parse_strict_json(_read(area, loc, MAX_POINTER_BYTES))
        validate_with_schema(pointer, POINTER_SCHEMA)
    except ConfigurationError as exc:
        raise RegistryError("integrity", "pointer") from exc
    if pointer["prefecture_code"] != prefecture:
        raise RegistryError("integrity", "pointer prefecture")
    data = _read(area, revision_loc(prefecture, pointer["registry_revision"]), MAX_REGISTRY_BYTES)
    if hashlib.sha256(data).hexdigest() != pointer["registry_sha256"]:
        raise RegistryError("integrity", "registry checksum")
    try:
        registry = parse_strict_json(data)
    except ConfigurationError as exc:
        raise RegistryError("integrity", "registry JSON") from exc
    check_registry(registry, prefecture)
    if registry["registry_revision"] != pointer["registry_revision"]:
        raise RegistryError("integrity", "revision mismatch")
    return RegistrySnapshot(prefecture, pointer, registry, data)


def read_entity(area: ApiDataArea, dataset: dict[str, Any]) -> bytes:
    """Published entity bytes, verified against the registry's checksum."""
    publication = dataset["publication"]
    data = _read(area, entity_loc(publication["path"]), MAX_ENTITY_BYTES)
    if "sha256:" + hashlib.sha256(data).hexdigest() != publication["checksum"]:
        raise RegistryError("integrity", "entity checksum")
    return data
