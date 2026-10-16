"""Regression tests for independent re-verification Round 1 findings (R1-01 .. R1-04)."""

from __future__ import annotations

import errno
import fcntl
import os
import shutil
import struct
import threading
import zlib
from pathlib import Path

import pytest

import fixture_builder as fb
from hererisk.common.config import ConfigurationManager
from hererisk.common.orchestrator import DownloadRequest, Orchestrator
from hererisk.common.result import PipelineError, Status
from hererisk.common.storage import (
    FIXTURE_ROOT_MARKER,
    FIXTURE_ROOT_MARKER_CONTENT,
    ApiDataArea,
    Loc,
    StorageError,
    init_fixture_data_root,
)
from hererisk.elevation.download.download import pending_acquisitions
from hererisk.elevation.download.transport import FixtureTransport

REPO = fb.REPO_ROOT


def live_fds() -> set[int]:
    out = set()
    for fd in range(3, 1024):
        try:
            fcntl.fcntl(fd, fcntl.F_GETFD)
            out.add(fd)
        except OSError:
            pass
    return out


def tree_files(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")} if root.exists() else set()


# ===== R1-01: root pinning ==========================================================
def _plant_marker(path: Path) -> None:
    (path / FIXTURE_ROOT_MARKER).write_bytes(FIXTURE_ROOT_MARKER_CONTENT)


def test_swap_after_lexical_check_cannot_enter_fixture_tree(harness, monkeypatch) -> None:
    _plant_marker(harness.fixture_root)  # simulated misplaced marker in a protected tree
    before = tree_files(harness.fixture_root)
    real = Orchestrator._check_data_root
    swapped = []

    def swap(self, auth):
        real(self, auth)
        harness.data_root.rename(harness.data_root.with_name("data-original"))
        harness.data_root.symlink_to(harness.fixture_root, target_is_directory=True)
        swapped.append(True)

    monkeypatch.setattr(Orchestrator, "_check_data_root", swap)
    result = harness.run()
    assert swapped and result.status is not Status.SUCCESS
    assert result.error_code == "INVALID_INPUT"
    assert tree_files(harness.fixture_root) == before
    assert harness.transport.requested_urls == []


def test_swap_after_area_creation_before_pin_fails_safe(harness, tmp_path) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    init_fixture_data_root(target)  # even a *valid-looking* root must not be followed

    def factory(root, api):
        area = ApiDataArea(root, api)
        harness.data_root.rename(harness.data_root.with_name("data-original"))
        harness.data_root.symlink_to(target, target_is_directory=True)
        return area

    harness.area_factory = factory
    result = harness.run()
    assert result.status is Status.FAILED and result.error_code == "PERMISSION_DENIED"
    assert tree_files(target) == {FIXTURE_ROOT_MARKER}
    assert harness.transport.requested_urls == []


def test_ancestor_swap_before_first_io_is_refused(tmp_path) -> None:
    base = tmp_path / "base"
    (base / "data").mkdir(parents=True)
    outside = tmp_path / "outside"
    (outside / "data").mkdir(parents=True)
    area = ApiDataArea(base / "data", "elevation")
    base.rename(tmp_path / "saved")
    base.symlink_to(outside, target_is_directory=True)
    with pytest.raises(StorageError) as err:
        area.write_new(Loc(("work", "download", "x")), b"audit")
    area.close()
    assert err.value.error_code == "PERMISSION_DENIED"
    assert tree_files(outside) == {"data"}


@pytest.mark.parametrize("level", [1, 2, 3])
def test_any_ancestor_symlink_at_pin_time_refused(tmp_path, level) -> None:
    deep = tmp_path / "a" / "b" / "c"
    deep.mkdir(parents=True)
    area = ApiDataArea(deep, "elevation")
    victim = deep.parents[level - 1] if level > 1 else deep
    outside = tmp_path / "outside"
    shutil.copytree(victim, outside)
    victim.rename(victim.with_name(victim.name + "-saved"))
    victim.symlink_to(outside, target_is_directory=True)
    with pytest.raises(StorageError):
        area.pin()
    area.close()
    assert not any(p.name == "elevation" for p in outside.rglob("*"))


def test_swap_into_protected_schema_tree_refused(harness, tmp_path, monkeypatch) -> None:
    schema_root = tmp_path / "schema-root"
    conf = schema_root / "api/elevation/conf"
    conf.mkdir(parents=True)
    shutil.copy(REPO / "api/elevation/conf/sources.schema.json", conf)
    _plant_marker(schema_root)
    before = tree_files(schema_root)
    orch = harness.orchestrator()
    orch._config = ConfigurationManager(harness.fixture_root, schema_root)
    real = Orchestrator._check_data_root

    def swap(self, auth):
        real(self, auth)
        harness.data_root.rename(harness.data_root.with_name("data-original"))
        harness.data_root.symlink_to(schema_root, target_is_directory=True)

    monkeypatch.setattr(Orchestrator, "_check_data_root", swap)
    result = orch.run_download(DownloadRequest("elevation", ("13",), "fixture-dem-png-tokyo"))
    assert result.error_code == "INVALID_INPUT"
    assert tree_files(schema_root) == before


def test_protected_identity_checked_on_pinned_chain(harness, tmp_path) -> None:
    """A root inside a protected tree is refused by identity even via another name."""
    protected = tmp_path / "protected"
    (protected / "inner").mkdir(parents=True)
    init_fixture_data_root(protected / "inner")
    with ApiDataArea(protected / "inner", "elevation") as area:
        area.pin()
        assert area.root_within((protected,))
        assert area.root_within((Path("/nonexistent"), protected / "inner"))
        assert not area.root_within((tmp_path / "unrelated",))


FIRMLINK = Path("/System/Volumes/Data")


@pytest.mark.skipif(not FIRMLINK.is_dir(), reason="macOS firmlink layout not present")
def test_firmlink_alias_into_protected_tree_refused(harness, tmp_path) -> None:
    """realpath() keeps macOS firmlink aliases, so only the identity check catches them."""
    protected = harness.fixture_root  # the fixture definition tree is a protected root
    inner = protected / "data"
    inner.mkdir()
    init_fixture_data_root(inner)
    alias = FIRMLINK / inner.relative_to("/")
    if not alias.is_dir() or os.stat(alias).st_ino != os.stat(inner).st_ino:
        pytest.skip("temp dir not reachable through the firmlink")
    with ApiDataArea(alias, "elevation") as area:
        assert not Path(os.path.realpath(alias)).is_relative_to(protected)  # lexical misses
        assert area.root_within((protected,))
    harness.data_root = alias
    result = harness.run()
    assert result.error_code == "INVALID_INPUT"
    assert tree_files(inner) == {FIXTURE_ROOT_MARKER}


@pytest.mark.skipif(not FIRMLINK.is_dir(), reason="macOS firmlink layout not present")
def test_init_fixture_root_refuses_firmlink_alias_into_protected(tmp_path) -> None:
    protected = tmp_path / "protected"
    inner = protected / "empty"
    inner.mkdir(parents=True)
    alias = FIRMLINK / inner.relative_to("/")
    if not alias.is_dir():
        pytest.skip("temp dir not reachable through the firmlink")
    with pytest.raises(StorageError):
        init_fixture_data_root(alias, protected_roots=(protected,))
    with pytest.raises(StorageError):
        init_fixture_data_root(inner, protected_roots=(protected,))
    assert list(inner.iterdir()) == []


def test_swap_after_pin_writes_only_into_pinned_root(harness, tmp_path) -> None:
    replacement = tmp_path / "replacement"
    replacement.mkdir()
    init_fixture_data_root(replacement)
    area = ApiDataArea(harness.data_root, "elevation")
    area.pin()
    harness.data_root.rename(tmp_path / "pinned")
    harness.data_root.symlink_to(replacement, target_is_directory=True)
    area.write_new(area.path("work", "download", "f"), b"x")
    area.close()
    assert tree_files(replacement) == {FIXTURE_ROOT_MARKER}
    assert (tmp_path / "pinned/elevation/work/download/f").read_bytes() == b"x"


def test_marker_is_read_from_pinned_root(harness, tmp_path) -> None:
    unmarked = tmp_path / "unmarked"
    unmarked.mkdir()
    area = ApiDataArea(unmarked, "elevation")
    area.pin()
    # Marker appears elsewhere under the same name after pinning: still unmarked.
    unmarked.rename(tmp_path / "unmarked-pinned")
    harness.data_root.rename(unmarked)
    assert not area.has_fixture_marker()
    area.close()


def test_production_data_root_lexically_refused(harness) -> None:
    harness.data_root = Path("/data")
    assert harness.run().error_code == "INVALID_INPUT"


# ===== R1-02: pending acquisitions and capacity =====================================
def failing_area(prefix: tuple[str, str]):
    class FailingArea(ApiDataArea):
        def write_new(self, loc, data):
            if tuple(loc[:2]) == prefix:
                raise StorageError("STORAGE_FULL", "injected")
            return super().write_new(loc, data)

    return FailingArea


class InterruptingTransport(FixtureTransport):
    def _read(self, handle):
        with handle:
            yield handle.read(100)
            raise PipelineError("TRANSFER_INTERRUPTED")


def _run_until_blocked(harness, first_code: str) -> list:
    results = [harness.run() for _ in range(8)]
    assert [r.error_code for r in results] == [first_code] * 8
    before = harness.files()
    blocked = [harness.run() for _ in range(3)]  # repeated requests after the limit
    assert all(r.status is Status.BLOCKED and r.error_code == "RECOVERY_REQUIRED" for r in blocked)
    assert harness.files() == before  # no new snapshot, reservation or artifact
    return results


@pytest.mark.parametrize(
    "prefix,code",
    [(("records", "acquisitions"), "RECORD_COMMIT_FAILED"),
     (("records", "commits"), "RECORD_COMMIT_FAILED")],
    ids=["record-write", "marker-write"],
)
def test_post_artifact_failures_count_towards_limit(harness, prefix, code) -> None:
    harness.area_factory = failing_area(prefix)
    _run_until_blocked(harness, code)
    originals = list((harness.api_root / "work/acquisitions").rglob("original.png"))
    assert len(originals) == 8
    configs = list((harness.api_root / "records/configurations").iterdir())
    assert len(configs) == 8


def test_part_failures_count_towards_limit(harness) -> None:
    harness.transport = InterruptingTransport(harness.fixture_root / "tiles")
    _run_until_blocked(harness, "TRANSFER_INTERRUPTED")
    assert len(list((harness.api_root / "work/download").rglob("*.part"))) == 8


def test_limit_shared_across_concurrent_sources(harness) -> None:
    harness.transport = InterruptingTransport(harness.fixture_root / "tiles")
    for _ in range(7):
        assert harness.run().error_code == "TRANSFER_INTERRUPTED"
    entered, release = threading.Event(), threading.Event()

    class Blocking(FixtureTransport):
        def fetch(self, url):
            entered.set()
            assert release.wait(10)
            return super().fetch(url)

    harness.transport = Blocking(harness.fixture_root / "tiles")
    out = {}
    thread = threading.Thread(target=lambda: out.setdefault("tokyo", harness.run()))
    thread.start()
    assert entered.wait(10)  # tokyo holds the 8th slot and is transferring
    osaka = harness.run(regions=("27",), source="fixture-dem-png-osaka")
    release.set()
    thread.join(10)
    assert osaka.status is Status.BLOCKED and osaka.error_code == "RECOVERY_REQUIRED"
    assert not (harness.api_root / f"records/configurations/{osaka.run_id}").exists()
    assert all("14370" not in u for u in harness.transport.requested_urls)
    # Tokyo's first tile committed, its second reused the freed capacity.
    assert out["tokyo"].status is Status.SUCCESS
    with ApiDataArea(harness.data_root, "elevation") as area:
        assert len(pending_acquisitions(area)) == 7


def test_quota_check_and_reservation_are_atomic(harness, monkeypatch) -> None:
    """Two sources racing for the last slot: the quota lock lets only one through."""
    from hererisk.elevation.download import download as dl

    harness.transport = InterruptingTransport(harness.fixture_root / "tiles")
    for _ in range(7):
        assert harness.run().error_code == "TRANSFER_INTERRUPTED"
    barrier = threading.Barrier(2, timeout=1.0)
    real_count = dl.pending_acquisitions

    def racing_count(area):
        found = real_count(area)
        try:
            barrier.wait()  # without the lock both racers would meet here
        except threading.BrokenBarrierError:
            pass
        return found

    monkeypatch.setattr(dl, "pending_acquisitions", racing_count)
    harness.transport = InterruptingTransport(harness.fixture_root / "tiles")
    out: dict[str, object] = {}
    threads = [
        threading.Thread(target=lambda: out.setdefault("tokyo", harness.run())),
        threading.Thread(target=lambda: out.setdefault(
            "osaka", harness.run(regions=("27",), source="fixture-dem-png-osaka"))),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    monkeypatch.undo()
    codes = sorted(r.error_code for r in out.values())  # type: ignore[union-attr]
    assert codes == ["RECOVERY_REQUIRED", "TRANSFER_INTERRUPTED"]
    with ApiDataArea(harness.data_root, "elevation") as area:
        assert len(real_count(area)) == 8


def test_committed_artifacts_are_not_counted(harness) -> None:
    for _ in range(6):  # 12 committed acquisitions > limit 8
        assert harness.run().status is Status.SUCCESS
    with ApiDataArea(harness.data_root, "elevation") as area:
        assert pending_acquisitions(area) == set()


def test_pending_states_are_counted_once_each(harness) -> None:
    ok = harness.run()
    committed = {a.acquisition_id for a in ok.artifacts}
    ids = [f"aaaaaaaa-aaaa-4aaa-8aaa-00000000000{i}" for i in range(6)]
    root = harness.api_root
    run = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    (root / f"work/download/{run}/{ids[0]}").mkdir(parents=True)  # reserved / part
    (root / f"work/acquisitions/{run}/{ids[1]}").mkdir(parents=True)  # artifact only
    (root / f"records/acquisitions/{run}").mkdir(parents=True)
    (root / f"records/acquisitions/{run}/{ids[2]}.json").write_bytes(b"{}")  # record only
    (root / f"records/commits/{ids[3]}.json").write_bytes(b"{}")  # marker only
    (root / f"records/commits/.{ids[4]}.json.tmp-{'0' * 32}").write_bytes(b"")  # temp
    # id 5: artifact + record + marker but part dir still present -> pending once
    (root / f"work/download/{run}/{ids[5]}").mkdir()
    (root / f"work/acquisitions/{run}/{ids[5]}").mkdir()
    (root / f"records/acquisitions/{run}/{ids[5]}.json").write_bytes(b"{}")
    (root / f"records/commits/{ids[5]}.json").write_bytes(b"{}")
    with ApiDataArea(harness.data_root, "elevation") as area:
        pending = pending_acquisitions(area)
    assert pending == set(ids)
    assert not pending & committed


def test_resume_rules_unchanged_at_limit(harness) -> None:
    first = harness.run()
    harness.transport = InterruptingTransport(harness.fixture_root / "tiles")
    for _ in range(8):
        harness.run()
    harness.transport = FixtureTransport(harness.fixture_root / "tiles")
    again = harness.run(resume=first.run_id)  # fully committed: no capacity needed
    assert again.status is Status.SUCCESS and again.artifacts == first.artifacts
    assert harness.transport.requested_urls == []


# ===== R1-03: PLTE ==================================================================
def _with_plte(png: bytes, payload: bytes) -> bytes:
    chunk = struct.pack(">I", len(payload)) + b"PLTE" + payload + struct.pack(
        ">I", zlib.crc32(b"PLTE" + payload) & 0xFFFFFFFF)
    return png[:33] + chunk + png[33:]


@pytest.mark.parametrize("length", [0, 1, 4, 771])
def test_invalid_palette_rejected_end_to_end(harness, length) -> None:
    tile = harness.fixture_root / "tiles/dem_png/14/14550/6450.png"
    tile.write_bytes(_with_plte(tile.read_bytes(), b"\0" * length))
    result = harness.run()
    assert result.error_code == "PNG_INVALID"
    assert not list((harness.api_root / "records/commits").glob("*.json"))


@pytest.mark.parametrize("length", [3, 768])
def test_valid_palette_on_rgb_accepted(harness, length) -> None:
    for x in (14550, 14551):
        tile = harness.fixture_root / f"tiles/dem_png/14/{x}/6450.png"
        tile.write_bytes(_with_plte(tile.read_bytes(), b"\1" * length))
    assert harness.run().status is Status.SUCCESS


# ===== R1-04: fd ownership ============================================================
def test_opendir_fstat_failure_closes_fd_repeatedly(harness, monkeypatch) -> None:
    area = ApiDataArea(harness.data_root, "elevation")
    area.ensure_dir(area.path("work", "download"))
    baseline = live_fds()
    real = os.fstat
    opened: list[int] = []

    def fail(fd):
        opened.append(fd)
        raise OSError(errno.EIO, "injected fstat failure")

    for _ in range(20):
        monkeypatch.setattr(os, "fstat", fail)
        with pytest.raises(StorageError) as err:
            area.ensure_dir(area.path("work", "download", "sub"))
        monkeypatch.setattr(os, "fstat", real)
        assert err.value.error_code == "STORAGE_INTEGRITY_FAILED"
    assert live_fds() == baseline
    area.close()
    assert opened and not (set(opened) & live_fds())


def test_pin_fstat_failure_closes_fds(tmp_path, monkeypatch) -> None:
    baseline = live_fds()
    real = os.fstat
    for _ in range(10):
        area = ApiDataArea(tmp_path, "elevation")
        monkeypatch.setattr(os, "fstat", lambda fd: (_ for _ in ()).throw(OSError(errno.EIO, "x")))
        with pytest.raises(StorageError):
            area.pin()
        monkeypatch.setattr(os, "fstat", real)
        area.close()
    assert live_fds() == baseline


def test_non_directory_after_open_closes_fd(harness, monkeypatch) -> None:
    import stat as stat_mod

    area = ApiDataArea(harness.data_root, "elevation")
    area.ensure_dir(area.path("work", "download"))
    baseline = live_fds()
    monkeypatch.setattr(stat_mod, "S_ISDIR", lambda mode: False)
    for _ in range(10):
        with pytest.raises(StorageError) as err:
            area.list_dir(area.path("work", "download"))
        assert err.value.error_code == "PERMISSION_DENIED"
    monkeypatch.undo()
    area.close()
    assert live_fds() <= baseline


def test_newfile_fdopen_failure_closes_both_fds(harness, monkeypatch) -> None:
    area = ApiDataArea(harness.data_root, "elevation")
    area.ensure_dir(area.path("work", "download", "r"))
    baseline = live_fds()

    def boom(*a, **k):
        raise OSError(errno.EMFILE, "injected")

    monkeypatch.setattr(os, "fdopen", boom)
    for i in range(10):
        with pytest.raises(OSError):
            area.open_exclusive(area.path("work", "download", "r", f"f{i}"))
    monkeypatch.undo()
    assert live_fds() == baseline
    area.close()


def test_transport_fstat_failure_closes_fd(harness, monkeypatch) -> None:
    baseline = live_fds()
    real = os.fstat
    calls = {"n": 0}

    def flaky(fd):
        calls["n"] += 1
        raise OSError(errno.EIO, "injected")

    monkeypatch.setattr(os, "fstat", flaky)
    for _ in range(10):
        with pytest.raises(PipelineError) as err:
            harness.transport.fetch("https://fixture.invalid/dem_png/14/14550/6450.png")
        assert err.value.error_code == "TRANSFER_INTERRUPTED"
    monkeypatch.setattr(os, "fstat", real)
    assert calls["n"] == 10 and live_fds() == baseline


def test_normal_and_rejected_operations_release_fds(harness) -> None:
    for _ in range(3):  # warm up lazily created objects
        harness.run()
    baseline = live_fds()
    for _ in range(10):
        assert harness.run().status is Status.SUCCESS
        with ApiDataArea(harness.data_root, "elevation") as area:
            with pytest.raises(StorageError):
                area.read_bytes(Loc(("records", "commits", "missing.json")), 100)
            with pytest.raises(StorageError):
                area.write_new(Loc(("dl", "current", "x")), b"x")
    assert live_fds() == baseline


def test_orchestrator_classifies_storage_fstat_failure(harness, monkeypatch) -> None:
    """An fstat EIO during directory traversal is a storage error, not INTERNAL_ERROR."""
    harness.run()  # create layout
    real_open = os.open
    real_fstat = os.fstat
    target: list[int] = []

    def tracking_open(path, flags, *a, **k):
        fd = real_open(path, flags, *a, **k)
        if path == "acquisitions" and flags & os.O_DIRECTORY:
            target.append(fd)
        return fd

    def failing_fstat(fd):
        if fd in target:
            raise OSError(errno.EIO, "injected")
        return real_fstat(fd)

    from hererisk.common import storage

    # Wrapping os.open changes its identity, which the platform check would
    # (correctly) refuse; keep the check satisfied for this injection only.
    monkeypatch.setattr(storage, "_platform_supported", lambda: True)
    monkeypatch.setattr(os, "open", tracking_open)
    monkeypatch.setattr(os, "fstat", failing_fstat)
    result = harness.run()
    monkeypatch.undo()
    assert target, "injection point not reached"
    assert result.status is Status.FAILED and result.error_code == "STORAGE_INTEGRITY_FAILED"


def test_wrapped_os_functions_trip_platform_check(harness, monkeypatch) -> None:
    """Fail safe: if dir_fd support cannot be confirmed, no I/O happens at all."""
    real_open = os.open
    monkeypatch.setattr(os, "open", lambda *a, **k: real_open(*a, **k))
    result = harness.run()
    monkeypatch.undo()
    assert result.error_code == "PERMISSION_DENIED"
    assert harness.files() == {} and harness.transport.requested_urls == []
