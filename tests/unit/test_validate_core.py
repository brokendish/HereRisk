"""Unit tests: elevation Validate core (in-memory candidate check + statistics).

Expected statistics are fixed literals computed by hand for each constructed
candidate, never by the code under test.
"""

from __future__ import annotations

import copy
import math

import pytest

import fixture_builder as fb
from hererisk.common.result import PipelineError
from hererisk.elevation.normalize.convert import normalize_tile
from hererisk.elevation.validate import core
from hererisk.elevation.validate.core import (
    PROFILE_ID,
    CandidateRejected,
    ValidationResult,
    validate_candidate,
)

TILE = {"z": 14, "x": 14550, "y": 6450}
N = 65536


def candidate(values, **overrides):
    doc = {
        "format": "hererisk-elevation-cm-json-v0.1",
        "tile": dict(TILE),
        "width": 256,
        "height": 256,
        "values_cm": values,
    }
    doc.update(overrides)
    return doc


def rejected(doc, check, **kwargs):
    with pytest.raises(CandidateRejected) as err:
        validate_candidate(doc, **kwargs)
    assert err.value.check == check
    assert isinstance(err.value, PipelineError) and err.value.error_code == "INVALID_INPUT"
    return err


# -- accepted -------------------------------------------------------------------------------
def test_accepts_real_normalize_output() -> None:
    out = normalize_tile(fb.make_png(1), TILE, max_png_bytes=1048576)
    result = validate_candidate(out, expected_tile=TILE)
    assert isinstance(result, ValidationResult) and result.profile == PROFILE_ID
    assert result.tile == (14, 14550, 6450)
    # fixture_builder.make_png(1): no-data where (x + y + 1) % 97 == 0.
    nodata = sum(1 for y in range(256) for x in range(256) if (x + y + 1) % 97 == 0)
    assert result.nodata_count == nodata == 663  # s=x+y in {96,193,290,387,484}: 97+194+221+124+27
    assert result.valid_count == N - 663
    assert result.warning is None
    assert result.min_cm is not None and result.max_cm is not None


def test_positive_zero_negative_and_nodata_counted() -> None:
    values = [0] * N
    values[0] = 1234
    values[1] = -120
    values[2] = None
    values[3] = None
    values[65535] = 8388607
    values[65534] = -8388607
    result = validate_candidate(candidate(values))
    assert result.stats() == {
        "valid_count": 65534,
        "nodata_count": 2,
        "min_cm": -8388607,
        "max_cm": 8388607,
    }


def test_min_max_ignore_nodata_and_handle_single_value() -> None:
    values = [None] * N
    values[100] = -5
    assert validate_candidate(candidate(values)).stats() == {
        "valid_count": 1, "nodata_count": 65535, "min_cm": -5, "max_cm": -5}
    values[200] = 7
    assert validate_candidate(candidate(values)).stats() == {
        "valid_count": 2, "nodata_count": 65534, "min_cm": -5, "max_cm": 7}


def test_decreasing_then_increasing_sequence() -> None:
    values = [10, 5, -3, 20] + [0] * (N - 4)
    assert validate_candidate(candidate(values)).stats() == {
        "valid_count": N, "nodata_count": 0, "min_cm": -3, "max_cm": 20}


@pytest.mark.parametrize(
    "values,stats",
    [
        ([0] * N, {"valid_count": N, "nodata_count": 0, "min_cm": 0, "max_cm": 0}),
        ([-1] * N, {"valid_count": N, "nodata_count": 0, "min_cm": -1, "max_cm": -1}),
        ([-8388607] * N,
         {"valid_count": N, "nodata_count": 0, "min_cm": -8388607, "max_cm": -8388607}),
        ([None] * N, {"valid_count": 0, "nodata_count": N, "min_cm": None, "max_cm": None}),
    ],
    ids=["all-zero", "all-negative", "all-min", "all-nodata"],
)
def test_uniform_tiles(values, stats) -> None:
    result = validate_candidate(candidate(values))
    assert result.stats() == stats
    assert result.warning == ("ALL_NODATA" if stats["valid_count"] == 0 else None)


def test_zero_is_not_nodata() -> None:
    result = validate_candidate(candidate([0] * N))
    assert result.nodata_count == 0 and result.warning is None


# -- rejected ---------------------------------------------------------------------------------
@pytest.mark.parametrize("length", [0, 1, N - 1, N + 1])
def test_wrong_length_rejected(length) -> None:
    rejected(candidate([0] * length), "values")


@pytest.mark.parametrize(
    "overrides,check",
    [
        ({"format": "hererisk-elevation-cm-json-v0.2"}, "format"),
        ({"format": None}, "format"),
        ({"width": 255}, "dimensions"),
        ({"height": 512}, "dimensions"),
        ({"width": 256.0}, "dimensions"),
        ({"width": True}, "dimensions"),
        ({"tile": {"z": 14, "x": 14550}}, "tile"),
        ({"tile": {"z": 14, "x": 14550, "y": 6450, "w": 0}}, "tile"),
        ({"tile": {"z": 14, "x": True, "y": 6450}}, "tile"),
        ({"tile": {"z": 14, "x": 14550.0, "y": 6450}}, "tile"),
        ({"tile": {"z": 14, "x": 16384, "y": 0}}, "tile"),
        ({"tile": {"z": 31, "x": 0, "y": 0}}, "tile"),
        ({"tile": [14, 14550, 6450]}, "tile"),
        ({"values_cm": tuple([0] * N)}, "values"),
        ({"values_cm": None}, "values"),
    ],
)
def test_invalid_fields_rejected(overrides, check) -> None:
    rejected(candidate([0] * N, **overrides), check)


def test_missing_and_unknown_keys_rejected() -> None:
    doc = candidate([0] * N)
    del doc["height"]
    rejected(doc, "keys")
    rejected(candidate([0] * N, extra=1), "keys")
    rejected([1, 2, 3], "keys")


def test_expected_tile_mismatch_rejected() -> None:
    rejected(candidate([0] * N), "tile", expected_tile={"z": 14, "x": 14551, "y": 6450})
    assert validate_candidate(candidate([0] * N), expected_tile=dict(TILE)).tile == (14, 14550, 6450)


@pytest.mark.parametrize(
    "bad",
    [True, False, 1.0, 0.0, float("nan"), float("inf"), "12", b"1", [1], {"v": 1},
     8388608, -8388608, 2**63],
    ids=["true", "false", "float", "float-zero", "nan", "inf", "str", "bytes", "list",
         "dict", "over-max", "under-min", "huge"],
)
@pytest.mark.parametrize("position", [0, 32768, N - 1])
def test_invalid_values_rejected(bad, position) -> None:
    values = [0] * N
    values[position] = bad
    rejected(candidate(values), "values")


def test_int_subclass_rejected() -> None:
    class Sneaky(int):
        pass

    values = [0] * N
    values[5] = Sneaky(3)
    rejected(candidate(values), "values")


# -- invariants -----------------------------------------------------------------------------------
def test_input_is_not_modified() -> None:
    values = [None, 0, -120, 1234] * (N // 4)
    doc = candidate(values)
    snapshot = copy.deepcopy(doc)
    validate_candidate(doc)
    assert doc == snapshot and doc["values_cm"] is values
    bad = candidate([0] * (N - 1) + [math.nan])
    bad_snapshot = copy.deepcopy(bad)
    with pytest.raises(CandidateRejected):
        validate_candidate(bad)
    assert bad["values_cm"][:-1] == bad_snapshot["values_cm"][:-1]
    assert math.isnan(bad["values_cm"][-1]) and set(bad) == set(bad_snapshot)


def test_result_is_immutable() -> None:
    result = validate_candidate(candidate([0] * N))
    with pytest.raises(AttributeError):
        result.valid_count = 0  # type: ignore[misc]


def test_module_is_pure_and_does_not_normalize() -> None:
    import ast

    tree = ast.parse(open(core.__file__, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add((node.module, tuple(a.name for a in node.names)))
        elif isinstance(node, ast.Import):
            imported |= {(a.name, ()) for a in node.names}
    modules = {m for m, _ in imported}
    assert modules <= {"__future__", "dataclasses", "typing", "hererisk.common.result",
                       "hererisk.elevation.normalize.convert",
                       "hererisk.elevation.download.download"}, modules
    from_convert = dict(imported)["hererisk.elevation.normalize.convert"]
    assert "normalize_tile" not in from_convert and "decode_rgb_rows" not in from_convert
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {"open", "normalize_tile", "decode_rgb_rows", "png", "zlib"}
