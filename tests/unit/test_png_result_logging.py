"""Unit tests: PNG container check, result contract, structured logging."""

from __future__ import annotations

import struct
import zlib

import pytest

import fixture_builder as fb
from hererisk.common.logging import ListSink, StructuredLogger
from hererisk.common.result import ERROR_CODES, Artifact, ModuleResult, PipelineError, Status
from hererisk.elevation.download.png import check_png

GOOD = fb.make_png(1)


def check(data: bytes) -> None:
    check_png(data, width=256, height=256, bit_depth=8, color_type=2)


def test_png_valid() -> None:
    check(GOOD)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"GIF89a" + GOOD[6:],
        GOOD[:-5],  # truncated
        GOOD + b"\x00",  # trailing data
        GOOD[:40] + bytes([GOOD[40] ^ 0xFF]) + GOOD[41:],  # CRC broken inside IDAT
        fb.make_png(1, width=128),  # wrong dimension
    ],
)
def test_png_invalid(data: bytes) -> None:
    with pytest.raises(PipelineError) as err:
        check(data)
    assert err.value.error_code == "PNG_INVALID"


def test_png_wrong_colour_type() -> None:
    ihdr = struct.pack(">IIBBBBB", 256, 256, 8, 6, 0, 0, 0)  # RGBA
    body = b"IHDR" + ihdr
    data = (
        GOOD[:8]
        + struct.pack(">I", 13)
        + body
        + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        + GOOD[33:]
    )
    with pytest.raises(PipelineError):
        check(data)


def test_exit_codes_match_contract() -> None:
    expected = {
        "TARGET_UNCONFIGURED": 3, "APPROVAL_REQUIRED": 3, "TARGET_BUSY": 3,
        "RECOVERY_REQUIRED": 3, "INVALID_INPUT": 2, "INVALID_CONFIGURATION": 2,
        "HTTP_404": 10, "TRANSFER_INTERRUPTED": 10, "PNG_INVALID": 11, "SIZE_INVALID": 11,
        "CONTENT_TYPE_INVALID": 11, "STORAGE_FULL": 12, "PERMISSION_DENIED": 12,
        "STORAGE_INTEGRITY_FAILED": 12, "RECORD_COMMIT_FAILED": 13, "INTERNAL_ERROR": 14,
    }
    for code, exit_code in expected.items():
        assert ModuleResult.error("r", "download", code).exit_code == exit_code
    assert ModuleResult.success("r", "download", ()).exit_code == 0
    assert {s for s, _ in ERROR_CODES.values()} == {Status.FAILED, Status.BLOCKED}


def test_result_invariants() -> None:
    art = Artifact("a", "a", "acquisitions/r/a.json", "0" * 64, 1)
    with pytest.raises(ValueError):
        ModuleResult("r", "download", Status.BLOCKED, "TARGET_BUSY", "m", (art,))
    with pytest.raises(ValueError):
        ModuleResult("r", "download", Status.FAILED, "TARGET_BUSY", "m")
    with pytest.raises(ValueError):
        ModuleResult("r", "download", Status.SUCCESS, "INTERNAL_ERROR", "m")
    with pytest.raises(ValueError):
        PipelineError("NOT_A_CODE")
    assert set(ModuleResult.error("r", "download", "HTTP_404").to_dict()) == {
        "run_id", "module", "status", "artifacts", "error_code", "message"}


def test_logger_fields_and_binding() -> None:
    sink = ListSink()
    log = StructuredLogger(sink, module="download").bind(api_id="elevation", run_id="r1")
    log.info("started")
    log.error("failed", error_code="HTTP_404")
    assert [set(e) for e in sink.entries] == [
        {"timestamp", "level", "module", "api_id", "run_id", "error_code", "message"}
    ] * 2
    assert sink.entries[1]["level"] == "ERROR" and sink.entries[1]["error_code"] == "HTTP_404"
    with pytest.raises(ValueError):
        log.log("DEBUG", "x")
