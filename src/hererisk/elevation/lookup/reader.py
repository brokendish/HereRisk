"""Read-only point elevation from one validated fixture run (Phase 1-C.2).

``read_point_elevation(area, run_id, latitude, longitude, zoom)``:

  1. ``locate_pixel`` -> tile and pixel (zoom is the caller's; nothing is fixed to Z14)
  2. the run's Validate record must be a fixture SUCCESS with every check passed
  3. its Normalize record must hash to the value pinned in the Validate record,
     be a SUCCESS of the same run / configuration, and list the same outputs
  4. the acquisition for the tile is taken from the Normalize record's fixed
     ``inputs`` (never from directory names, never by scanning candidates);
     no entry -> TILE_NOT_IN_RUN
  5. only that candidate is read (bounded, through the safe storage layer) and
     its size / SHA-256 compared with the Normalize record
  6. strict JSON parsing and ``validate_candidate`` with the expected tile; the
     statistics must equal the Validate record's
  7. ``lookup_elevation`` -> the stored value, unchanged

Trust chain: Validate record (root, read from the management area) -> Normalize
record hash -> candidate hash. A SUCCESS record alone is not trusted: every
link is re-checked. Nothing is written, repaired or deleted. Fixture data roots
only (marker required); this says nothing about future production read access.

Result for a valid pixel without data is a normal result with
``elevation_cm=None`` and ``nodata=True`` - distinct from a tile that is not
part of the run, which is an error.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from hererisk.common.config import ConfigurationError, parse_strict_json, validate_with_schema
from hererisk.common.result import PipelineError
from hererisk.common.storage import ApiDataArea, StorageError
from hererisk.elevation.lookup.core import locate_pixel, lookup_elevation
from hererisk.elevation.normalize import stage as normalize_stage
from hererisk.elevation.normalize.stage import MAX_CANDIDATE_BYTES, MAX_NORMALIZE_RECORD_BYTES
from hererisk.elevation.validate import stage as validate_stage
from hererisk.elevation.validate.core import CandidateRejected, validate_candidate
from hererisk.elevation.validate.stage import CHECKS, MAX_VALIDATE_RECORD_BYTES

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

# Rejection reasons (the error_code alone is not always specific enough).
INVALID_COORDINATES = "INVALID_COORDINATES"
INVALID_RUN = "INVALID_RUN"
NOT_FIXTURE = "NOT_FIXTURE"
NOT_VALIDATED = "NOT_VALIDATED"
TILE_NOT_IN_RUN = "TILE_NOT_IN_RUN"
EVIDENCE_INCONSISTENT = "EVIDENCE_INCONSISTENT"
CANDIDATE_CORRUPTED = "CANDIDATE_CORRUPTED"
CANDIDATE_INVALID = "CANDIDATE_INVALID"


class ReadRejected(PipelineError):
    """Lookup refused. ``reason`` is one of the constants above."""

    def __init__(self, error_code: str, reason: str, detail: str = "") -> None:
        super().__init__(error_code, f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass(frozen=True)
class PointElevation:
    run_id: str
    acquisition_id: str
    candidate_sha256: str
    z: int
    tile_x: int
    tile_y: int
    pixel_x: int
    pixel_y: int
    elevation_cm: int | None

    @property
    def nodata(self) -> bool:
        return self.elevation_cm is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "acquisition_id": self.acquisition_id,
            "candidate_sha256": self.candidate_sha256,
            "tile": {"z": self.z, "x": self.tile_x, "y": self.tile_y},
            "pixel": {"x": self.pixel_x, "y": self.pixel_y},
            "elevation_cm": self.elevation_cm,
            "nodata": self.nodata,
        }


def _read_record(area: ApiDataArea, parts: tuple[str, ...], limit: int, schema: dict,
                 missing_reason: str, missing_code: str) -> tuple[bytes, dict]:
    loc = area.path(*parts)
    if not area.entry_exists(loc):
        raise ReadRejected(missing_code, missing_reason, "record missing")
    try:
        data = area.read_bytes(loc, limit)
        record = parse_strict_json(data)
        validate_with_schema(record, schema)
    except (StorageError, ConfigurationError) as exc:
        raise ReadRejected("RECOVERY_REQUIRED", EVIDENCE_INCONSISTENT, "record unreadable") from exc
    return data, record


def read_point_elevation(
    area: ApiDataArea, run_id: str, latitude: float, longitude: float, zoom: int
) -> PointElevation:
    if type(run_id) is not str or not _UUID_RE.match(run_id):
        raise ReadRejected("INVALID_INPUT", INVALID_RUN, "run_id must be a UUID")
    try:
        location = locate_pixel(latitude, longitude, zoom)
    except PipelineError as exc:
        raise ReadRejected("INVALID_INPUT", INVALID_COORDINATES) from exc
    if not area.has_fixture_marker():
        raise ReadRejected("APPROVAL_REQUIRED", NOT_FIXTURE, "fixture data roots only")

    # 2. Validate record: fixture SUCCESS, all checks passed.
    _, validation = _read_record(
        area, ("records", "validations", f"{run_id}.json"), MAX_VALIDATE_RECORD_BYTES,
        validate_stage.RECORD_SCHEMA, NOT_VALIDATED, "INVALID_INPUT")
    if validation["run_id"] != run_id:
        raise ReadRejected("RECOVERY_REQUIRED", EVIDENCE_INCONSISTENT, "run mismatch")
    if validation["status"] != "SUCCESS" or validation["error_code"] is not None \
            or validation["validation"]["checks"] != {name: "passed" for name in CHECKS}:
        raise ReadRejected("INVALID_INPUT", NOT_VALIDATED, "validation not a SUCCESS")

    # 3. Normalize record pinned by the Validate record.
    ref = validation["validation"]["normalize_record_ref"]
    if ref != f"normalizations/{run_id}.json":
        raise ReadRejected("RECOVERY_REQUIRED", EVIDENCE_INCONSISTENT, "normalize reference")
    data, normalization = _read_record(
        area, ("records", "normalizations", f"{run_id}.json"), MAX_NORMALIZE_RECORD_BYTES,
        normalize_stage.RECORD_SCHEMA, EVIDENCE_INCONSISTENT, "RECOVERY_REQUIRED")
    if (
        hashlib.sha256(data).hexdigest() != validation["validation"]["normalize_record_sha256"]
        or normalization["status"] != "SUCCESS"
        or normalization["run_id"] != run_id
        or normalization["source_raw_sha256"] != validation["source_raw_sha256"]
        or normalization["effective_configuration"] != validation["effective_configuration"]
        or normalization["outputs"] != validation["outputs"]
        or [i["acquisition_id"] for i in normalization["inputs"]]
        != [o["acquisition_id"] for o in normalization["outputs"]]
        or [t["acquisition_id"] for t in validation["validation"]["tiles"]]
        != [o["acquisition_id"] for o in normalization["outputs"]]
    ):
        raise ReadRejected("RECOVERY_REQUIRED", EVIDENCE_INCONSISTENT, "normalize record mismatch")

    # 4. Tile -> acquisition from the fixed inputs.
    wanted = {"z": location.z, "x": location.tile_x, "y": location.tile_y}
    matches = [i for i, entry in enumerate(normalization["inputs"]) if entry["tile"] == wanted]
    if not matches:
        raise ReadRejected("TARGET_UNCONFIGURED", TILE_NOT_IN_RUN, "tile not part of the run")
    if len(matches) > 1:
        raise ReadRejected("RECOVERY_REQUIRED", EVIDENCE_INCONSISTENT, "duplicate tile")
    index = matches[0]
    output = normalization["outputs"][index]
    stored_stats = validation["validation"]["tiles"][index]
    acquisition_id = output["acquisition_id"]

    # 5. Only this candidate, bounded, hash-checked.
    loc = area.path("work", "normalized", run_id, f"{acquisition_id}.json")
    if output["candidate_ref"] != area.relative(loc, "work"):
        raise ReadRejected("RECOVERY_REQUIRED", EVIDENCE_INCONSISTENT, "candidate reference")
    try:
        raw = area.read_bytes(loc, MAX_CANDIDATE_BYTES)
    except StorageError as exc:
        raise ReadRejected("STORAGE_INTEGRITY_FAILED", CANDIDATE_CORRUPTED, "unreadable") from exc
    if len(raw) != output["size_bytes"] or hashlib.sha256(raw).hexdigest() != output["candidate_sha256"]:
        raise ReadRejected("STORAGE_INTEGRITY_FAILED", CANDIDATE_CORRUPTED, "hash mismatch")

    # 6. Strict parse + Validate Core; statistics must equal the recorded ones.
    try:
        candidate = parse_strict_json(raw)
        result = validate_candidate(candidate, expected_tile=wanted)
    except (ConfigurationError, CandidateRejected) as exc:
        raise ReadRejected("VALIDATION_FAILED", CANDIDATE_INVALID) from exc
    if {"acquisition_id": acquisition_id, **result.stats(), "warning": result.warning} != stored_stats:
        raise ReadRejected("RECOVERY_REQUIRED", EVIDENCE_INCONSISTENT, "statistics mismatch")

    # 7. Stored value, unchanged.
    value = lookup_elevation(candidate, location)
    return PointElevation(
        run_id=run_id,
        acquisition_id=acquisition_id,
        candidate_sha256=output["candidate_sha256"],
        z=location.z,
        tile_x=location.tile_x,
        tile_y=location.tile_y,
        pixel_x=location.pixel_x,
        pixel_y=location.pixel_y,
        elevation_cm=value,
    )
