"""Phase 1-D.2: read-only point elevation from a Phase 1-D.1 GSI PoC directory.

``read_poc_elevation(poc_dir, latitude, longitude, zoom)``:

  1. ``locate_pixel`` -> tile and pixel (zoom is the caller's)
  2. the directory must be a dedicated PoC directory: real directory pinned
     without following symlinks, exact PoC marker, not a fixture data root
  3. the tile's evidence ``dem_png_<z>_<x>_<y>.json`` (bounded, regular file,
     single link, own uid) is strictly parsed and checked: PoC schema,
     ``poc_only``, tile, URL, HTTP 200 / image/png, all checks passed
  4. the PNG named in the evidence (same rules) must match size and SHA-256
  5. ``normalize_tile`` -> in-memory candidate; ``validate_candidate`` with the
     tile; statistics must equal the evidence
  6. ``lookup_elevation`` -> stored value

No network code is imported here; nothing is written, repaired or deleted;
PoC files are never copied into the fixture pipeline. The value is GSI PoC
data: not approved for publication, vertical reference / survey period /
revision status unconfirmed (reported, never guessed).
"""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hererisk.common.config import ConfigurationError, parse_strict_json, validate_with_schema
from hererisk.common.result import PipelineError
from hererisk.common.storage import FIXTURE_ROOT_MARKER, StorageError, _open_dir_chain
from hererisk.elevation.gsi_poc.constants import (
    EVIDENCE_SCHEMA,
    MAX_BODY_BYTES,
    MAX_EVIDENCE_BYTES,
    POC_MARKER,
    POC_MARKER_CONTENT,
    SOURCE_REF,
    tile_basename,
    tile_url,
)
from hererisk.elevation.lookup.core import locate_pixel, lookup_elevation
from hererisk.elevation.lookup.reader import INVALID_COORDINATES, ReadRejected
from hererisk.elevation.normalize.convert import normalize_tile
from hererisk.elevation.validate.core import validate_candidate

NOT_POC_DIR = "NOT_POC_DIR"
TILE_NOT_FETCHED = "TILE_NOT_FETCHED"
EVIDENCE_INVALID = "EVIDENCE_INVALID"
PNG_MISMATCH = "PNG_MISMATCH"
PNG_UNDECODABLE = "PNG_UNDECODABLE"
STATISTICS_MISMATCH = "STATISTICS_MISMATCH"

_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
_SHA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_TS = {"type": "string", "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"}
_INT0 = {"type": "integer", "minimum": 0}


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "required": required or list(props), "properties": props}


# Checked fields of the D.1 evidence (unknown extra keys are tolerated: the
# reader only relies on what it verifies).
EVIDENCE_READ_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    **_obj({
        "schema": {"const": EVIDENCE_SCHEMA},
        "poc_only": {"const": True},
        "dataset": {"const": "DEM10B"},
        "layer": {"const": "dem_png"},
        "url": {"type": "string"},
        "tile": {"type": "object", "additionalProperties": False, "required": ["z", "x", "y"],
                 "properties": {"z": _INT0, "x": _INT0, "y": _INT0}},
        "acquired_at": _TS,
        "http_status": {"const": 200},
        "content_type": {"const": "image/png"},
        "size_bytes": {"type": "integer", "minimum": 1, "maximum": MAX_BODY_BYTES},
        "sha256": _SHA,
        "png_file": {"type": "string"},
        "checks": {"const": {"png_container": "passed", "decode": "passed", "profile": "passed"}},
        "statistics": _obj({"valid_count": _INT0, "nodata_count": _INT0,
                            "min_cm": {"type": ["integer", "null"]},
                            "max_cm": {"type": ["integer", "null"]},
                            "warning": {"enum": [None, "ALL_NODATA"]}}),
        "source_definition": _obj({"source_ref": {"const": SOURCE_REF}}),
        "attribution": {"type": "string", "minLength": 1},
        "unconfirmed": {"type": "array", "items": {"type": "string"}},
    }),
}


@dataclass(frozen=True)
class PocElevation:
    z: int
    tile_x: int
    tile_y: int
    pixel_x: int
    pixel_y: int
    elevation_cm: int | None
    sha256: str
    acquired_at: str
    attribution: str
    unconfirmed: tuple[str, ...]

    @property
    def nodata(self) -> bool:
        return self.elevation_cm is None

    @property
    def elevation_m(self) -> float | None:
        return None if self.elevation_cm is None else self.elevation_cm / 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "tile": {"z": self.z, "x": self.tile_x, "y": self.tile_y},
            "pixel": {"x": self.pixel_x, "y": self.pixel_y},
            "elevation_cm": self.elevation_cm,
            "elevation_m": self.elevation_m,
            "nodata": self.nodata,
            "poc_only": True,
            "source": {
                "provider": "国土地理院",
                "dataset": "DEM10B",
                "layer": "dem_png",
                "attribution": self.attribution,
                "png_sha256": self.sha256,
                "acquired_at": self.acquired_at,
                "approved_for_publication": False,
                "unconfirmed": list(self.unconfirmed),
            },
        }


def _read_file(dir_fd: int, name: str, limit: int, missing: tuple[str, str],
               bad: tuple[str, str]) -> bytes:
    """Read a regular, single-link, self-owned file of at most ``limit`` bytes."""
    try:
        fd = os.open(name, _READ_FLAGS, dir_fd=dir_fd)
    except FileNotFoundError as exc:
        raise ReadRejected(*missing, "file missing") from exc
    except OSError as exc:  # symlink, directory, permission ...
        raise ReadRejected(*bad, "file not readable") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_uid != os.geteuid():
            raise ReadRejected(*bad, "not a single-link regular file of this user")
        if st.st_size > limit:
            raise ReadRejected(*bad, "file too large")
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, 64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ReadRejected(*bad, "file too large")
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError as exc:
        raise ReadRejected(*bad, "read failed") from exc
    finally:
        os.close(fd)


def _open_poc_dir(poc_dir: Path) -> int:
    path = Path(poc_dir)
    reject = ReadRejected("INVALID_INPUT", NOT_POC_DIR, "not a GSI PoC directory")
    if path.is_symlink() or not path.is_dir():
        raise reject
    try:
        fd, _ = _open_dir_chain(Path(os.path.realpath(path)))
    except StorageError as exc:
        raise reject from exc
    try:
        try:
            os.stat(FIXTURE_ROOT_MARKER, dir_fd=fd, follow_symlinks=False)
            raise reject  # a fixture data root is never a PoC directory
        except FileNotFoundError:
            pass
        marker = _read_file(fd, POC_MARKER, 128, ("INVALID_INPUT", NOT_POC_DIR),
                            ("INVALID_INPUT", NOT_POC_DIR))
        if marker != POC_MARKER_CONTENT:
            raise reject
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_poc_elevation(poc_dir: Path, latitude: float, longitude: float, zoom: int) -> PocElevation:
    try:
        location = locate_pixel(latitude, longitude, zoom)
    except PipelineError as exc:
        raise ReadRejected("INVALID_INPUT", INVALID_COORDINATES) from exc
    tile = {"z": location.z, "x": location.tile_x, "y": location.tile_y}
    base = tile_basename(location.z, location.tile_x, location.tile_y)

    fd = _open_poc_dir(poc_dir)
    try:
        raw = _read_file(fd, f"{base}.json", MAX_EVIDENCE_BYTES,
                         ("TARGET_UNCONFIGURED", TILE_NOT_FETCHED),
                         ("RECOVERY_REQUIRED", EVIDENCE_INVALID))
        try:
            evidence = parse_strict_json(raw)
            validate_with_schema(evidence, EVIDENCE_READ_SCHEMA)
        except ConfigurationError as exc:
            raise ReadRejected("RECOVERY_REQUIRED", EVIDENCE_INVALID, "evidence invalid") from exc
        if (evidence["tile"] != tile or evidence["png_file"] != f"{base}.png"
                or evidence["url"] != tile_url(location.z, location.tile_x, location.tile_y)):
            raise ReadRejected("RECOVERY_REQUIRED", EVIDENCE_INVALID, "evidence for another tile")

        png = _read_file(fd, f"{base}.png", MAX_BODY_BYTES,
                         ("STORAGE_INTEGRITY_FAILED", PNG_MISMATCH),
                         ("STORAGE_INTEGRITY_FAILED", PNG_MISMATCH))
    finally:
        os.close(fd)
    if len(png) != evidence["size_bytes"] or hashlib.sha256(png).hexdigest() != evidence["sha256"]:
        raise ReadRejected("STORAGE_INTEGRITY_FAILED", PNG_MISMATCH, "size or SHA-256 differs")

    try:
        candidate = normalize_tile(png, tile, max_png_bytes=MAX_BODY_BYTES)
        result = validate_candidate(candidate, expected_tile=tile)
    except PipelineError as exc:
        raise ReadRejected("PNG_INVALID", PNG_UNDECODABLE, "decode or profile failed") from exc
    if {**result.stats(), "warning": result.warning} != evidence["statistics"]:
        raise ReadRejected("RECOVERY_REQUIRED", STATISTICS_MISMATCH, "statistics differ")

    return PocElevation(
        z=location.z, tile_x=location.tile_x, tile_y=location.tile_y,
        pixel_x=location.pixel_x, pixel_y=location.pixel_y,
        elevation_cm=lookup_elevation(candidate, location),
        sha256=evidence["sha256"], acquired_at=evidence["acquired_at"],
        attribution=evidence["attribution"], unconfirmed=tuple(evidence["unconfirmed"]),
    )
