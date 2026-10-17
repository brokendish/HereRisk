"""Contract tests: Phase 1-D.2 point lookup on Phase 1-D.1 GSI PoC artifacts.

Artifacts are produced by the real D.1 code (``run_fetch_poc``) against an
in-memory fake connection; no real network. Expected values come from the
fixture PNG builder rule or hand-placed pixels, never from the code under test.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path

import pytest

import fixture_builder as fb
from hererisk import cli
from hererisk.common.logging import ListSink, StructuredLogger
from hererisk.common.storage import init_fixture_data_root
from hererisk.elevation.gsi_poc import poc
from hererisk.elevation.gsi_poc.reader import (
    EVIDENCE_INVALID,
    NOT_POC_DIR,
    PNG_MISMATCH,
    PNG_UNDECODABLE,
    STATISTICS_MISMATCH,
    TILE_NOT_FETCHED,
    read_poc_elevation,
)
from hererisk.elevation.lookup.reader import INVALID_COORDINATES, ReadRejected
from test_elevation_reader import _png_with, builder_value, centre
from test_gsi_fetch_poc import FakeHTTP
from test_normalize_stage import _undecodable_png

REPO = fb.REPO_ROOT
TX, TY = 14552, 6451  # tile of Tokyo Station at z14
TOKYO_STATION = (35.681236, 139.767125)


def fetched(tmp_path: Path, body: bytes = fb.make_png(4), lat_lon=TOKYO_STATION) -> Path:
    d = tmp_path / "poc"
    d.mkdir(parents=True, exist_ok=True)
    plan = poc.plan_fetch(*lat_lon, 14, repo_root=REPO)
    poc.run_fetch_poc(plan, d, allow_network=True, protected_roots=(REPO,),
                      connection_factory=FakeHTTP(body=body))
    return d


def files(d: Path) -> dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in d.iterdir()}


def rejected(d, lat, lon, reason, code, zoom=14):
    with pytest.raises(ReadRejected) as err:
        read_poc_elevation(d, lat, lon, zoom)
    assert (err.value.reason, err.value.error_code) == (reason, code)


def evidence_path(d: Path) -> Path:
    return d / f"dem_png_14_{TX}_{TY}.json"


def png_path(d: Path) -> Path:
    return d / f"dem_png_14_{TX}_{TY}.png"


def rewrite(path: Path, data: bytes) -> None:
    path.unlink()
    path.write_bytes(data)


# -- values ---------------------------------------------------------------------------------------
def test_reads_values_from_d1_artifacts(tmp_path) -> None:
    d = fetched(tmp_path)
    before = files(d)
    for px, py in [(0, 0), (93, 0), (255, 255), (17, 130)]:
        result = read_poc_elevation(d, *centre(TX, TY, px, py), 14)
        assert (result.z, result.tile_x, result.tile_y) == (14, TX, TY)
        assert (result.pixel_x, result.pixel_y) == (px, py)
        expected = builder_value(4, px, py)  # seed 4 rule; (93+0+4) % 97 == 0 -> no-data
        assert result.elevation_cm == expected
        assert result.nodata is (expected is None)
        assert result.elevation_m == (None if expected is None else expected / 100)
    doc = read_poc_elevation(d, *TOKYO_STATION, 14).to_dict()
    assert doc["poc_only"] is True and doc["tile"] == {"z": 14, "x": TX, "y": TY}
    assert doc["source"]["provider"] == "国土地理院" and doc["source"]["dataset"] == "DEM10B"
    assert doc["source"]["approved_for_publication"] is False
    assert "vertical_reference" in doc["source"]["unconfirmed"]
    assert doc["source"]["png_sha256"] == hashlib.sha256(fb.make_png(4)).hexdigest()
    assert files(d) == before  # read only


def test_zero_negative_positive_and_nodata(tmp_path) -> None:
    special = {(10, 20): (0, 0, 0), (11, 20): (255, 255, 136), (12, 20): (128, 0, 0),
               (13, 20): (0, 4, 210)}
    d = fetched(tmp_path, _png_with(special))
    got = {px: read_poc_elevation(d, *centre(TX, TY, px, 20), 14) for px in (10, 11, 12, 13)}
    assert (got[10].elevation_cm, got[10].elevation_m, got[10].nodata) == (0, 0.0, False)
    assert (got[11].elevation_cm, got[11].elevation_m, got[11].nodata) == (-120, -1.2, False)
    assert (got[12].elevation_cm, got[12].elevation_m, got[12].nodata) == (None, None, True)
    assert (got[13].elevation_cm, got[13].elevation_m) == (1234, 12.34)


def test_second_fetched_tile_is_readable(tmp_path) -> None:
    fetched(tmp_path)
    east = (TOKYO_STATION[0], TOKYO_STATION[1] + 360 / 2**14)
    d = fetched(tmp_path, fb.make_png(5), east)
    assert read_poc_elevation(d, *centre(TX + 1, TY, 7, 9), 14).elevation_cm == builder_value(5, 7, 9)


# -- not available / invalid input -------------------------------------------------------------------
def test_tile_not_fetched(tmp_path) -> None:
    d = fetched(tmp_path)
    rejected(d, *centre(TX + 5, TY, 0, 0), TILE_NOT_FETCHED, "TARGET_UNCONFIGURED")
    rejected(d, *TOKYO_STATION, TILE_NOT_FETCHED, "TARGET_UNCONFIGURED", zoom=13)


@pytest.mark.parametrize("lat,lon,zoom", [(91.0, 0.0, 14), (0.0, 180.0, 14),
                                          (float("nan"), 0.0, 14), (35.0, 139.0, 31)])
def test_invalid_coordinates(tmp_path, lat, lon, zoom) -> None:
    rejected(fetched(tmp_path), lat, lon, INVALID_COORDINATES, "INVALID_INPUT", zoom)


def test_not_a_poc_directory(tmp_path) -> None:
    d = fetched(tmp_path)
    plain = tmp_path / "plain"
    plain.mkdir()
    rejected(plain, *TOKYO_STATION, NOT_POC_DIR, "INVALID_INPUT")
    rejected(tmp_path / "missing", *TOKYO_STATION, NOT_POC_DIR, "INVALID_INPUT")
    link = tmp_path / "link"
    link.symlink_to(d, target_is_directory=True)
    rejected(link, *TOKYO_STATION, NOT_POC_DIR, "INVALID_INPUT")
    (d / poc.POC_MARKER).unlink()
    (d / poc.POC_MARKER).write_bytes(b"wrong\n")
    rejected(d, *TOKYO_STATION, NOT_POC_DIR, "INVALID_INPUT")


def test_marker_must_be_single_link_regular_file(tmp_path) -> None:
    d = fetched(tmp_path)
    os.link(d / poc.POC_MARKER, tmp_path / "alias")
    rejected(d, *TOKYO_STATION, NOT_POC_DIR, "INVALID_INPUT")


def test_fixture_data_root_is_not_a_poc_directory(tmp_path) -> None:
    d = tmp_path / "fx"
    d.mkdir()
    init_fixture_data_root(d)
    (d / poc.POC_MARKER).write_bytes(poc.POC_MARKER_CONTENT)
    rejected(d, *TOKYO_STATION, NOT_POC_DIR, "INVALID_INPUT")


def test_ancestor_symlink_rejected(tmp_path) -> None:
    d = fetched(tmp_path)
    real_parent = tmp_path / "real"
    d.rename(tmp_path / "moved")
    real_parent.mkdir()
    (tmp_path / "moved").rename(real_parent / "poc")
    alias = tmp_path / "alias-parent"
    alias.symlink_to(real_parent, target_is_directory=True)
    # A path through a symlinked ancestor resolves to the real directory (allowed)...
    assert read_poc_elevation(alias / "poc", *TOKYO_STATION, 14).tile_x == TX
    # ...but the directory itself may not be a symlink.
    (tmp_path / "direct").symlink_to(real_parent / "poc", target_is_directory=True)
    rejected(tmp_path / "direct", *TOKYO_STATION, NOT_POC_DIR, "INVALID_INPUT")


# -- evidence / PNG integrity -------------------------------------------------------------------------------
def test_missing_evidence_or_png(tmp_path) -> None:
    d = fetched(tmp_path)
    png_path(d).unlink()
    rejected(d, *TOKYO_STATION, PNG_MISMATCH, "STORAGE_INTEGRITY_FAILED")
    d2 = fetched(tmp_path / "b")
    evidence_path(d2).unlink()
    rejected(d2, *TOKYO_STATION, TILE_NOT_FETCHED, "TARGET_UNCONFIGURED")


@pytest.mark.parametrize(
    "edit",
    [
        lambda e: e.update(poc_only=False),
        lambda e: e.update(schema="other"),
        lambda e: e["checks"].update(decode="failed"),
        lambda e: e.update(http_status=206),
        lambda e: e.update(content_type="text/html"),
        lambda e: e["tile"].update(x=TX + 1),
        lambda e: e.update(url="https://evil.example/x.png"),
        lambda e: e.update(png_file="../../etc/passwd"),
        lambda e: e["source_definition"].update(source_ref="other"),
        lambda e: e.pop("sha256"),
    ],
    ids=["poc-only", "schema", "check", "status", "ctype", "tile", "url", "traversal",
         "source", "no-sha"],
)
def test_tampered_evidence_rejected(tmp_path, edit) -> None:
    d = fetched(tmp_path)
    doc = json.loads(evidence_path(d).read_bytes())
    edit(doc)
    rewrite(evidence_path(d), json.dumps(doc).encode())
    rejected(d, *TOKYO_STATION, EVIDENCE_INVALID, "RECOVERY_REQUIRED")


@pytest.mark.parametrize("data", [b"{not json", b'{"a":1,"a":2}', b"[]", b'{"x":NaN}'])
def test_corrupt_evidence_rejected(tmp_path, data) -> None:
    d = fetched(tmp_path)
    rewrite(evidence_path(d), data)
    rejected(d, *TOKYO_STATION, EVIDENCE_INVALID, "RECOVERY_REQUIRED")


def test_oversized_evidence_rejected(tmp_path) -> None:
    d = fetched(tmp_path)
    evidence_path(d).unlink()
    with evidence_path(d).open("wb") as fh:
        fh.truncate(64 * 1024 * 1024)
    rejected(d, *TOKYO_STATION, EVIDENCE_INVALID, "RECOVERY_REQUIRED")


def test_png_sha_and_size_mismatch(tmp_path) -> None:
    d = fetched(tmp_path)
    rewrite(png_path(d), fb.make_png(9))  # valid PNG, different bytes
    rejected(d, *TOKYO_STATION, PNG_MISMATCH, "STORAGE_INTEGRITY_FAILED")
    d2 = fetched(tmp_path / "b")
    rewrite(png_path(d2), png_path(d2).read_bytes() + b"x")
    rejected(d2, *TOKYO_STATION, PNG_MISMATCH, "STORAGE_INTEGRITY_FAILED")


def test_png_hardlink_and_symlink_rejected(tmp_path) -> None:
    d = fetched(tmp_path)
    os.link(png_path(d), tmp_path / "png-alias")
    rejected(d, *TOKYO_STATION, PNG_MISMATCH, "STORAGE_INTEGRITY_FAILED")
    d2 = fetched(tmp_path / "b")
    real = tmp_path / "elsewhere.png"
    real.write_bytes(png_path(d2).read_bytes())
    png_path(d2).unlink()
    png_path(d2).symlink_to(real)
    rejected(d2, *TOKYO_STATION, PNG_MISMATCH, "STORAGE_INTEGRITY_FAILED")
    d3 = fetched(tmp_path / "c")
    os.link(evidence_path(d3), tmp_path / "ev-alias")
    rejected(d3, *TOKYO_STATION, EVIDENCE_INVALID, "RECOVERY_REQUIRED")


def _resign(d: Path, png: bytes, stats=None) -> None:
    """Replace the PNG and make the evidence agree with its bytes (forged but consistent)."""
    rewrite(png_path(d), png)
    doc = json.loads(evidence_path(d).read_bytes())
    doc.update(sha256=hashlib.sha256(png).hexdigest(), size_bytes=len(png))
    if stats is not None:
        doc["statistics"] = stats
    rewrite(evidence_path(d), json.dumps(doc).encode())


def test_undecodable_png_rejected_even_if_hashes_agree(tmp_path) -> None:
    d = fetched(tmp_path)
    _resign(d, _undecodable_png())
    rejected(d, *TOKYO_STATION, PNG_UNDECODABLE, "PNG_INVALID")


def test_statistics_mismatch_rejected(tmp_path) -> None:
    d = fetched(tmp_path)
    _resign(d, fb.make_png(9))  # consistent hash, but the evidence statistics are seed 4's
    rejected(d, *TOKYO_STATION, STATISTICS_MISMATCH, "RECOVERY_REQUIRED")


# -- CLI -------------------------------------------------------------------------------------------------------
KEYS = {"status", "error_code", "reason", "message", "tile", "pixel", "elevation_cm",
        "elevation_m", "nodata", "poc_only", "source"}


def run_cli(argv):
    args = cli.build_parser().parse_args(argv)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli._gsi_elevation_poc(args, StructuredLogger(sink := ListSink()))
    lines = buf.getvalue().splitlines()
    assert len(lines) == 1
    doc = json.loads(lines[0])
    assert set(doc) == KEYS
    return code, doc, sink.entries


def test_cli_success(tmp_path) -> None:
    d = fetched(tmp_path)
    lat, lon = centre(TX, TY, 17, 130)
    code, doc, logs = run_cli(["gsi-elevation-poc", "--lat", repr(lat), "--lon", repr(lon),
                               "--zoom", "14", "--poc-dir", str(d)])
    assert code == 0 and doc["status"] == "SUCCESS" and doc["poc_only"] is True
    assert doc["elevation_cm"] == builder_value(4, 17, 130)
    assert doc["elevation_m"] == builder_value(4, 17, 130) / 100
    assert doc["source"]["dataset"] == "DEM10B"
    text = json.dumps(doc) + json.dumps(logs)
    assert repr(lat)[:8] not in text and str(d) not in text  # no coordinates / paths


@pytest.mark.parametrize(
    "argv,code,reason",
    [
        (["--lat", "abc", "--lon", "139", "--zoom", "14"], 2, INVALID_COORDINATES),
        (["--lat", "35.681236", "--lon", "139.767125", "--zoom", "x"], 2, INVALID_COORDINATES),
        (["--lat", "35.0", "--lon", "135.0", "--zoom", "14"], 3, TILE_NOT_FETCHED),
    ],
)
def test_cli_errors(tmp_path, argv, code, reason) -> None:
    d = fetched(tmp_path)
    rc, doc, _ = run_cli(["gsi-elevation-poc", *argv, "--poc-dir", str(d)])
    assert (rc, doc["reason"]) == (code, reason) and doc["status"] != "SUCCESS"
    assert doc["elevation_cm"] is None and doc["nodata"] is None


def test_cli_subprocess_no_network(tmp_path) -> None:
    from test_cli import cli as child

    d = fetched(tmp_path)
    before = files(d)
    proc = child("gsi-elevation-poc", "--lat", "35.681236", "--lon", "139.767125",
                 "--zoom", "14", "--poc-dir", str(d))
    assert proc.returncode == 0 and json.loads(proc.stdout)["status"] == "SUCCESS"
    assert files(d) == before


def test_reader_does_not_load_network_code() -> None:
    import subprocess
    import sys

    code = ("import sys\nimport hererisk.elevation.gsi_poc.reader\n"
            "print([m for m in sys.modules if m in ('http.client', 'socket', 'ssl')"
            " or m.endswith('gsi_poc.http_fetch')])\n")
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          env=dict(os.environ, PYTHONPATH=str(REPO / "src")), timeout=60)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "[]"


def test_oversized_files_are_not_read(tmp_path, monkeypatch) -> None:
    d = fetched(tmp_path)
    evidence_path(d).unlink()
    with evidence_path(d).open("wb") as fh:
        fh.truncate(64 * 1024 * 1024)
    read_bytes = []
    real_read = os.read

    def counting(fd, n):
        data = real_read(fd, n)
        read_bytes.append(len(data))
        return data

    monkeypatch.setattr(os, "read", counting)
    rejected(d, *TOKYO_STATION, EVIDENCE_INVALID, "RECOVERY_REQUIRED")
    assert sum(read_bytes) < 1024  # only the small marker was read, never the big file
