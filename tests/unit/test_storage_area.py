"""Unit tests: common storage (confinement, symlink safety, no-clobber, limits, lock)."""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

from hererisk.common import storage
from hererisk.common.storage import (
    FIXTURE_ROOT_MARKER,
    ApiDataArea,
    LimitExceeded,
    Loc,
    StorageError,
    init_fixture_data_root,
)


@pytest.fixture
def area(tmp_path: Path):
    with ApiDataArea(tmp_path, "elevation") as a:
        yield a


def put(area: ApiDataArea, loc: Loc, data: bytes) -> None:
    area.write_new(loc, data)


# -- F01: every entry point is confined -------------------------------------------
FORBIDDEN = [
    Loc(("dl", "current", "x")),
    Loc(("dl", "archive", "x")),
    Loc(("rel", "versions", "x")),
    Loc(("records", "registry", "x")),
    Loc(("work", "other", "x")),
    Loc(("work", "download", "..", "x")),
    Loc(("work", "download", "../../flood", "x")),
    Loc(("work", "download", "/abs")),
    Loc(("work",)),
]


def _ops(area: ApiDataArea, loc: object):
    good = Loc(("work", "download", "ok", "f"))
    return [
        lambda: area.ensure_dir(loc),
        lambda: area.write_new(loc, b"x"),
        lambda: area.open_exclusive(loc),
        lambda: area.link_no_clobber(good, loc),
        lambda: area.link_no_clobber(loc, good),
        lambda: area.read_bytes(loc, 10),
        lambda: area.hash_file(loc, 10),
        lambda: area.list_dir(loc),
        lambda: area.dir_exists(loc),
        lambda: area.entry_exists(loc),
        lambda: area.remove_empty_dir(loc),
        lambda: area.exclusive_lock(loc).__enter__(),
        lambda: area.same_filesystem(loc),
    ]


@pytest.mark.parametrize("loc", FORBIDDEN, ids=str)
def test_every_operation_rejects_forbidden_locations(area: ApiDataArea, tmp_path, loc) -> None:
    put(area, Loc(("work", "download", "ok", "f")), b"x")
    for op in _ops(area, loc):
        with pytest.raises(StorageError) as err:
            op()
        assert err.value.error_code == "PERMISSION_DENIED"
    for sub in ("dl", "rel", "records/registry", "work/other"):
        assert not (tmp_path / "elevation" / sub).exists()


@pytest.mark.parametrize(
    "target", [Path("flood/records/x"), Path("elevation/dl/current/x"), "work/download/x"]
)
def test_plain_paths_grant_nothing(area: ApiDataArea, tmp_path, target) -> None:
    abs_target = tmp_path / target if isinstance(target, Path) else target
    for op in _ops(area, abs_target):
        with pytest.raises(StorageError):
            op()
    assert not (tmp_path / "flood").exists() and not (tmp_path / "elevation/dl").exists()


def test_reads_limited_to_readable_areas(area: ApiDataArea) -> None:
    lock = area.path("work", "locks", "l")
    with area.exclusive_lock(lock):
        pass
    with pytest.raises(StorageError):
        area.read_bytes(lock, 10)


def test_area_is_scoped_to_its_api(tmp_path: Path) -> None:
    with ApiDataArea(tmp_path, "elevation") as a:
        a.write_new(a.path("records", "commits", "x.json"), b"e")
    assert (tmp_path / "elevation/records/commits/x.json").read_bytes() == b"e"
    assert [p.name for p in tmp_path.iterdir()] == ["elevation"]


# -- no-clobber / durability ---------------------------------------------------------
def test_write_new_creates_and_never_overwrites(area: ApiDataArea, tmp_path) -> None:
    target = area.path("records", "commits", "a.json")
    area.write_new(target, b"one")
    with pytest.raises(StorageError) as err:
        area.write_new(target, b"two")
    assert err.value.error_code == "STORAGE_INTEGRITY_FAILED"
    d = tmp_path / "elevation/records/commits"
    assert (d / "a.json").read_bytes() == b"one"
    assert [p.name for p in d.iterdir()] == ["a.json"]  # no temp leftovers


def test_link_no_clobber_refuses_existing_target(area: ApiDataArea, tmp_path) -> None:
    src, dst = area.path("work", "download", "r", "src"), area.path("work", "download", "r", "dst")
    area.write_new(src, b"new")
    area.write_new(dst, b"old")
    with pytest.raises(StorageError):
        area.link_no_clobber(src, dst)
    assert (tmp_path / "elevation/work/download/r/dst").read_bytes() == b"old"


def test_files_and_dirs_are_fsynced(area: ApiDataArea, monkeypatch: pytest.MonkeyPatch) -> None:
    target = area.path("records", "commits", "b.json")
    area.ensure_dir(target.parent)
    calls: list[int] = []
    real = storage.fsync_fd
    monkeypatch.setattr(storage, "fsync_fd", lambda fd: (calls.append(fd), real(fd)))
    area.write_new(target, b"x")
    assert len(calls) >= 3  # file + dir after link + dir after unlink


def test_unlink_failure_after_link_preserves_bytes(area, tmp_path, monkeypatch) -> None:
    src, dst = area.path("work", "download", "u", "s"), area.path("work", "download", "u", "d")
    area.write_new(src, b"original")
    real = os.unlink

    def fail(name, *a, **k):
        if name == "s":
            raise OSError(errno.EIO, "injected")
        return real(name, *a, **k)

    monkeypatch.setattr(os, "unlink", fail)
    with pytest.raises(StorageError):
        area.link_no_clobber(src, dst)
    d = tmp_path / "elevation/work/download/u"
    assert (d / "s").read_bytes() == (d / "d").read_bytes() == b"original"


# -- F02: symlinks, including races ----------------------------------------------------
def test_static_symlink_in_area_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "elevation").mkdir()
    os.symlink(outside, tmp_path / "elevation" / "work")
    with ApiDataArea(tmp_path, "elevation") as area:
        with pytest.raises(StorageError) as err:
            area.write_new(area.path("work", "download", "r", "f"), b"x")
    assert err.value.error_code == "PERMISSION_DENIED"
    assert list(outside.iterdir()) == []


def test_symlinked_final_component_not_followed(area: ApiDataArea, tmp_path) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"secret")
    area.ensure_dir(area.path("records", "commits"))
    os.symlink(outside, tmp_path / "elevation/records/commits/x.json")
    with pytest.raises(StorageError):
        area.read_bytes(area.path("records", "commits", "x.json"), 100)
    with pytest.raises(StorageError):
        area.write_new(area.path("records", "commits", "x.json"), b"overwrite")
    area.ensure_dir(area.path("work", "locks"))
    os.symlink(outside, tmp_path / "elevation/work/locks/x.lock")
    with pytest.raises(StorageError):
        with area.exclusive_lock(area.path("work", "locks", "x.lock")):
            pass
    assert outside.read_bytes() == b"secret"


@pytest.mark.parametrize("swap_level", ["parent", "grandparent", "api"])
def test_parent_swapped_to_symlink_during_operation(tmp_path, monkeypatch, swap_level) -> None:
    """Swap a directory for a symlink right before the final open: no outside write."""
    outside = tmp_path / "outside"
    outside.mkdir()
    area = ApiDataArea(tmp_path / "data", "elevation")
    (tmp_path / "data").mkdir()
    loc = area.path("work", "download", "race", "x")
    area.ensure_dir(loc.parent)
    victim = {
        "parent": tmp_path / "data/elevation/work/download/race",
        "grandparent": tmp_path / "data/elevation/work/download",
        "api": tmp_path / "data/elevation",
    }[swap_level]
    real_open = os.open
    swapped = []

    def racing_open(path, flags, *args, **kwargs):
        if path == "x" and not swapped:
            victim.rename(victim.with_name(victim.name + "-saved"))
            victim.symlink_to(outside, target_is_directory=True)
            swapped.append(True)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", racing_open)
    try:
        with area.open_exclusive(loc) as handle:
            handle.write(b"audit")
    except StorageError:
        pass
    monkeypatch.undo()
    area.close()
    assert swapped and list(outside.iterdir()) == []


def test_symlink_swap_before_operation_fails_safe(tmp_path, monkeypatch) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "data").mkdir()
    with ApiDataArea(tmp_path / "data", "elevation") as area:
        area.ensure_dir(area.path("work", "download", "race"))
        race = tmp_path / "data/elevation/work/download/race"
        race.rename(race.with_name("saved"))
        race.symlink_to(outside, target_is_directory=True)
        for op in (
            lambda: area.write_new(area.path("work", "download", "race", "x"), b"x"),
            lambda: area.open_exclusive(area.path("work", "download", "race", "y")),
            lambda: area.ensure_dir(area.path("work", "download", "race", "sub")),
            lambda: area.list_dir(area.path("work", "download", "race")),
            lambda: area.remove_empty_dir(area.path("work", "download", "race", "sub")),
        ):
            with pytest.raises(StorageError) as err:
                op()
            assert err.value.error_code == "PERMISSION_DENIED"
    assert list(outside.iterdir()) == []


def test_data_root_swap_after_open_has_no_effect(tmp_path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "data"
    root.mkdir()
    area = ApiDataArea(root, "elevation")
    area.ensure_dir(area.path("work", "download"))
    root.rename(tmp_path / "data-saved")
    root.symlink_to(outside, target_is_directory=True)
    area.write_new(area.path("work", "download", "f"), b"x")
    area.close()
    assert list(outside.iterdir()) == []
    assert (tmp_path / "data-saved/elevation/work/download/f").read_bytes() == b"x"


# -- F06 / F10: bounded, single-link reads -----------------------------------------------
def test_reads_are_bounded(area: ApiDataArea, tmp_path) -> None:
    loc = area.path("records", "commits", "big.json")
    area.ensure_dir(loc.parent)
    big = tmp_path / "elevation/records/commits/big.json"
    with big.open("wb") as fh:
        fh.truncate(64 * 1024 * 1024)  # sparse: no real disk use
    with pytest.raises(LimitExceeded):
        area.read_bytes(loc, 1024)
    with pytest.raises(LimitExceeded):
        area.hash_file(loc, 1024)


def test_hash_file_streams_within_limit(area: ApiDataArea) -> None:
    loc = area.path("work", "acquisitions", "r", "a", "original.png")
    area.write_new(loc, b"abc" * 1000)
    import hashlib

    assert area.hash_file(loc, 3000) == (hashlib.sha256(b"abc" * 1000).hexdigest(), 3000)
    with pytest.raises(LimitExceeded):
        area.hash_file(loc, 2999)


def test_hardlink_alias_rejected_for_committed_reads(area: ApiDataArea, tmp_path) -> None:
    loc = area.path("work", "acquisitions", "r", "a", "original.png")
    area.write_new(loc, b"png")
    os.link(tmp_path / "elevation/work/acquisitions/r/a/original.png", tmp_path / "alias")
    for op in (lambda: area.read_bytes(loc, 10), lambda: area.hash_file(loc, 10)):
        with pytest.raises(StorageError):
            op()


def test_link_refuses_source_with_external_alias(area: ApiDataArea, tmp_path) -> None:
    src = area.path("work", "download", "r", "a", "original.part")
    area.write_new(src, b"data")
    os.link(tmp_path / "elevation/work/download/r/a/original.part", tmp_path / "alias")
    with pytest.raises(StorageError):
        area.link_no_clobber(src, area.path("work", "acquisitions", "r", "a", "original.png"))
    assert not (tmp_path / "elevation/work/acquisitions").exists() or not list(
        (tmp_path / "elevation/work/acquisitions").rglob("*.png"))


def test_non_regular_file_rejected(area: ApiDataArea, tmp_path) -> None:
    area.ensure_dir(area.path("records", "commits"))
    os.mkfifo(tmp_path / "elevation/records/commits/fifo.json")
    with pytest.raises(StorageError):
        area.read_bytes(area.path("records", "commits", "fifo.json"), 10)


# -- lock / misc ----------------------------------------------------------------------------
def test_lock_is_exclusive_and_released(area: ApiDataArea) -> None:
    lock = area.path("work", "locks", "download-s.lock")
    with area.exclusive_lock(lock):
        with pytest.raises(StorageError) as err:
            with area.exclusive_lock(lock):
                pass
        assert err.value.error_code == "TARGET_BUSY"
    with area.exclusive_lock(lock):
        pass


def test_missing_data_root_rejected(tmp_path: Path) -> None:
    area = ApiDataArea(tmp_path / "missing", "elevation")
    with pytest.raises(StorageError):
        area.ensure_dir(area.path("work", "download"))
    assert not (tmp_path / "missing").exists()


def test_storage_error_codes() -> None:
    assert storage.storage_error_code(OSError(errno.ENOSPC, "x")) == "STORAGE_FULL"
    assert storage.storage_error_code(OSError(errno.EACCES, "x")) == "PERMISSION_DENIED"
    assert storage.storage_error_code(OSError(errno.ELOOP, "x")) == "PERMISSION_DENIED"
    assert storage.storage_error_code(OSError(errno.EIO, "x")) == "STORAGE_INTEGRITY_FAILED"


def test_unsupported_platform_fails_safe(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "_platform_supported", lambda: False)
    area = ApiDataArea(tmp_path, "elevation")
    with pytest.raises(StorageError) as err:
        area.ensure_dir(area.path("work", "download"))
    assert err.value.error_code == "PERMISSION_DENIED"
    assert not (tmp_path / "elevation").exists()


# -- F12: fixture data root marker -------------------------------------------------------------
def test_fixture_root_marker(tmp_path: Path) -> None:
    root = tmp_path / "fx"
    root.mkdir()
    with ApiDataArea(root, "elevation") as area:
        assert not area.has_fixture_marker()
    init_fixture_data_root(root)
    with ApiDataArea(root, "elevation") as area:
        assert area.has_fixture_marker()
    with pytest.raises(StorageError):
        init_fixture_data_root(root)  # no longer empty


def test_fixture_root_marker_must_be_exact(tmp_path: Path) -> None:
    root = tmp_path / "fx"
    root.mkdir()
    (root / FIXTURE_ROOT_MARKER).write_bytes(b"something else\n")
    with ApiDataArea(root, "elevation") as area:
        assert not area.has_fixture_marker()
    (root / FIXTURE_ROOT_MARKER).unlink()
    real = tmp_path / "real-marker"
    real.write_bytes(storage.FIXTURE_ROOT_MARKER_CONTENT)
    os.symlink(real, root / FIXTURE_ROOT_MARKER)
    with ApiDataArea(root, "elevation") as area:
        assert not area.has_fixture_marker()


@pytest.mark.parametrize("bad", ["missing", "file", "symlink"])
def test_init_fixture_root_refusals(tmp_path: Path, bad: str) -> None:
    target = tmp_path / "t"
    if bad == "file":
        target.write_bytes(b"x")
    elif bad == "symlink":
        (tmp_path / "real").mkdir()
        target.symlink_to(tmp_path / "real", target_is_directory=True)
    with pytest.raises(StorageError):
        init_fixture_data_root(target)


def test_init_fixture_root_refuses_production_root() -> None:
    with pytest.raises((StorageError, OSError)):
        init_fixture_data_root(Path("/data"))
