"""Contract tests: Phase 1-C.2 validated candidate reader.

Every test reads artifacts produced by the real Phase 1-B fixture pipeline
(Download -> Normalize -> Validate through the Orchestrator). Expected values
come from the fixture PNG generation rule or from hand-placed pixel values.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
import zlib

import pytest

import fixture_builder as fb
from hererisk.common.orchestrator import DownloadRequest
from hererisk.common.result import Status
from hererisk.common.storage import ApiDataArea
from hererisk.elevation.lookup.reader import (
    CANDIDATE_CORRUPTED,
    CANDIDATE_INVALID,
    EVIDENCE_INCONSISTENT,
    INVALID_COORDINATES,
    INVALID_RUN,
    NOT_FIXTURE,
    NOT_VALIDATED,
    TILE_NOT_IN_RUN,
    PointElevation,
    ReadRejected,
    read_point_elevation,
)
from hererisk.elevation.normalize.stage import NormalizeStage
from hererisk.elevation.validate.stage import ValidateStage

Z = 14
TOKYO = (("13",), "fixture-dem-png-tokyo")  # tiles (14550, 6450), (14551, 6450): seeds 2, 3
OSAKA = (("27",), "fixture-dem-png-osaka")  # tile (14370, 6495): seed 1
SEEDS = {(14370, 6495): 1, (14550, 6450): 2, (14551, 6450): 3}  # build_tree: sorted tiles, seed+1


def run_pipeline(harness, target=TOKYO):
    regions, source = target
    orch = harness.orchestrator(stages={"elevation": (NormalizeStage(), ValidateStage())})
    results = orch.run_fixture_pipeline(DownloadRequest("elevation", regions, source))
    assert [r.status for r in results] == [Status.SUCCESS] * 3, results
    return results[0].run_id


def centre(tx, ty, px, py, z=Z):
    n = 256 * 2**z
    lon = (tx * 256 + px + 0.5) / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ty * 256 + py + 0.5) / n))))
    return lat, lon


def builder_value(seed, x, y):
    """fixture_builder.make_png rule (independent of the code under test)."""
    return None if (x + y + seed) % 97 == 0 else (seed * 1000 + x * 37 + y * 11) % 400000


def read(harness, run_id, lat, lon, z=Z):
    with ApiDataArea(harness.data_root, "elevation") as area:
        return read_point_elevation(area, run_id, lat, lon, z)


def rejected(harness, run_id, lat, lon, reason, code, z=Z):
    with pytest.raises(ReadRejected) as err:
        read(harness, run_id, lat, lon, z)
    assert (err.value.reason, err.value.error_code) == (reason, code)


def candidate_path(harness, run_id, index=0):
    record = json.loads((harness.api_root / f"records/normalizations/{run_id}.json").read_bytes())
    acq = record["outputs"][index]["acquisition_id"]
    return harness.api_root / f"work/normalized/{run_id}/{acq}.json"


# -- values ------------------------------------------------------------------------------------
def test_one_tile_values(harness) -> None:
    run_id = run_pipeline(harness, OSAKA)
    before = harness.files()
    for px, py in [(0, 0), (37, 200), (255, 255), (96, 0), (128, 64)]:
        result = read(harness, run_id, *centre(14370, 6495, px, py))
        assert isinstance(result, PointElevation)
        assert (result.z, result.tile_x, result.tile_y) == (14, 14370, 6495)
        assert (result.pixel_x, result.pixel_y) == (px, py)
        assert result.elevation_cm == builder_value(1, px, py)
        assert result.nodata is (result.elevation_cm is None)
        assert result.run_id == run_id
    assert read(harness, run_id, *centre(14370, 6495, 96, 0)).nodata  # (96+0+1) % 97 == 0
    assert harness.files() == before  # read-only


def test_two_tiles_values_and_identifiers(harness) -> None:
    run_id = run_pipeline(harness, TOKYO)
    record = json.loads((harness.api_root / f"records/normalizations/{run_id}.json").read_bytes())
    by_tile = {(i["tile"]["x"], i["tile"]["y"]): o
               for i, o in zip(record["inputs"], record["outputs"])}
    for tx in (14550, 14551):
        seed = SEEDS[(tx, 6450)]
        for px, py in [(0, 0), (200, 17), (255, 255)]:
            result = read(harness, run_id, *centre(tx, 6450, px, py))
            assert result.tile_x == tx
            assert result.elevation_cm == builder_value(seed, px, py)
            assert result.acquisition_id == by_tile[(tx, 6450)]["acquisition_id"]
            assert result.candidate_sha256 == by_tile[(tx, 6450)]["candidate_sha256"]
    doc = read(harness, run_id, *centre(14551, 6450, 1, 2)).to_dict()
    assert set(doc) == {"run_id", "acquisition_id", "candidate_sha256", "tile", "pixel",
                        "elevation_cm", "nodata"}
    assert doc["tile"] == {"z": 14, "x": 14551, "y": 6450} and doc["pixel"] == {"x": 1, "y": 2}


def _png_with(values: dict[tuple[int, int], tuple[int, int, int]]) -> bytes:
    rows = bytearray()
    for y in range(256):
        rows.append(0)
        for x in range(256):
            rows += bytes(values.get((x, y), (0, 0, 100)))  # default 100 cm
    ihdr = struct.pack(">IIBBBBB", 256, 256, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + fb._chunk(b"IHDR", ihdr)
            + fb._chunk(b"IDAT", zlib.compress(bytes(rows))) + fb._chunk(b"IEND", b""))


def test_zero_negative_and_nodata_are_distinct(harness) -> None:
    special = {(10, 20): (0, 0, 0), (11, 20): (255, 255, 136), (12, 20): (128, 0, 0),
               (13, 20): (0, 4, 210)}
    (harness.fixture_root / "tiles/dem_png/14/14370/6495.png").write_bytes(_png_with(special))
    run_id = run_pipeline(harness, OSAKA)
    zero = read(harness, run_id, *centre(14370, 6495, 10, 20))
    neg = read(harness, run_id, *centre(14370, 6495, 11, 20))
    nodata = read(harness, run_id, *centre(14370, 6495, 12, 20))
    pos = read(harness, run_id, *centre(14370, 6495, 13, 20))
    assert (zero.elevation_cm, zero.nodata) == (0, False)
    assert (neg.elevation_cm, neg.nodata) == (-120, False)
    assert (nodata.elevation_cm, nodata.nodata) == (None, True)
    assert (pos.elevation_cm, pos.nodata) == (1234, False)
    assert type(zero.elevation_cm) is int


def test_zoom_is_explicit_not_fixed(harness) -> None:
    run_id = run_pipeline(harness, OSAKA)
    lat, lon = centre(14370, 6495, 5, 5)
    # Same point at zoom 13 belongs to tile (7185, 3247): not in the run -> not found.
    rejected(harness, run_id, lat, lon, TILE_NOT_IN_RUN, "TARGET_UNCONFIGURED", z=13)
    assert read(harness, run_id, lat, lon, 14).elevation_cm == builder_value(1, 5, 5)


# -- not found / not validated / invalid input -------------------------------------------------------
def test_tile_not_in_run_is_not_nodata(harness) -> None:
    run_id = run_pipeline(harness, OSAKA)
    rejected(harness, run_id, *centre(14550, 6450, 0, 0), TILE_NOT_IN_RUN, "TARGET_UNCONFIGURED")
    rejected(harness, run_id, 35.0, 139.0, TILE_NOT_IN_RUN, "TARGET_UNCONFIGURED")


@pytest.mark.parametrize("lat,lon,z", [(91.0, 0.0, 14), (0.0, 180.0, 14), (math.nan, 0.0, 14),
                                       (True, 0.0, 14), (35.0, 139.0, 31), (35.0, 139.0, 14.0)])
def test_invalid_coordinates(harness, lat, lon, z) -> None:
    run_id = run_pipeline(harness, OSAKA)
    rejected(harness, run_id, lat, lon, INVALID_COORDINATES, "INVALID_INPUT", z=z)


@pytest.mark.parametrize("run_id", ["not-a-uuid", "../x", None, "11111111-1111-1111-8111-111111111111"])
def test_invalid_run_id(harness, run_id) -> None:
    rejected(harness, run_id, 35.0, 139.0, INVALID_RUN, "INVALID_INPUT")


def test_unknown_run_is_not_validated(harness) -> None:
    rejected(harness, "11111111-1111-4111-8111-111111111111", 35.0, 139.0,
             NOT_VALIDATED, "INVALID_INPUT")


def test_run_without_validate_record_rejected(harness) -> None:
    orch = harness.orchestrator(stages={"elevation": (NormalizeStage(),)})
    dl, norm = orch.run_fixture_pipeline(DownloadRequest("elevation", *OSAKA))
    assert norm.status is Status.SUCCESS
    rejected(harness, dl.run_id, *centre(14370, 6495, 0, 0), NOT_VALIDATED, "INVALID_INPUT")


def test_failed_validation_rejected(harness) -> None:
    run_id = run_pipeline(harness, OSAKA)
    path = harness.api_root / f"records/validations/{run_id}.json"
    record = json.loads(path.read_bytes())
    record.update(status="FAILED", error_code="VALIDATION_FAILED")
    record["validation"]["checks"]["values_nodata"] = "failed"
    path.unlink()
    path.write_bytes(json.dumps(record).encode())
    rejected(harness, run_id, *centre(14370, 6495, 0, 0), NOT_VALIDATED, "INVALID_INPUT")


def test_non_fixture_root_rejected(harness) -> None:
    run_id = run_pipeline(harness, OSAKA)
    (harness.data_root / ".hererisk-fixture-data-root").unlink()
    rejected(harness, run_id, *centre(14370, 6495, 0, 0), NOT_FIXTURE, "APPROVAL_REQUIRED")


# -- corruption / inconsistency ----------------------------------------------------------------------------
def _rewrite(path, data: bytes) -> None:
    path.unlink()
    path.write_bytes(data)


def test_candidate_hash_mismatch(harness) -> None:
    run_id = run_pipeline(harness, OSAKA)
    path = candidate_path(harness, run_id)
    _rewrite(path, path.read_bytes().replace(b"1000", b"1001", 1))
    rejected(harness, run_id, *centre(14370, 6495, 0, 0), CANDIDATE_CORRUPTED,
             "STORAGE_INTEGRITY_FAILED")


def test_missing_candidate(harness) -> None:
    run_id = run_pipeline(harness, OSAKA)
    candidate_path(harness, run_id).unlink()
    rejected(harness, run_id, *centre(14370, 6495, 0, 0), CANDIDATE_CORRUPTED,
             "STORAGE_INTEGRITY_FAILED")


def test_normalize_record_hash_mismatch(harness) -> None:
    run_id = run_pipeline(harness, OSAKA)
    path = harness.api_root / f"records/normalizations/{run_id}.json"
    _rewrite(path, path.read_bytes() + b"\n")  # still valid JSON, different bytes
    rejected(harness, run_id, *centre(14370, 6495, 0, 0), EVIDENCE_INCONSISTENT,
             "RECOVERY_REQUIRED")


def _forge_consistent_candidate(harness, run_id, data: bytes) -> None:
    """Replace the candidate and re-sign the whole chain so every hash agrees."""
    cpath = candidate_path(harness, run_id)
    _rewrite(cpath, data)
    npath = harness.api_root / f"records/normalizations/{run_id}.json"
    nrec = json.loads(npath.read_bytes())
    nrec["outputs"][0].update(candidate_sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
    nbytes = json.dumps(nrec).encode()
    _rewrite(npath, nbytes)
    vpath = harness.api_root / f"records/validations/{run_id}.json"
    vrec = json.loads(vpath.read_bytes())
    vrec["outputs"] = nrec["outputs"]
    vrec["validation"]["normalize_record_sha256"] = hashlib.sha256(nbytes).hexdigest()
    _rewrite(vpath, json.dumps(vrec).encode())


@pytest.mark.parametrize(
    "mutate",
    [
        lambda raw: raw.replace(b"[", b"[NaN,", 1),  # non-standard JSON
        lambda raw: raw[:-1],  # truncated JSON
        lambda raw: raw.replace(b'"width":256', b'"width":256,"width":256', 1),  # duplicate key
        lambda raw: raw.replace(b'"width":256', b'"width":255', 1),  # profile violation
    ],
    ids=["nan", "truncated", "duplicate-key", "width"],
)
def test_invalid_candidate_rejected_even_if_hashes_agree(harness, mutate) -> None:
    run_id = run_pipeline(harness, OSAKA)
    _forge_consistent_candidate(harness, run_id, mutate(candidate_path(harness, run_id).read_bytes()))
    rejected(harness, run_id, *centre(14370, 6495, 0, 0), CANDIDATE_INVALID, "VALIDATION_FAILED")


def test_value_changed_with_consistent_hashes_caught_by_statistics(harness) -> None:
    run_id = run_pipeline(harness, OSAKA)
    doc = json.loads(candidate_path(harness, run_id).read_bytes())
    doc["values_cm"][0] = 3999999 if doc["values_cm"][0] != 3999999 else 0
    _forge_consistent_candidate(harness, run_id, json.dumps(doc, separators=(",", ":")).encode())
    rejected(harness, run_id, *centre(14370, 6495, 0, 0), EVIDENCE_INCONSISTENT,
             "RECOVERY_REQUIRED")


@pytest.mark.parametrize(
    "edit",
    [
        lambda v, n: v["validation"].update(normalize_record_ref="normalizations/other.json"),
        lambda v, n: v.update(outputs=[]),
        lambda v, n: v["validation"]["tiles"].clear(),
        lambda v, n: v.update(source_raw_sha256="0" * 64),
    ],
    ids=["normalize-ref", "outputs", "tiles", "source-hash"],
)
def test_validation_record_inconsistencies(harness, edit) -> None:
    run_id = run_pipeline(harness, OSAKA)
    vpath = harness.api_root / f"records/validations/{run_id}.json"
    vrec = json.loads(vpath.read_bytes())
    edit(vrec, None)
    _rewrite(vpath, json.dumps(vrec).encode())
    with pytest.raises(ReadRejected) as err:
        read(harness, run_id, *centre(14370, 6495, 0, 0))
    assert err.value.reason == EVIDENCE_INCONSISTENT


def test_corrupt_validation_record(harness) -> None:
    run_id = run_pipeline(harness, OSAKA)
    _rewrite(harness.api_root / f"records/validations/{run_id}.json", b"{not json")
    rejected(harness, run_id, *centre(14370, 6495, 0, 0), EVIDENCE_INCONSISTENT,
             "RECOVERY_REQUIRED")


def test_only_the_needed_candidate_is_read(harness, monkeypatch) -> None:
    run_id = run_pipeline(harness, TOKYO)
    reads = []
    real = ApiDataArea.read_bytes

    def tracking(self, loc, max_bytes):
        reads.append(tuple(loc))
        return real(self, loc, max_bytes)

    monkeypatch.setattr(ApiDataArea, "read_bytes", tracking)
    read(harness, run_id, *centre(14551, 6450, 3, 4))
    candidates = [r for r in reads if r[:2] == ("work", "normalized")]
    assert len(candidates) == 1
    record = json.loads((harness.api_root / f"records/normalizations/{run_id}.json").read_bytes())
    assert candidates[0][-1] == f"{record['outputs'][1]['acquisition_id']}.json"
    assert not any(r[:2] == ("work", "acquisitions") for r in reads)  # PNGs untouched


def test_reader_never_writes(harness) -> None:
    run_id = run_pipeline(harness, TOKYO)
    before = harness.files()
    for tx in (14550, 14551):
        read(harness, run_id, *centre(tx, 6450, 9, 9))
    with pytest.raises(ReadRejected):
        read(harness, run_id, 35.0, 139.0)
    assert harness.files() == before


@pytest.mark.parametrize(
    "edit",
    [
        lambda r: r.update(status="FAILED"),  # checks still all "passed"
        lambda r: r.update(error_code="VALIDATION_FAILED"),
        lambda r: r["validation"]["checks"].update(counts_stats="not_run"),
    ],
    ids=["status-only", "error-code-only", "check-not-run"],
)
def test_each_success_condition_is_required(harness, edit) -> None:
    run_id = run_pipeline(harness, OSAKA)
    path = harness.api_root / f"records/validations/{run_id}.json"
    record = json.loads(path.read_bytes())
    edit(record)
    _rewrite(path, json.dumps(record).encode())
    rejected(harness, run_id, *centre(14370, 6495, 0, 0), NOT_VALIDATED, "INVALID_INPUT")
