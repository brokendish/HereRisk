"""Contract tests: Phase 1-B.3-A Normalize stage (Download evidence -> candidates -> record).

Each test runs a real fixture Download through the Orchestrator, rebuilds the
same fixed DownloadPlan the Orchestrator used, and calls the Normalize stage.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import struct
import zlib
from datetime import datetime, timezone
from types import MappingProxyType

import pytest

import fixture_builder as fb
from hererisk.common.authorization import ExecutionContext
from hererisk.common.logging import ListSink, StructuredLogger
from hererisk.common.orchestrator import DownloadPlan, DownloadRequest, _canonical_json
from hererisk.common.result import ModuleResult, Status
from hererisk.common.config import sha256_hex
from hererisk.common.storage import ApiDataArea, StorageError
from hererisk.elevation.download.download import ElevationDownload
from hererisk.elevation.download import record as rec
from hererisk.elevation.normalize.convert import normalize_tile
from hererisk.elevation.normalize.stage import NormalizeStage, candidate_bytes
from hererisk.elevation.validate.core import validate_candidate

FIXED_NOW = datetime(2026, 10, 17, 3, 4, 5, tzinfo=timezone.utc)


def build_plan(harness, result, regions=("13",), source="fixture-dem-png-tokyo") -> DownloadPlan:
    orch = harness.orchestrator()
    definition = orch._config.load("api", "elevation", "sources")
    auth = orch._authorizer.authorize(api_id="elevation", operation="download",
                                      source_ref=source, region_codes=tuple(sorted(regions)),
                                      definition=definition)
    request = DownloadRequest("elevation", tuple(regions), source)
    effective = _canonical_json(orch._effective_document(
        result.run_id, request, definition, auth, ElevationDownload(harness.transport)))
    return DownloadPlan(
        run_id=result.run_id, api_id="elevation", source_ref=source,
        region_codes=tuple(sorted(regions)), definition=definition,
        effective_configuration_ref=f"configurations/{result.run_id}/effective.json",
        effective_configuration_sha256=sha256_hex(effective), authorization=auth, resume=False)


def normalize(harness, plan, result, *, area_cls=ApiDataArea, stage=None):
    with area_cls(harness.data_root, "elevation") as area:
        return (stage or NormalizeStage(clock=lambda: FIXED_NOW)).run(
            plan, result, area, StructuredLogger(ListSink()))


def downloaded(harness, regions=("13",), source="fixture-dem-png-tokyo"):
    result = harness.run(regions=regions, source=source)
    assert result.status is Status.SUCCESS
    return result, build_plan(harness, result, regions, source)


def subtree(harness, *prefixes):
    return {k: v for k, v in harness.files().items() if k.startswith(prefixes)}


DOWNLOAD_EVIDENCE = ("elevation/work/acquisitions", "elevation/records/acquisitions",
                     "elevation/records/commits", "elevation/records/configurations")
NORMALIZE_OUT = ("elevation/work/normalized", "elevation/records/normalizations")


# -- success ------------------------------------------------------------------------------
def test_one_tile_normalized_and_recorded(harness) -> None:
    dl, plan = downloaded(harness, ("27",), "fixture-dem-png-osaka")
    before = subtree(harness, *DOWNLOAD_EVIDENCE)
    result = normalize(harness, plan, dl)
    assert result.status is Status.SUCCESS and result.module == "normalize"
    assert result.message == "Normalization committed" and result.error_code is None
    (art,) = result.artifacts
    acq = dl.artifacts[0].acquisition_id
    assert art.acquisition_id == art.artifact_id == acq
    assert art.record_ref == f"normalizations/{dl.run_id}.json"

    cand_path = harness.api_root / f"work/normalized/{dl.run_id}/{acq}.json"
    data = cand_path.read_bytes()
    assert hashlib.sha256(data).hexdigest() == art.sha256 and len(data) == art.size_bytes
    assert b" " not in data and b"\n" not in data  # compact
    assert len(data) <= 1024 * 1024
    png = (harness.api_root / f"work/acquisitions/{dl.run_id}/{acq}/original.png").read_bytes()
    expected = normalize_tile(png, {"z": 14, "x": 14370, "y": 6495}, max_png_bytes=1048576)
    assert json.loads(data) == expected and data == candidate_bytes(expected)
    assert list(json.loads(data)) == ["format", "tile", "width", "height", "values_cm"]

    record = json.loads((harness.api_root / f"records/normalizations/{dl.run_id}.json").read_bytes())
    assert record["status"] == "SUCCESS" and record["error_code"] is None
    assert record["completed_at"] == "2026-10-17T03:04:05Z"
    assert record["module"] == "normalize" and record["profile"] == "hererisk-elevation-cm-json-v0.1"
    assert record["validation"] is None and record["execution_context"] == "fixture"
    rec_file = harness.api_root / "records" / dl.artifacts[0].record_ref
    assert record["inputs"] == [{
        "acquisition_id": acq,
        "record_ref": dl.artifacts[0].record_ref,
        "record_sha256": hashlib.sha256(rec_file.read_bytes()).hexdigest(),
        "artifact_sha256": dl.artifacts[0].sha256,
        "size_bytes": dl.artifacts[0].size_bytes,
        "tile": {"z": 14, "x": 14370, "y": 6495},
    }]
    assert record["outputs"] == [{"acquisition_id": acq,
                                  "candidate_ref": f"normalized/{dl.run_id}/{acq}.json",
                                  "candidate_sha256": art.sha256, "size_bytes": art.size_bytes}]
    eff = harness.api_root / f"records/configurations/{dl.run_id}/effective.json"
    assert record["effective_configuration"]["sha256"] == hashlib.sha256(eff.read_bytes()).hexdigest()
    assert subtree(harness, *DOWNLOAD_EVIDENCE) == before  # originals / records unchanged
    # The stored candidate passes the Validate core (consumer-side sanity check).
    assert validate_candidate(json.loads(data), expected_tile={"z": 14, "x": 14370, "y": 6495})


def test_two_tiles_keep_correspondence(harness) -> None:
    dl, plan = downloaded(harness)
    result = normalize(harness, plan, dl)
    assert result.status is Status.SUCCESS
    assert [a.acquisition_id for a in result.artifacts] == [a.acquisition_id for a in dl.artifacts]
    for dl_art, n_art in zip(dl.artifacts, result.artifacts):
        record = json.loads((harness.api_root / "records" / dl_art.record_ref).read_bytes())
        cand = json.loads((harness.api_root /
                           f"work/normalized/{dl.run_id}/{n_art.acquisition_id}.json").read_bytes())
        assert cand["tile"] == record["tile"]
    tiles = [json.loads((harness.api_root / f"work/normalized/{dl.run_id}/{a.acquisition_id}.json")
                        .read_bytes())["tile"]["x"] for a in result.artifacts]
    assert tiles == [14550, 14551]


def test_rerun_after_success_reuses_without_new_files(harness) -> None:
    dl, plan = downloaded(harness)
    first = normalize(harness, plan, dl)
    before = harness.files()
    again = normalize(harness, plan, dl, stage=NormalizeStage(clock=lambda: datetime.now(timezone.utc)))
    assert again == first and harness.files() == before


def test_only_normalize_areas_written(harness) -> None:
    for rel in ("dl/current/g/x.png", "rel/versions/v/x", "registry.json"):
        p = harness.api_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"keep")
    dl, plan = downloaded(harness)
    before = harness.files()
    assert normalize(harness, plan, dl).status is Status.SUCCESS
    after = harness.files()
    assert all(after[k] == v for k, v in before.items())
    assert set(after) - set(before) and all(k.startswith(NORMALIZE_OUT) for k in set(after) - set(before))


# -- preconditions: nothing written ----------------------------------------------------------
def assert_rejected(harness, result, code, status=None) -> None:
    assert result.error_code == code, result
    assert result.artifacts == ()
    if status:
        assert result.status is status
    assert subtree(harness, *NORMALIZE_OUT) == {}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: ModuleResult.error(r.run_id, "download", "HTTP_404"),
        lambda r: dataclasses.replace(r, module="normalize"),
        lambda r: dataclasses.replace(r, run_id="11111111-1111-4111-8111-111111111111"),
        lambda r: "SUCCESS",
    ],
    ids=["failed", "wrong-module", "wrong-run", "not-a-result"],
)
def test_download_result_must_be_success_of_this_run(harness, mutate) -> None:
    dl, plan = downloaded(harness)
    assert_rejected(harness, normalize(harness, plan, mutate(dl)), "INVALID_INPUT", Status.FAILED)


def test_partial_download_is_not_accepted(harness) -> None:
    (harness.fixture_root / "tiles/dem_png/14/14551/6450.png").unlink()
    dl = harness.run()
    assert dl.status is Status.FAILED and len(dl.artifacts) == 1
    plan = build_plan(harness, dl)
    assert_rejected(harness, normalize(harness, plan, dl), "INVALID_INPUT")
    fake = ModuleResult.success(dl.run_id, "download", dl.artifacts)  # forged SUCCESS
    assert_rejected(harness, normalize(harness, plan, fake), "RECOVERY_REQUIRED", Status.BLOCKED)


def test_result_artifacts_must_match_evidence(harness) -> None:
    dl, plan = downloaded(harness)
    fake = ModuleResult.success(dl.run_id, "download", tuple(reversed(dl.artifacts)))
    assert_rejected(harness, normalize(harness, plan, fake), "RECOVERY_REQUIRED")


def _forge_record(harness, dl, art, edit) -> None:
    record_path = harness.api_root / "records" / art.record_ref
    marker_path = harness.api_root / f"records/commits/{art.acquisition_id}.json"
    record = json.loads(record_path.read_bytes())
    edit(record)
    data = rec.to_bytes(record)
    record_path.write_bytes(data)
    marker = json.loads(marker_path.read_bytes())
    marker["record_sha256"] = hashlib.sha256(data).hexdigest()
    marker_path.write_bytes(rec.to_bytes(marker))


@pytest.mark.parametrize(
    "tamper",
    [
        lambda h, dl: _forge_record(h, dl, dl.artifacts[1], lambda r: r["provider"].update(name="x")),
        lambda h, dl: _forge_record(h, dl, dl.artifacts[0], lambda r: r["tile"].update(x=1)),
        lambda h, dl: (h.api_root / "records" / dl.artifacts[0].record_ref).write_bytes(b"{}"),
        lambda h, dl: (h.api_root / f"records/commits/{dl.artifacts[1].acquisition_id}.json").unlink(),
        lambda h, dl: (h.api_root / f"work/acquisitions/{dl.run_id}/{dl.artifacts[0].acquisition_id}"
                       "/original.png").write_bytes(b"\x89PNG tampered"),
    ],
    ids=["forged-provider", "forged-tile", "broken-record", "missing-marker", "tampered-png"],
)
def test_bad_download_evidence_creates_no_candidate(harness, tamper) -> None:
    dl, plan = downloaded(harness)
    tamper(harness, dl)
    before = harness.files()
    result = normalize(harness, plan, dl)
    assert_rejected(harness, result, "RECOVERY_REQUIRED", Status.BLOCKED)
    assert harness.files() == before


def test_snapshot_mismatch_rejected(harness) -> None:
    dl, plan = downloaded(harness)
    eff = harness.api_root / f"records/configurations/{dl.run_id}/effective.json"
    eff.write_bytes(eff.read_bytes().replace(b'"13"', b'"14"'))
    assert_rejected(harness, normalize(harness, plan, dl), "RECOVERY_REQUIRED")


def test_plan_from_latest_configuration_is_not_a_substitute(harness) -> None:
    dl, plan = downloaded(harness)
    definition = fb.fixture_definition()
    definition["definition_revision"] = "fixture-2"
    harness.rebuild(definition_bytes=fb.dump(definition))
    newer = build_plan(harness, dl)  # same run, re-read *latest* definition
    assert_rejected(harness, normalize(harness, newer, dl), "RECOVERY_REQUIRED")


@pytest.mark.parametrize("bad", [0, -1, True, None, 1.5, float("nan"), "1048576"])
def test_invalid_max_tile_bytes_rejected_at_boundary(harness, bad) -> None:
    """B1-F01: only a validated positive int reaches normalize_tile()."""
    dl, plan = downloaded(harness)
    policy = dict(plan.authorization.policy, max_tile_bytes=bad)
    bad_plan = dataclasses.replace(plan, authorization=dataclasses.replace(
        plan.authorization, policy=MappingProxyType(policy)))
    assert_rejected(harness, normalize(harness, bad_plan, dl), "INVALID_CONFIGURATION")


def test_production_context_blocked(harness) -> None:
    dl, plan = downloaded(harness)
    prod = dataclasses.replace(plan, authorization=dataclasses.replace(
        plan.authorization, context=ExecutionContext.PRODUCTION))
    assert_rejected(harness, normalize(harness, prod, dl), "APPROVAL_REQUIRED", Status.BLOCKED)


# -- failures during conversion / storage ---------------------------------------------------------
def _undecodable_png() -> bytes:
    """Container-valid (passes Download), but an invalid scanline filter type."""
    raw = bytearray((b"\x00" + b"\x00\x00\x01" * 256) * 256)
    raw[0] = 5
    ihdr = struct.pack(">IIBBBBB", 256, 256, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + fb._chunk(b"IHDR", ihdr)
            + fb._chunk(b"IDAT", zlib.compress(bytes(raw))) + fb._chunk(b"IEND", b""))


def test_second_tile_failure_is_not_success(harness) -> None:
    (harness.fixture_root / "tiles/dem_png/14/14551/6450.png").write_bytes(_undecodable_png())
    dl, plan = downloaded(harness)  # Download only checks the container: SUCCESS
    before = subtree(harness, *DOWNLOAD_EVIDENCE)
    result = normalize(harness, plan, dl)
    assert result.status is Status.FAILED and result.error_code == "PNG_INVALID"
    assert result.artifacts == ()
    record = json.loads((harness.api_root / f"records/normalizations/{dl.run_id}.json").read_bytes())
    assert record["status"] == "FAILED" and record["error_code"] == "PNG_INVALID"
    assert [o["acquisition_id"] for o in record["outputs"]] == [dl.artifacts[0].acquisition_id]
    assert len(record["inputs"]) == 2
    assert subtree(harness, *DOWNLOAD_EVIDENCE) == before
    # Re-running never turns the failed attempt into SUCCESS or overwrites it.
    snapshot = harness.files()
    again = normalize(harness, plan, dl)
    assert again.status is Status.BLOCKED and again.error_code == "RECOVERY_REQUIRED"
    assert harness.files() == snapshot


def test_uncommitted_candidate_blocks_without_overwrite(harness) -> None:
    dl, plan = downloaded(harness)
    stray = harness.api_root / f"work/normalized/{dl.run_id}/{dl.artifacts[0].acquisition_id}.json"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b'{"partial":true}')
    before = harness.files()
    result = normalize(harness, plan, dl)
    assert result.error_code == "RECOVERY_REQUIRED" and result.artifacts == ()
    assert harness.files() == before and stray.read_bytes() == b'{"partial":true}'


@pytest.mark.parametrize(
    "tamper",
    [
        lambda p: p.write_bytes(p.read_bytes().replace(b"1000", b"1001", 1)),
        lambda p: p.unlink(),
        lambda p: p.with_name("extra.json").write_bytes(b"{}"),
    ],
    ids=["edited", "missing", "extra"],
)
def test_tampered_candidates_block_reuse(harness, tamper) -> None:
    dl, plan = downloaded(harness)
    assert normalize(harness, plan, dl).status is Status.SUCCESS
    cand = harness.api_root / f"work/normalized/{dl.run_id}/{dl.artifacts[0].acquisition_id}.json"
    tamper(cand)
    before = harness.files()
    result = normalize(harness, plan, dl)
    assert result.error_code == "RECOVERY_REQUIRED" and harness.files() == before


def failing_area(prefix):
    class FailingArea(ApiDataArea):
        def write_new(self, loc, data):
            if tuple(loc[:2]) == prefix:
                raise StorageError("STORAGE_FULL", "injected")
            return super().write_new(loc, data)

    return FailingArea


def test_candidate_write_failure(harness) -> None:
    dl, plan = downloaded(harness)
    result = normalize(harness, plan, dl, area_cls=failing_area(("work", "normalized")))
    assert result.status is Status.FAILED and result.error_code == "STORAGE_FULL"
    record = json.loads((harness.api_root / f"records/normalizations/{dl.run_id}.json").read_bytes())
    assert record["status"] == "FAILED" and record["outputs"] == []


def test_record_write_failure_is_not_success(harness) -> None:
    dl, plan = downloaded(harness)
    result = normalize(harness, plan, dl, area_cls=failing_area(("records", "normalizations")))
    assert result.status is Status.FAILED and result.error_code == "RECORD_COMMIT_FAILED"
    assert result.artifacts == ()
    assert not (harness.api_root / f"records/normalizations/{dl.run_id}.json").exists()
    # Candidates exist without a record: the next attempt must stop, not regenerate.
    again = normalize(harness, plan, dl)
    assert again.error_code == "RECOVERY_REQUIRED"


def test_tiles_are_converted_one_at_a_time(harness, monkeypatch) -> None:
    """normalize_tile is called once per tile and its output is dropped before the next."""
    import gc
    import weakref

    from hererisk.elevation.normalize import stage as stage_mod

    dl, plan = downloaded(harness)
    alive: list[weakref.ref] = []
    real = stage_mod.normalize_tile

    class Tracked(dict):
        pass

    def tracking(png_bytes, tile, *, max_png_bytes):
        gc.collect()
        assert all(r() is None for r in alive), "previous tile's array still alive"
        out = Tracked(real(png_bytes, tile, max_png_bytes=max_png_bytes))
        alive.append(weakref.ref(out))
        return out

    monkeypatch.setattr(stage_mod, "normalize_tile", tracking)
    assert normalize(harness, plan, dl).status is Status.SUCCESS
    assert len(alive) == 2


def test_clean_subset_of_planned_tiles_rejected(harness) -> None:
    """Committed evidence for only some planned tiles (no leftovers) is not enough."""
    import shutil

    (harness.fixture_root / "tiles/dem_png/14/14551/6450.png").unlink()
    dl = harness.run()
    assert dl.status is Status.FAILED and len(dl.artifacts) == 1
    for leftover in (harness.api_root / f"work/download/{dl.run_id}").iterdir():
        shutil.rmtree(leftover)  # simulate an operator-cleaned partial run
    plan = build_plan(harness, dl)
    fake = ModuleResult.success(dl.run_id, "download", dl.artifacts)
    assert_rejected(harness, normalize(harness, plan, fake), "RECOVERY_REQUIRED", Status.BLOCKED)


def test_original_swapped_after_verification_is_not_decoded(harness, monkeypatch) -> None:
    dl, plan = downloaded(harness)
    real = ApiDataArea.read_bytes

    def swapped(self, loc, max_bytes):
        data = real(self, loc, max_bytes)
        return fb.make_png(99) if loc.name == "original.png" else data

    monkeypatch.setattr(ApiDataArea, "read_bytes", swapped)
    result = normalize(harness, plan, dl)
    assert result.status is Status.FAILED and result.error_code == "STORAGE_INTEGRITY_FAILED"
    assert not list((harness.api_root / "work/normalized").rglob("*.json"))


@pytest.mark.parametrize(
    "edit",
    [
        lambda r: r.update(authorization_ref="fixture-other"),
        lambda r: r.update(source_raw_sha256="0" * 64),
        lambda r: r["inputs"][0].update(record_sha256="1" * 64),
        lambda r: r["effective_configuration"].update(sha256="2" * 64),
        lambda r: r.update(status="FAILED", error_code="PNG_INVALID"),
    ],
    ids=["auth", "source-hash", "input-hash", "effective", "status"],
)
def test_edited_success_record_blocks_reuse(harness, edit) -> None:
    dl, plan = downloaded(harness)
    assert normalize(harness, plan, dl).status is Status.SUCCESS
    path = harness.api_root / f"records/normalizations/{dl.run_id}.json"
    record = json.loads(path.read_bytes())
    edit(record)
    path.write_bytes(json.dumps(record).encode())
    before = harness.files()
    result = normalize(harness, plan, dl)
    assert result.error_code == "RECOVERY_REQUIRED" and harness.files() == before
