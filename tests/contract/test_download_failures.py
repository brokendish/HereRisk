"""Contract tests: execution failures via fault injection never yield SUCCESS."""

from __future__ import annotations

import errno
import json
import os
from pathlib import Path

import pytest

from hererisk.common.result import PipelineError, Status
from hererisk.common.storage import ApiDataArea, StorageError
from hererisk.elevation.download.transport import FixtureTransport, TransportResponse


def markers(harness) -> list[Path]:
    d = harness.api_root / "records" / "commits"
    return sorted(d.glob("*.json")) if d.exists() else []


def parts(harness) -> list[Path]:
    return sorted((harness.api_root / "work" / "download").rglob("*.part"))


# -- transport / representation ----------------------------------------------
def test_missing_fixture_fails_after_committing_first_tile(harness) -> None:
    (harness.fixture_root / "tiles/dem_png/14/14551/6450.png").unlink()
    result = harness.run()
    assert result.status is Status.FAILED and result.error_code == "HTTP_404"
    assert result.exit_code == 10
    # The first tile was committed and is reported; the request is not SUCCESS.
    assert len(result.artifacts) == 1 and len(markers(harness)) == 1


class InterruptingTransport(FixtureTransport):
    def _read(self, handle):
        with handle:
            yield handle.read(1000)
            raise PipelineError("TRANSFER_INTERRUPTED", "simulated")


def test_read_interruption_leaves_unconsumable_part(harness) -> None:
    harness.transport = InterruptingTransport(harness.fixture_root / "tiles")
    result = harness.run()
    assert result.status is Status.FAILED and result.error_code == "TRANSFER_INTERRUPTED"
    assert result.artifacts == () and markers(harness) == []
    assert len(parts(harness)) == 1  # quarantined, never promoted


class LyingLengthTransport(FixtureTransport):
    def fetch(self, url):
        r = super().fetch(url)
        return TransportResponse(r.effective_url, r.content_type, r.content_length + 1, r.chunks)


def test_length_mismatch_is_interruption(harness) -> None:
    harness.transport = LyingLengthTransport(harness.fixture_root / "tiles")
    assert harness.run().error_code == "TRANSFER_INTERRUPTED"
    assert markers(harness) == []


class WrongTypeTransport(FixtureTransport):
    def fetch(self, url):
        r = super().fetch(url)
        return TransportResponse(r.effective_url, "text/html", r.content_length, r.chunks)


class RedirectTransport(FixtureTransport):
    def fetch(self, url):
        r = super().fetch(url)
        return TransportResponse(url.replace("6450", "6451"), r.content_type, r.content_length, r.chunks)


@pytest.mark.parametrize(
    "cls,code", [(WrongTypeTransport, "CONTENT_TYPE_INVALID"), (RedirectTransport, "REDIRECT_REJECTED")]
)
def test_response_checks(harness, cls, code) -> None:
    harness.transport = cls(harness.fixture_root / "tiles")
    result = harness.run()
    assert result.status is Status.FAILED and result.error_code == code
    assert markers(harness) == []


def test_corrupt_png_rejected(harness) -> None:
    tile = harness.fixture_root / "tiles/dem_png/14/14550/6450.png"
    tile.write_bytes(tile.read_bytes()[:-1] + b"\x00")
    result = harness.run()
    assert result.error_code == "PNG_INVALID" and result.exit_code == 11
    assert markers(harness) == [] and not list((harness.api_root / "work/acquisitions").rglob("*.png"))


def test_empty_and_oversize_bodies_rejected(harness) -> None:
    tile = harness.fixture_root / "tiles/dem_png/14/14550/6450.png"
    tile.write_bytes(b"")
    assert harness.run().error_code == "SIZE_INVALID"
    tile.write_bytes(b"\x89PNG" + b"0" * (1048576 + 1))
    assert harness.run().error_code == "SIZE_INVALID"
    assert markers(harness) == []


# -- storage ---------------------------------------------------------------
def test_permission_denied(harness) -> None:
    if os.geteuid() == 0:
        pytest.skip("root ignores permissions")
    assert harness.run().status is Status.SUCCESS  # creates the layout
    download = harness.api_root / "work" / "download"
    download.chmod(0o500)
    try:
        result = harness.run()
    finally:
        download.chmod(0o750)
    assert result.status is Status.FAILED and result.error_code == "PERMISSION_DENIED"
    assert result.exit_code == 12


class _FullHandle:
    def __init__(self, handle):
        self._h = handle

    def write(self, data):
        raise OSError(errno.ENOSPC, "No space left on device")

    def __getattr__(self, name):
        return getattr(self._h, name)


class DiskFullArea(ApiDataArea):
    def open_exclusive(self, path):
        handle = super().open_exclusive(path)
        return _FullHandle(handle) if path.name.endswith(".part") else handle


class CorruptReadArea(ApiDataArea):
    def read_bytes(self, path, max_bytes):
        data = super().read_bytes(path, max_bytes)
        return data[:-1] + bytes([data[-1] ^ 1]) if path.name.endswith(".part") else data


def failing_write_area(fragment: str, *, after: bool = False, exc: BaseException | None = None):
    class FailingWriteArea(ApiDataArea):
        def write_new(self, path, data):
            hit = fragment in str(path)
            if hit and not after:
                raise exc or StorageError("STORAGE_INTEGRITY_FAILED", "injected")
            super().write_new(path, data)
            if hit and after:
                raise exc or StorageError("STORAGE_INTEGRITY_FAILED", "injected")

    return FailingWriteArea


@pytest.mark.parametrize(
    "area_cls,code,exit_code",
    [
        (DiskFullArea, "STORAGE_FULL", 12),
        (CorruptReadArea, "STORAGE_INTEGRITY_FAILED", 12),
        (failing_write_area("/records/acquisitions/"), "RECORD_COMMIT_FAILED", 13),
        (failing_write_area("/records/commits/"), "RECORD_COMMIT_FAILED", 13),
    ],
    ids=["disk-full", "sha-mismatch", "record-write", "marker-write"],
)
def test_storage_and_commit_failures(harness, area_cls, code, exit_code) -> None:
    harness.area_factory = area_cls
    result = harness.run()
    assert result.status is Status.FAILED and result.error_code == code
    assert result.exit_code == exit_code
    assert result.artifacts == () and markers(harness) == []


def test_record_without_marker_is_not_consumable(harness) -> None:
    harness.area_factory = failing_write_area("/records/commits/")
    result = harness.run()
    records = list((harness.api_root / "records/acquisitions").rglob("*.json"))
    assert len(records) == 1 and markers(harness) == []
    harness.area_factory = ApiDataArea
    again = harness.run(resume=result.run_id)
    assert again.status is Status.BLOCKED and again.error_code == "RECOVERY_REQUIRED"
    assert again.artifacts == ()


def test_unexpected_exception_is_internal_error_without_leak(harness) -> None:
    class Boom(FixtureTransport):
        def fetch(self, url):
            raise RuntimeError(f"secret detail {url} /private/path")

    harness.transport = Boom(harness.fixture_root / "tiles")
    result = harness.run()
    assert result.error_code == "INTERNAL_ERROR" and result.exit_code == 14
    text = json.dumps(result.to_dict()) + json.dumps(harness.sink.entries)
    assert "secret" not in text and "/private/path" not in text and "fixture.invalid" not in text
