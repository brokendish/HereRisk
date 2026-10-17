"""Contract tests: Phase 1-B.3-B fixture pipeline Download -> Normalize -> Validate.

Reuses the existing Harness and the Normalize-stage helpers (build_plan etc.).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import stat
import struct
import subprocess
import sys
import zlib

import pytest

import fixture_builder as fb
from hererisk.common.authorization import ProductionAuthorizer
from hererisk.common.orchestrator import DownloadRequest
from hererisk.common.result import ERROR_CODES, ModuleResult, Status
from hererisk.common.storage import ApiDataArea, StorageError
from hererisk.elevation.normalize.stage import NormalizeStage, candidate_bytes
from hererisk.elevation.validate.stage import CHECKS, ValidateStage
from test_normalize_stage import (
    DOWNLOAD_EVIDENCE,
    _undecodable_png,
    build_plan,
    normalize,
    stage_authorization,
    subtree,
)

TOKYO = (("13",), "fixture-dem-png-tokyo")
OSAKA = (("27",), "fixture-dem-png-osaka")
STAGES_OUT = ("elevation/work/normalized", "elevation/records/normalizations",
              "elevation/records/validations")


def stages():
    return {"elevation": (NormalizeStage(), ValidateStage())}


def pipeline(harness, target=TOKYO, resume=None, **kw):
    regions, source = target
    orch = harness.orchestrator(stages=kw.pop("stages", None) or stages(), **kw)
    results = orch.run_fixture_pipeline(
        DownloadRequest("elevation", regions, source, resume_run_id=resume))
    harness.run_ids.append(results[0].run_id)
    return results


def modules(results):
    return [(r.module, r.status.value, r.error_code) for r in results]


def validation_record(harness, run_id):
    return json.loads((harness.api_root / f"records/validations/{run_id}.json").read_bytes())


# -- success ----------------------------------------------------------------------------------
def test_single_tile_pipeline_success(harness) -> None:
    results = pipeline(harness, OSAKA)
    assert modules(results) == [("download", "SUCCESS", None), ("normalize", "SUCCESS", None),
                                ("validate", "SUCCESS", None)]
    dl, norm, val = results
    assert dl.run_id == norm.run_id == val.run_id
    assert val.message == "Validation committed"
    assert [a.sha256 for a in norm.artifacts] == [a.sha256 for a in val.artifacts]
    assert val.artifacts[0].record_ref == f"validations/{dl.run_id}.json"
    record = validation_record(harness, dl.run_id)
    assert record["status"] == "SUCCESS" and record["error_code"] is None
    assert record["module"] == "validate" and record["profile"] == "fixture-elevation-normalized-v0.1"
    assert record["authorization_ref"] == "fixture-auth-elevation-validate"
    assert record["validation"]["checks"] == {name: "passed" for name in CHECKS}
    nrec = harness.api_root / f"records/normalizations/{dl.run_id}.json"
    assert record["validation"]["normalize_record_sha256"] == hashlib.sha256(nrec.read_bytes()).hexdigest()
    assert json.loads(nrec.read_bytes())["authorization_ref"] == "fixture-auth-elevation-normalize"
    (tile,) = record["validation"]["tiles"]
    # fixture_builder seed 1 for the single Osaka tile: no-data where (x+y+1) % 97 == 0 -> 663.
    assert tile["nodata_count"] == 663 and tile["valid_count"] == 65536 - 663
    assert tile["warning"] is None and tile["min_cm"] is not None


def test_two_tiles_keep_ids_positions_and_hashes(harness) -> None:
    dl, norm, val = pipeline(harness, TOKYO)
    assert val.status is Status.SUCCESS
    ids = [a.acquisition_id for a in dl.artifacts]
    assert [a.acquisition_id for a in norm.artifacts] == ids == [a.acquisition_id for a in val.artifacts]
    record = validation_record(harness, dl.run_id)
    assert [t["acquisition_id"] for t in record["validation"]["tiles"]] == ids
    for art in val.artifacts:
        cand = (harness.api_root / f"work/normalized/{dl.run_id}/{art.acquisition_id}.json").read_bytes()
        assert hashlib.sha256(cand).hexdigest() == art.sha256
    xs = [json.loads((harness.api_root / "records" / a.record_ref).read_bytes())["tile"]["x"]
          for a in dl.artifacts]
    assert xs == [14550, 14551]


def test_resume_after_success_reuses_everything(harness) -> None:
    first = pipeline(harness, TOKYO)
    before = harness.files()
    harness.transport.requested_urls.clear()
    again = pipeline(harness, TOKYO, resume=first[0].run_id)
    assert again == first and harness.files() == before
    assert harness.transport.requested_urls == []


def _all_nodata_png() -> bytes:
    raw = (b"\x00" + b"\x80\x00\x00" * 256) * 256
    ihdr = struct.pack(">IIBBBBB", 256, 256, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + fb._chunk(b"IHDR", ihdr)
            + fb._chunk(b"IDAT", zlib.compress(raw)) + fb._chunk(b"IEND", b""))


def test_all_nodata_tile_passes_with_warning(harness) -> None:
    (harness.fixture_root / "tiles/dem_png/14/14370/6495.png").write_bytes(_all_nodata_png())
    dl, norm, val = pipeline(harness, OSAKA)
    assert val.status is Status.SUCCESS
    (tile,) = validation_record(harness, dl.run_id)["validation"]["tiles"]
    assert tile == {"acquisition_id": dl.artifacts[0].acquisition_id, "valid_count": 0,
                    "nodata_count": 65536, "min_cm": None, "max_cm": None,
                    "warning": "ALL_NODATA"}
    assert any(e["level"] == "WARNING" and e["module"] == "validate" for e in harness.sink.entries)


# -- stop on failure ------------------------------------------------------------------------------
def test_download_failure_stops_pipeline(harness) -> None:
    (harness.fixture_root / "tiles/dem_png/14/14551/6450.png").unlink()
    results = pipeline(harness, TOKYO)
    assert modules(results) == [("download", "FAILED", "HTTP_404")]
    assert subtree(harness, *STAGES_OUT) == {}


def test_normalize_failure_stops_before_validate(harness) -> None:
    (harness.fixture_root / "tiles/dem_png/14/14551/6450.png").write_bytes(_undecodable_png())
    results = pipeline(harness, TOKYO)
    assert modules(results) == [("download", "SUCCESS", None), ("normalize", "FAILED", "PNG_INVALID")]
    assert not (harness.api_root / "records/validations").exists() or not list(
        (harness.api_root / "records/validations").iterdir())


def test_stage_exception_is_contained(harness) -> None:
    class Exploding(ValidateStage):
        def run(self, *a, **k):
            raise RuntimeError("secret detail")

    results = pipeline(harness, OSAKA, stages={"elevation": (NormalizeStage(), Exploding())})
    assert modules(results)[-1] == ("validate", "FAILED", "INTERNAL_ERROR")
    assert "secret" not in json.dumps([r.to_dict() for r in results] + harness.sink.entries)


# -- Validate stage inputs ---------------------------------------------------------------------------
def normalized(harness, target=TOKYO):
    """Download + Normalize via the Orchestrator, Validate not run."""
    dl, norm = pipeline(harness, target, stages={"elevation": (NormalizeStage(),)})
    assert norm.status is Status.SUCCESS
    return dl, norm, build_plan(harness, dl, *target)


def validate(harness, plan, norm, *, area_cls=ApiDataArea, authorization=None):
    from hererisk.common.logging import ListSink, StructuredLogger

    with area_cls(harness.data_root, "elevation") as area:
        return ValidateStage().run(plan, norm, area, StructuredLogger(ListSink()),
                                   authorization=authorization
                                   or stage_authorization(harness, plan, "validate"))


def _forge_candidate(harness, dl, norm, index, edit):
    """Rewrite a candidate and make the Normalize record + result agree with it."""
    art = norm.artifacts[index]
    path = harness.api_root / f"work/normalized/{dl.run_id}/{art.acquisition_id}.json"
    doc = json.loads(path.read_bytes())
    edit(doc)
    data = json.dumps(doc, separators=(",", ":")).encode()
    path.unlink()
    path.write_bytes(data)
    rpath = harness.api_root / f"records/normalizations/{dl.run_id}.json"
    record = json.loads(rpath.read_bytes())
    record["outputs"][index].update(candidate_sha256=hashlib.sha256(data).hexdigest(),
                                    size_bytes=len(data))
    rpath.unlink()
    rpath.write_bytes(json.dumps(record).encode())
    arts = list(norm.artifacts)
    arts[index] = type(art)(art.artifact_id, art.acquisition_id, art.record_ref,
                            hashlib.sha256(data).hexdigest(), len(data))
    return ModuleResult(norm.run_id, "normalize", Status.SUCCESS, None, norm.message, tuple(arts))


@pytest.mark.parametrize(
    "edit",
    [
        lambda d: d["values_cm"].__setitem__(5, True),
        lambda d: d["values_cm"].__setitem__(5, 1.5),
        lambda d: d["values_cm"].__setitem__(5, 8388608),
        lambda d: d["values_cm"].pop(),
        lambda d: d["tile"].update(x=14550),  # index 1 is x=14551: swapped position
        lambda d: d.update(width=255),
    ],
    ids=["bool", "float", "out-of-range", "short", "wrong-tile", "width"],
)
def test_hash_consistent_invalid_candidate_is_validation_failed(harness, edit) -> None:
    dl, norm, plan = normalized(harness)
    forged = _forge_candidate(harness, dl, norm, 1, edit)
    result = validate(harness, plan, forged)
    assert result.status is Status.FAILED and result.error_code == "VALIDATION_FAILED"
    assert result.exit_code == 11 and ERROR_CODES["VALIDATION_FAILED"] == (Status.FAILED, 11)
    record = validation_record(harness, dl.run_id)
    assert record["status"] == "FAILED" and record["error_code"] == "VALIDATION_FAILED"
    assert "failed" in record["validation"]["checks"].values()
    assert len(record["validation"]["tiles"]) == 1  # first tile completed, second failed


def test_candidate_nan_is_rejected_as_json_format(harness) -> None:
    dl, norm, plan = normalized(harness)
    art = norm.artifacts[0]
    path = harness.api_root / f"work/normalized/{dl.run_id}/{art.acquisition_id}.json"
    data = path.read_bytes().replace(b"[", b"[NaN,", 1)
    path.unlink()
    path.write_bytes(data)
    rpath = harness.api_root / f"records/normalizations/{dl.run_id}.json"
    record = json.loads(rpath.read_bytes())
    record["outputs"][0].update(candidate_sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
    rpath.unlink()
    rpath.write_bytes(json.dumps(record).encode())
    arts = list(norm.artifacts)
    arts[0] = type(art)(art.artifact_id, art.acquisition_id, art.record_ref,
                        hashlib.sha256(data).hexdigest(), len(data))
    forged = ModuleResult(norm.run_id, "normalize", Status.SUCCESS, None, norm.message, tuple(arts))
    result = validate(harness, plan, forged)
    assert result.error_code == "VALIDATION_FAILED"
    assert validation_record(harness, dl.run_id)["validation"]["checks"]["json_format"] == "failed"


def test_candidate_bytes_changed_is_integrity_failure(harness) -> None:
    dl, norm, plan = normalized(harness)
    path = harness.api_root / f"work/normalized/{dl.run_id}/{norm.artifacts[0].acquisition_id}.json"
    path.write_bytes(path.read_bytes().replace(b"1000", b"1001", 1))
    result = validate(harness, plan, norm)
    assert result.error_code == "STORAGE_INTEGRITY_FAILED"
    assert validation_record(harness, dl.run_id)["validation"]["checks"]["candidate_integrity"] == "failed"


@pytest.mark.parametrize(
    "tamper,code",
    [
        (lambda h, dl, n: (h.api_root / f"records/normalizations/{dl.run_id}.json").unlink(),
         "RECOVERY_REQUIRED"),
        (lambda h, dl, n: (h.api_root / f"records/commits/{dl.artifacts[0].acquisition_id}.json").unlink(),
         "RECOVERY_REQUIRED"),
        (lambda h, dl, n: (h.api_root / f"work/normalized/{dl.run_id}/{n.artifacts[1].acquisition_id}.json").unlink(),
         "STORAGE_INTEGRITY_FAILED"),
    ],
    ids=["normalize-record-missing", "download-marker-missing", "candidate-missing"],
)
def test_missing_evidence_is_never_success(harness, tamper, code) -> None:
    dl, norm, plan = normalized(harness)
    tamper(harness, dl, norm)
    assert validate(harness, plan, norm).error_code == code


@pytest.mark.parametrize(
    "mutate",
    [
        lambda n: ModuleResult.error(n.run_id, "normalize", "PNG_INVALID"),
        lambda n: ModuleResult(n.run_id, "download", Status.SUCCESS, None, "x", n.artifacts),
        lambda n: ModuleResult(n.run_id, "normalize", Status.SUCCESS, None, "x",
                               tuple(reversed(n.artifacts))),
    ],
    ids=["failed", "wrong-module", "artifacts-differ"],
)
def test_bad_normalize_result_writes_nothing(harness, mutate) -> None:
    dl, norm, plan = normalized(harness)
    result = validate(harness, plan, mutate(norm))
    assert result.status is not Status.SUCCESS
    assert not (harness.api_root / f"records/validations/{dl.run_id}.json").exists()


def test_failed_validate_record_blocks_rerun_without_overwrite(harness) -> None:
    dl, norm, plan = normalized(harness)
    forged = _forge_candidate(harness, dl, norm, 0, lambda d: d.update(height=1))
    assert validate(harness, plan, forged).error_code == "VALIDATION_FAILED"
    before = harness.files()
    again = validate(harness, plan, forged)
    assert again.status is Status.BLOCKED and again.error_code == "RECOVERY_REQUIRED"
    assert harness.files() == before


def test_record_write_failure_then_rerun(harness) -> None:
    class FailingArea(ApiDataArea):
        def write_new(self, loc, data):
            if tuple(loc[:2]) == ("records", "validations"):
                raise StorageError("STORAGE_FULL", "injected")
            return super().write_new(loc, data)

    dl, norm, plan = normalized(harness)
    result = validate(harness, plan, norm, area_cls=FailingArea)
    assert result.error_code == "RECORD_COMMIT_FAILED" and result.artifacts == ()
    assert not (harness.api_root / f"records/validations/{dl.run_id}.json").exists()
    # Validate writes nothing but its record: a clean re-run is safe.
    assert validate(harness, plan, norm).status is Status.SUCCESS


def test_edited_validate_record_blocks_reuse(harness) -> None:
    dl, norm, val = pipeline(harness, TOKYO)
    path = harness.api_root / f"records/validations/{dl.run_id}.json"
    record = json.loads(path.read_bytes())
    record["validation"]["tiles"][0]["min_cm"] = -999
    path.unlink()
    path.write_bytes(json.dumps(record).encode())
    again = pipeline(harness, TOKYO, resume=dl.run_id)
    assert modules(again)[-1] == ("validate", "BLOCKED", "RECOVERY_REQUIRED")


def test_expected_tile_is_exact_int_from_plan(harness, monkeypatch) -> None:
    """B2-F01 boundary: only the plan's verified integer tile reaches validate_candidate."""
    from hererisk.elevation.validate import stage as vstage

    seen = []
    real = vstage.validate_candidate

    def spy(candidate, *, expected_tile):
        seen.append(expected_tile)
        return real(candidate, expected_tile=expected_tile)

    monkeypatch.setattr(vstage, "validate_candidate", spy)
    assert pipeline(harness, TOKYO)[-1].status is Status.SUCCESS
    assert seen == [{"z": 14, "x": 14550, "y": 6450}, {"z": 14, "x": 14551, "y": 6450}]
    assert all(type(v) is int for t in seen for v in t.values())


# -- authorization ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("missing", ["normalize", "validate"])
def test_missing_stage_authorization_blocks_before_any_write(harness, missing) -> None:
    (harness.fixture_root / f"authorization/{missing}.json").unlink()
    results = pipeline(harness, TOKYO)
    assert modules(results) == [(missing, "BLOCKED", "APPROVAL_REQUIRED")]
    assert harness.files() == {} and harness.transport.requested_urls == []


def test_download_grant_is_not_a_later_stage_grant(harness) -> None:
    auth = harness.fixture_root / "authorization"
    shutil.copy(auth / "download.json", auth / "normalize.json")  # operation stays "download"
    results = pipeline(harness, TOKYO)
    assert modules(results) == [("normalize", "BLOCKED", "APPROVAL_REQUIRED")]
    assert harness.files() == {}


def test_stage_grant_bound_to_source_and_definition(harness) -> None:
    auth = harness.fixture_root / "authorization/validate.json"
    doc = json.loads(auth.read_bytes())
    doc["grants"] = [g for g in doc["grants"] if g["source_ref"] == "fixture-dem-png-osaka"]
    auth.write_bytes(fb.dump(doc))
    assert modules(pipeline(harness, TOKYO)) == [("validate", "BLOCKED", "APPROVAL_REQUIRED")]
    doc = json.loads(fb.dump(fb.authorization(b"other", fb.FIXTURE_SOURCES, "validate")))
    auth.write_bytes(fb.dump(doc))  # bound to a different definition hash
    assert modules(pipeline(harness, TOKYO)) == [("validate", "BLOCKED", "APPROVAL_REQUIRED")]
    assert harness.files() == {}


def test_production_pipeline_blocked(harness) -> None:
    results = pipeline(harness, TOKYO, authorizer=ProductionAuthorizer())
    assert modules(results) == [("download", "BLOCKED", "APPROVAL_REQUIRED")]
    assert harness.files() == {}


def test_stages_reject_wrong_operation_authorization(harness) -> None:
    dl, norm, plan = normalized(harness)
    for op in ("download", "normalize"):
        result = validate(harness, plan, norm, authorization=stage_authorization(harness, plan, op))
        assert result.error_code == "APPROVAL_REQUIRED"
    assert not (harness.api_root / f"records/validations/{dl.run_id}.json").exists()
    osaka = harness.run(regions=OSAKA[0], source=OSAKA[1])
    osaka_plan = build_plan(harness, osaka, *OSAKA)
    for op in ("download", "validate"):
        result = normalize(harness, osaka_plan, osaka,
                           authorization=stage_authorization(harness, osaka_plan, op))
        assert result.error_code == "APPROVAL_REQUIRED"
    assert not (harness.api_root / f"work/normalized/{osaka.run_id}").exists()


def test_run_download_unchanged_with_stages_registered(harness) -> None:
    orch = harness.orchestrator(stages=stages())
    result = orch.run_download(DownloadRequest("elevation", *TOKYO))
    assert isinstance(result, ModuleResult) and result.module == "download"
    assert result.status is Status.SUCCESS
    assert subtree(harness, *STAGES_OUT) == {}


def test_pipeline_without_registered_stages_is_invalid(harness) -> None:
    results = harness.orchestrator().run_fixture_pipeline(DownloadRequest("elevation", *TOKYO))
    assert modules(results) == [("download", "FAILED", "INVALID_INPUT")]
    assert harness.files() == {}


# -- lock, isolation, permissions -----------------------------------------------------------------------
def test_source_lock_held_once_across_all_stages(harness) -> None:
    observed = []

    class Probe(ValidateStage):
        def run(self, plan, previous, area, logger, *, authorization):
            lock = area.path("work", "locks", f"download-{plan.source_ref}.lock")
            try:
                with area.exclusive_lock(lock):
                    observed.append("acquired")
            except StorageError as exc:
                observed.append(exc.error_code)
            return super().run(plan, previous, area, logger, authorization=authorization)

    results = pipeline(harness, TOKYO, stages={"elevation": (NormalizeStage(), Probe())})
    assert observed == ["TARGET_BUSY"]  # held by the Orchestrator, not re-acquired
    assert results[-1].status is Status.SUCCESS


def test_evidence_and_protected_areas_unchanged(harness) -> None:
    for rel in ("dl/current/g/x.png", "dl/archive/a.tgz", "rel/versions/v/x", "registry.json"):
        p = harness.api_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"keep")
    dl = harness.run(regions=TOKYO[0], source=TOKYO[1])
    evidence = subtree(harness, *DOWNLOAD_EVIDENCE)
    before = harness.files()
    results = pipeline(harness, TOKYO, resume=dl.run_id)
    assert results[-1].status is Status.SUCCESS
    after = harness.files()
    assert subtree(harness, *DOWNLOAD_EVIDENCE) == evidence
    assert all(after[k] == v for k, v in before.items())
    new = set(after) - set(before)
    assert new and all(k.startswith(STAGES_OUT) for k in new)


def test_new_files_not_group_or_world_writable(harness) -> None:
    pipeline(harness, TOKYO)
    for path in harness.api_root.rglob("*"):
        if path.is_symlink():
            continue
        mode = stat.S_IMODE(path.stat().st_mode)
        assert not mode & (stat.S_IWGRP | stat.S_IWOTH | stat.S_IROTH | stat.S_IXOTH), (path, oct(mode))


# -- real SIGKILL ----------------------------------------------------------------------------------------------
RUN_ID = "44444444-4444-4444-8444-444444444444"
_WORKER = r'''
import os, signal, socket, sys
from pathlib import Path
def _deny(*a, **k): raise RuntimeError("network forbidden")
socket.socket.connect = _deny; socket.getaddrinfo = _deny; socket.create_connection = _deny
from conftest import Harness
from hererisk.common.logging import ListSink
from hererisk.common.orchestrator import DownloadRequest
from hererisk.common.storage import ApiDataArea
from hererisk.elevation.download.transport import FixtureTransport
from hererisk.elevation.normalize.stage import NormalizeStage
from hererisk.elevation.validate.stage import ValidateStage
fixture, data, point, run_id = sys.argv[1:]
fixture, data = Path(fixture), Path(data)
def die(): os.kill(os.getpid(), signal.SIGKILL)
class Area(ApiDataArea):
    def write_new(self, loc, payload):
        super().write_new(loc, payload)
        s = str(loc)
        if point == "normalize-candidate" and "/work/normalized/" in s: die()
        if point == "normalize-record" and "/records/normalizations/" in s: die()
        if point == "validate-record" and "/records/validations/" in s: die()
h = Harness(fixture, data, ListSink(), FixtureTransport(fixture / "tiles"), area_factory=Area)
orch = h.orchestrator(stages={"elevation": (NormalizeStage(), ValidateStage())})
orch._id_factory = lambda: run_id
orch.run_fixture_pipeline(DownloadRequest("elevation", ("13",), "fixture-dem-png-tokyo"))
if point == "return": die()
sys.exit(7)
'''


@pytest.mark.parametrize(
    "point,expected",
    [
        ("normalize-candidate", [("download", "SUCCESS", None),
                                 ("normalize", "BLOCKED", "RECOVERY_REQUIRED")]),
        ("normalize-record", [("download", "SUCCESS", None), ("normalize", "SUCCESS", None),
                              ("validate", "SUCCESS", None)]),
        ("validate-record", [("download", "SUCCESS", None), ("normalize", "SUCCESS", None),
                             ("validate", "SUCCESS", None)]),
        ("return", [("download", "SUCCESS", None), ("normalize", "SUCCESS", None),
                    ("validate", "SUCCESS", None)]),
    ],
)
def test_sigkill_then_resume(harness, point, expected) -> None:
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(
        [str(fb.REPO_ROOT / "src"), str(fb.REPO_ROOT / "tests")]))
    proc = subprocess.run([sys.executable, "-c", _WORKER, str(harness.fixture_root),
                           str(harness.data_root), point, RUN_ID],
                          env=env, capture_output=True, timeout=120, check=False)
    assert proc.returncode == -signal.SIGKILL, (proc.returncode, proc.stderr[-2000:])
    before = harness.files()
    results = pipeline(harness, TOKYO, resume=RUN_ID)
    assert modules(results) == expected
    if point in ("validate-record", "return"):
        assert harness.files() == before  # complete evidence: verified and reused only
    if point == "normalize-candidate":
        assert harness.files() == before  # incomplete: nothing overwritten or added
        assert not (harness.api_root / f"records/validations/{RUN_ID}.json").exists()


def test_snapshot_changed_after_normalize_blocks_validate(harness) -> None:
    dl, norm, plan = normalized(harness)
    eff = harness.api_root / f"records/configurations/{dl.run_id}/effective.json"
    eff.write_bytes(eff.read_bytes().replace(b'"13"', b'"14"'))
    result = validate(harness, plan, norm)
    assert result.status is Status.BLOCKED and result.error_code == "RECOVERY_REQUIRED"
    assert not (harness.api_root / f"records/validations/{dl.run_id}.json").exists()
