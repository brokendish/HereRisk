"""Unit tests: common storage (confinement, no-clobber, durability calls, lock)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from hererisk.common import storage
from hererisk.common.storage import ApiDataArea, StorageError


@pytest.fixture
def area(tmp_path: Path) -> ApiDataArea:
    return ApiDataArea(tmp_path, "elevation")


def test_write_new_creates_and_never_overwrites(area: ApiDataArea) -> None:
    target = area.path("records", "commits", "a.json")
    area.ensure_dir(target.parent)
    area.write_new(target, b"one")
    with pytest.raises(StorageError) as err:
        area.write_new(target, b"two")
    assert err.value.error_code == "STORAGE_INTEGRITY_FAILED"
    assert target.read_bytes() == b"one"
    assert [p.name for p in target.parent.iterdir()] == ["a.json"]  # no temp leftovers


def test_link_no_clobber_refuses_existing_target(area: ApiDataArea) -> None:
    d = area.path("work", "download", "r")
    area.ensure_dir(d)
    (d / "src").write_bytes(b"new")
    (d / "dst").write_bytes(b"old")
    with pytest.raises(StorageError):
        area.link_no_clobber(d / "src", d / "dst")
    assert (d / "dst").read_bytes() == b"old"


@pytest.mark.parametrize(
    "parts",
    [
        ("dl", "current", "x"),
        ("rel", "versions", "x"),
        ("records", "registry", "x"),
        ("work", "download", ".."),
        ("work", "download", "../../flood"),
        ("work", "download", "/abs"),
        ("work",),
    ],
)
def test_path_outside_writable_areas_rejected(area: ApiDataArea, parts) -> None:
    with pytest.raises(StorageError) as err:
        area.path(*parts)
    assert err.value.error_code == "PERMISSION_DENIED"


def test_symlink_in_area_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "elevation").mkdir()
    os.symlink(outside, tmp_path / "elevation" / "work")
    area = ApiDataArea(tmp_path, "elevation")
    with pytest.raises(StorageError):
        area.path("work", "download", "r")
    assert list(outside.iterdir()) == []


def test_ensure_dir_requires_existing_data_root(tmp_path: Path) -> None:
    area = ApiDataArea(tmp_path / "missing", "elevation")
    with pytest.raises(StorageError):
        area.ensure_dir(area.path("work", "download"))
    assert not (tmp_path / "missing").exists()


def test_files_and_dirs_are_fsynced(area: ApiDataArea, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    real = storage.fsync_fd
    monkeypatch.setattr(storage, "fsync_fd", lambda fd: (calls.append(fd), real(fd)))
    target = area.path("records", "commits", "b.json")
    area.ensure_dir(target.parent)
    calls.clear()
    area.write_new(target, b"x")
    # file + target dir after link + dir after unlink of temp name
    assert len(calls) >= 3


def test_lock_is_exclusive_and_released(area: ApiDataArea) -> None:
    lock = area.path("work", "locks", "download-s.lock")
    area.ensure_dir(lock.parent)
    with area.exclusive_lock(lock):
        with pytest.raises(StorageError) as err:
            with area.exclusive_lock(lock):
                pass
        assert err.value.error_code == "TARGET_BUSY"
    with area.exclusive_lock(lock):
        pass


def test_storage_error_codes() -> None:
    import errno

    assert storage.storage_error_code(OSError(errno.ENOSPC, "x")) == "STORAGE_FULL"
    assert storage.storage_error_code(OSError(errno.EACCES, "x")) == "PERMISSION_DENIED"
    assert storage.storage_error_code(OSError(errno.EIO, "x")) == "STORAGE_INTEGRITY_FAILED"
