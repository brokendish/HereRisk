"""Contract tests: re-runs, simulated crashes, concurrency, area isolation."""

from __future__ import annotations

import ast
import json
import threading
from pathlib import Path

import pytest

import fixture_builder as fb
from hererisk.common.result import Status
from hererisk.common.storage import ApiDataArea
from hererisk.elevation.download.transport import FixtureTransport


class SimulatedCrash(BaseException):
    """Stands in for SIGKILL: escapes every ``except Exception`` handler."""


def crash_area(fragment: str, *, after: bool, nth: int = 1):
    seen = {"n": 0}

    class CrashArea(ApiDataArea):
        def write_new(self, path, data):
            hit = fragment in str(path)
            if hit:
                seen["n"] += 1
            if hit and seen["n"] == nth and not after:
                raise SimulatedCrash
            super().write_new(path, data)
            if hit and seen["n"] == nth and after:
                raise SimulatedCrash

    return CrashArea


def run_crashing(harness, area_cls) -> str:
    harness.area_factory = area_cls
    with pytest.raises(SimulatedCrash):
        harness.run()
    harness.area_factory = ApiDataArea
    return next((harness.api_root / "records/configurations").iterdir()).name


# -- re-run ----------------------------------------------------------------
def test_new_run_with_same_configuration_keeps_old_artifacts(harness) -> None:
    first = harness.run()
    before = harness.files()
    second = harness.run()
    assert second.status is Status.SUCCESS and second.run_id != first.run_id
    after = harness.files()
    assert {k: after[k] for k in before if not k.endswith(".lock")} == {
        k: v for k, v in before.items() if not k.endswith(".lock")}
    assert {a.sha256 for a in first.artifacts} == {a.sha256 for a in second.artifacts}
    assert {a.acquisition_id for a in first.artifacts}.isdisjoint(
        a.acquisition_id for a in second.artifacts)


def test_same_run_id_after_success_reuses_without_transfer(harness) -> None:
    first = harness.run()
    before = harness.files()
    harness.transport.requested_urls.clear()
    again = harness.run(resume=first.run_id)
    assert again.status is Status.SUCCESS and again.run_id == first.run_id
    assert harness.transport.requested_urls == []
    assert sorted(again.artifacts, key=lambda a: a.acquisition_id) == sorted(
        first.artifacts, key=lambda a: a.acquisition_id)
    assert harness.files() == before


def test_same_run_id_with_different_configuration_rejected(harness) -> None:
    first = harness.run()
    before = harness.files()
    definition = fb.fixture_definition()
    definition["definition_revision"] = "fixture-2"
    harness.rebuild(definition_bytes=fb.dump(definition))
    harness.transport.requested_urls.clear()
    again = harness.run(resume=first.run_id)
    assert again.status is Status.FAILED and again.error_code == "INVALID_INPUT"
    assert harness.transport.requested_urls == [] and harness.files() == before
    # A new run under the new configuration is fine and leaves the old one intact.
    new = harness.run()
    assert new.status is Status.SUCCESS
    assert all(harness.files()[k] == v for k, v in before.items() if not k.endswith(".lock"))


def test_unknown_or_malformed_resume_run_id(harness) -> None:
    assert harness.run(resume="11111111-1111-4111-8111-111111111111").error_code == "INVALID_INPUT"
    assert harness.run(resume="../../etc").error_code == "INVALID_INPUT"
    assert harness.transport.requested_urls == []


def test_tampered_committed_artifact_is_not_overwritten(harness) -> None:
    first = harness.run()
    art = first.artifacts[0]
    stored = harness.api_root / f"work/acquisitions/{first.run_id}/{art.acquisition_id}/original.png"
    stored.write_bytes(b"tampered")
    again = harness.run(resume=first.run_id)
    assert again.status is Status.BLOCKED and again.error_code == "RECOVERY_REQUIRED"
    assert stored.read_bytes() == b"tampered"


# -- simulated forced stop at each commit point ------------------------------
@pytest.mark.parametrize(
    "fragment,after",
    [
        ("/records/acquisitions/", False),  # artifact promoted, no record
        ("/records/commits/", False),  # record committed, no marker
    ],
    ids=["after-artifact", "after-record"],
)
def test_crash_before_marker_requires_recovery(harness, fragment, after) -> None:
    run_id = run_crashing(harness, crash_area(fragment, after=after))
    assert not list((harness.api_root / "records/commits").glob("*.json"))
    before = harness.files()
    result = harness.run(resume=run_id)
    assert result.status is Status.BLOCKED and result.error_code == "RECOVERY_REQUIRED"
    assert result.artifacts == () and harness.files() == before


def test_crash_during_transfer_leaves_part_and_requires_recovery(harness) -> None:
    class CrashTransport(FixtureTransport):
        def _read(self, handle):
            with handle:
                yield handle.read(1000)
                raise SimulatedCrash

    harness.transport = CrashTransport(harness.fixture_root / "tiles")
    with pytest.raises(SimulatedCrash):
        harness.run()
    run_id = next((harness.api_root / "records/configurations").iterdir()).name
    assert len(list((harness.api_root / "work/download").rglob("*.part"))) == 1
    harness.transport = FixtureTransport(harness.fixture_root / "tiles")
    result = harness.run(resume=run_id)
    assert result.error_code == "RECOVERY_REQUIRED"
    # A fresh run is unaffected by the quarantined part of the old run.
    assert harness.run().status is Status.SUCCESS


def test_crash_after_marker_resumes_by_verification(harness) -> None:
    run_id = run_crashing(harness, crash_area("/records/commits/", after=True, nth=1))
    assert len(list((harness.api_root / "records/commits").glob("*.json"))) == 1
    harness.transport.requested_urls.clear()
    result = harness.run(resume=run_id)
    assert result.status is Status.SUCCESS and len(result.artifacts) == 2
    tiles = [
        json.loads((harness.api_root / "records" / a.record_ref).read_text())["tile"]["x"]
        for a in result.artifacts
    ]
    assert tiles == [14550, 14551]  # reused + new, reported in tile order
    # Only the uncommitted second tile was transferred.
    assert harness.transport.requested_urls == ["https://fixture.invalid/dem_png/14/14551/6450.png"]


# -- concurrency -------------------------------------------------------------
def test_concurrent_run_for_same_source_is_busy(harness) -> None:
    entered, release = threading.Event(), threading.Event()

    class BlockingTransport(FixtureTransport):
        def fetch(self, url):
            entered.set()
            assert release.wait(10)
            return super().fetch(url)

    harness.transport = BlockingTransport(harness.fixture_root / "tiles")
    results = {}
    thread = threading.Thread(target=lambda: results.setdefault("a", harness.run()))
    thread.start()
    assert entered.wait(10)
    busy = harness.run()
    release.set()
    thread.join(10)
    assert busy.status is Status.BLOCKED and busy.error_code == "TARGET_BUSY"
    assert busy.artifacts == ()
    assert results["a"].status is Status.SUCCESS
    assert len(harness.transport.requested_urls) == 2  # only the first run transferred
    assert not (harness.api_root / f"records/configurations/{busy.run_id}").exists()


# -- isolation -----------------------------------------------------------------
def test_writes_confined_to_own_work_and_records(harness) -> None:
    other = harness.data_root / "flood" / "records" / "keep.json"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"other api")
    for rel in ("dl/current/g1/x.png", "dl/archive/a.tar.gz", "rel/versions/v1/x", "registry.json"):
        p = harness.api_root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(rel.encode())
    before = harness.files()
    assert harness.run().status is Status.SUCCESS
    after = harness.files()
    for path, digest in before.items():
        assert after[path] == digest
    new = set(after) - set(before)
    assert new and all(p.startswith(("elevation/work/", "elevation/records/")) for p in new)
    assert not any(p.startswith(("elevation/dl/", "elevation/rel/")) for p in new)


def test_symlinked_work_area_rejected(harness, tmp_path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    harness.api_root.mkdir()
    (harness.api_root / "work").symlink_to(outside)
    result = harness.run()
    assert result.status is Status.FAILED and result.error_code == "PERMISSION_DENIED"
    assert list(outside.iterdir()) == []


def test_no_later_stage_or_network_code_reachable(no_network) -> None:
    src = fb.REPO_ROOT / "src" / "hererisk"
    forbidden = {"normalize", "validate", "publish", "registry", "generation", "restore"}
    banned_imports = {"socket", "http", "urllib.request", "requests", "subprocess"}
    # Phase 1-D.1: the GSI PoC's single HTTPS module is the only network code.
    network_allowed = {src / "elevation" / "gsi_poc" / "http_fetch.py"}
    pipeline_dirs = ("/common/", "/elevation/download/", "/elevation/normalize/",
                     "/elevation/validate/", "/elevation/lookup/")
    for path in src.rglob("*.py"):
        assert path.stem not in forbidden, path
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if path not in network_allowed:
                    assert not any(name == b or name.startswith(b + ".") for b in banned_imports), (
                        path, name)
                if any(d in path.as_posix() for d in pipeline_dirs):
                    assert not name.startswith("hererisk.elevation.gsi_poc"), (path, name)
                if "/common/" in path.as_posix():
                    assert not name.startswith("hererisk.elevation"), (path, name)
    assert no_network == []


def test_network_guard_is_active() -> None:
    import socket

    with pytest.raises(AssertionError):
        socket.create_connection(("cyberjapandata.gsi.go.jp", 443))
