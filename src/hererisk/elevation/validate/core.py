"""Pure validation of one in-memory Normalize candidate (contract sections 4.2 / 5).

Input: the ``hererisk-elevation-cm-json-v0.1`` structure produced by Normalize.
Output: a :class:`ValidationResult` with the counts / min / max statistics.
Rejection: :class:`CandidateRejected` (a ``PipelineError``) naming the failed check.

No I/O, no PNG decoding, no call to Normalize. The candidate is never modified,
completed or reordered. Only ``None`` is no-data; 0 and negative values are
valid elevations. Values are checked by exact type: ``bool``, ``float`` (incl.
NaN), ``str`` etc. are rejected, never coerced.

A candidate passing this profile is structurally sound fixture data only; it is
not a statement about real terrain quality or eligibility for publication.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from hererisk.common.result import PipelineError
from hererisk.elevation.normalize.convert import FORMAT, PIXELS, _check_tile
from hererisk.elevation.tile_format import TILE_HEIGHT, TILE_WIDTH

PROFILE_ID = "fixture-elevation-normalized-v0.1"
VALUE_MIN_CM = -8388607  # representable range of the GSI encoding (q - 2^24 .. 2^23 - 1)
VALUE_MAX_CM = 8388607
WARNING_ALL_NODATA = "ALL_NODATA"
_KEYS = frozenset({"format", "tile", "width", "height", "values_cm"})


class CandidateRejected(PipelineError):
    """Candidate violates the profile. ``check`` names the failed check.

    Uses the existing INVALID_INPUT code: the contract's VALIDATION_FAILED is a
    proposal not yet added to the common error table (out of scope here).
    """

    def __init__(self, check: str, detail: str = "") -> None:
        super().__init__("INVALID_INPUT", f"{check}: {detail}" if detail else check)
        self.check = check


@dataclass(frozen=True)
class ValidationResult:
    profile: str
    tile: tuple[int, int, int]  # (z, x, y)
    valid_count: int
    nodata_count: int
    min_cm: int | None
    max_cm: int | None

    @property
    def warning(self) -> str | None:
        """``ALL_NODATA`` for an entirely missing tile (accepted, but flagged)."""
        return WARNING_ALL_NODATA if self.valid_count == 0 else None

    def stats(self) -> dict[str, int | None]:
        return {
            "valid_count": self.valid_count,
            "nodata_count": self.nodata_count,
            "min_cm": self.min_cm,
            "max_cm": self.max_cm,
        }


def validate_candidate(
    candidate: Mapping[str, Any], *, expected_tile: Mapping[str, Any] | None = None
) -> ValidationResult:
    """Check a Normalize candidate and compute its statistics in one pass.

    ``expected_tile`` (optional) is the tile fixed by the plan; when given the
    candidate's tile must equal it exactly.
    """
    if not isinstance(candidate, Mapping):
        raise CandidateRejected("keys", "candidate is not an object")
    if set(candidate) != _KEYS:
        raise CandidateRejected("keys", "missing or unknown keys")
    if type(candidate["format"]) is not str or candidate["format"] != FORMAT:
        raise CandidateRejected("format", "unsupported format")
    try:
        tile = _check_tile(candidate["tile"])
    except PipelineError as exc:
        raise CandidateRejected("tile", "invalid tile") from exc
    if expected_tile is not None and tile != dict(expected_tile):
        raise CandidateRejected("tile", "tile differs from the fixed plan")
    for key, expected in (("width", TILE_WIDTH), ("height", TILE_HEIGHT)):
        if type(candidate[key]) is not int or candidate[key] != expected:
            raise CandidateRejected("dimensions", f"{key} must be {expected}")
    values = candidate["values_cm"]
    if type(values) is not list:
        raise CandidateRejected("values", "values_cm is not an array")
    if len(values) != PIXELS:
        raise CandidateRejected("values", "values_cm length is not 65536")

    nodata = 0
    low: int | None = None
    high: int | None = None
    for value in values:  # single pass: type, range and statistics
        if value is None:
            nodata += 1
        elif type(value) is int:
            if not VALUE_MIN_CM <= value <= VALUE_MAX_CM:
                raise CandidateRejected("values", "value outside encoding range")
            if low is None:
                low = high = value
            elif value < low:
                low = value
            elif value > high:  # type: ignore[operator]
                high = value
        else:
            raise CandidateRejected("values", "value is neither integer nor null")

    return ValidationResult(
        profile=PROFILE_ID,
        tile=(tile["z"], tile["x"], tile["y"]),
        valid_count=PIXELS - nodata,
        nodata_count=nodata,
        min_cm=low,
        max_cm=high,
    )
