"""CLI tests: ``hererisk-pipeline elevation`` (read-only point elevation).

Artifacts are produced by the real fixture pipeline through the CLI
(``pipeline`` command); the child processes run with the socket/DNS guard of
test_cli. Expected values come from the fixture PNG generation rule or from
hand-placed pixel values, never from the code under test.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import fixture_builder as fb
from test_cli import FIXTURE, cli, fixture_root
from test_elevation_reader import _png_with, builder_value, centre

KEYS = {"status", "error_code", "reason", "message", "run_id", "acquisition_id",
        "candidate_sha256", "tile", "pixel", "elevation_cm", "nodata"}


def pipeline(root: Path, region="13", source="fixture-dem-png-tokyo", fixture=FIXTURE) -> str:
    proc = cli("pipeline", "--api", "elevation", "--region", region, "--source", source,
               "--fixture", str(fixture), "--data-root", str(root))
    assert proc.returncode == 0, proc.stdout
    return json.loads(proc.stdout)["run_id"]


def elevation(root: Path, run_id: str, lat, lon, zoom="14"):
    proc = cli("elevation", "--run-id", run_id, "--lat", str(lat), "--lon", str(lon),
               "--zoom", str(zoom), "--data-root", str(root))
    lines = proc.stdout.splitlines()
    assert len(lines) == 1, proc.stdout  # exactly one JSON line; logs on stderr
    doc = json.loads(lines[0])
    assert set(doc) == KEYS
    return proc, doc


def tree(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def tokyo(tmp_path):
    root = fixture_root(tmp_path)
    return root, pipeline(root)


# -- success --------------------------------------------------------------------------------
def test_one_tile_value(tmp_path) -> None:
    root = fixture_root(tmp_path)
    run_id = pipeline(root, "27", "fixture-dem-png-osaka")
    proc, doc = elevation(root, run_id, *centre(14370, 6495, 37, 200))
    assert proc.returncode == 0
    assert doc["status"] == "SUCCESS" and doc["error_code"] is None and doc["reason"] is None
    assert doc["run_id"] == run_id
    assert doc["tile"] == {"z": 14, "x": 14370, "y": 6495}
    assert doc["pixel"] == {"x": 37, "y": 200}
    assert doc["elevation_cm"] == builder_value(1, 37, 200) and doc["nodata"] is False
    logs = [json.loads(line) for line in proc.stderr.splitlines()]
    assert logs and all(e["run_id"] == run_id for e in logs)


def test_two_tiles_values(tokyo) -> None:
    root, run_id = tokyo
    for tx, seed in ((14550, 2), (14551, 3)):
        for px, py in ((0, 0), (255, 255), (120, 33)):
            proc, doc = elevation(root, run_id, *centre(tx, 6450, px, py))
            assert proc.returncode == 0
            assert doc["tile"]["x"] == tx and doc["pixel"] == {"x": px, "y": py}
            assert doc["elevation_cm"] == builder_value(seed, px, py)
    assert len({elevation(root, run_id, *centre(tx, 6450, 1, 1))[1]["acquisition_id"]
                for tx in (14550, 14551)}) == 2


def test_zero_negative_and_nodata_are_distinct(tmp_path) -> None:
    fixture = fb.build_tree(tmp_path / "fx")
    special = {(10, 20): (0, 0, 0), (11, 20): (255, 255, 136), (12, 20): (128, 0, 0)}
    (fixture / "tiles/dem_png/14/14370/6495.png").write_bytes(_png_with(special))
    root = fixture_root(tmp_path)
    run_id = pipeline(root, "27", "fixture-dem-png-osaka", fixture)
    results = {px: elevation(root, run_id, *centre(14370, 6495, px, 20)) for px in (10, 11, 12)}
    assert all(proc.returncode == 0 for proc, _ in results.values())
    assert (results[10][1]["elevation_cm"], results[10][1]["nodata"]) == (0, False)
    assert (results[11][1]["elevation_cm"], results[11][1]["nodata"]) == (-120, False)
    assert (results[12][1]["elevation_cm"], results[12][1]["nodata"]) == (None, True)
    assert results[12][1]["status"] == "SUCCESS"  # no-data is a successful read


# -- not successful -----------------------------------------------------------------------------
def test_tile_not_in_run_is_not_nodata(tokyo) -> None:
    root, run_id = tokyo
    proc, doc = elevation(root, run_id, *centre(14370, 6495, 0, 0))  # Osaka tile, Tokyo run
    assert proc.returncode == 3
    assert (doc["status"], doc["error_code"], doc["reason"]) == \
        ("BLOCKED", "TARGET_UNCONFIGURED", "TILE_NOT_IN_RUN")
    assert doc["elevation_cm"] is None and doc["nodata"] is None and doc["tile"] is None


@pytest.mark.parametrize(
    "lat,lon,zoom",
    [("91", "139", "14"), ("35", "180", "14"), ("nan", "139", "14"), ("inf", "139", "14"),
     ("abc", "139", "14"), ("35", "", "14"), ("35", "139", "31"), ("35", "139", "14.0"),
     ("35", "139", "-1"), ("35", "139", "x")],
)
def test_invalid_coordinates(tokyo, lat, lon, zoom) -> None:
    root, run_id = tokyo
    proc, doc = elevation(root, run_id, lat, lon, zoom)
    assert proc.returncode == 2
    assert (doc["status"], doc["error_code"], doc["reason"]) == \
        ("FAILED", "INVALID_INPUT", "INVALID_COORDINATES")


@pytest.mark.parametrize("run_id", ["not-a-uuid", "../../etc/passwd", "11111111-1111-1111-8111-111111111111"])
def test_invalid_run_id_not_echoed(tokyo, run_id) -> None:
    root, _ = tokyo
    proc, doc = elevation(root, run_id, 35.0, 139.0)
    assert proc.returncode == 2
    assert (doc["error_code"], doc["reason"], doc["run_id"]) == ("INVALID_INPUT", "INVALID_RUN", None)
    assert run_id not in proc.stdout and run_id not in proc.stderr


def test_unknown_or_unvalidated_run(tmp_path, tokyo) -> None:
    root, run_id = tokyo
    proc, doc = elevation(root, "22222222-2222-4222-8222-222222222222", 35.0, 139.0)
    assert proc.returncode == 2 and doc["reason"] == "NOT_VALIDATED"
    vrec = root / f"elevation/records/validations/{run_id}.json"
    record = json.loads(vrec.read_bytes())
    record["status"] = "FAILED"
    vrec.unlink()
    vrec.write_bytes(json.dumps(record).encode())
    proc, doc = elevation(root, run_id, *centre(14550, 6450, 0, 0))
    assert proc.returncode == 2 and (doc["error_code"], doc["reason"]) == ("INVALID_INPUT", "NOT_VALIDATED")


def test_corrupted_candidate(tokyo) -> None:
    root, run_id = tokyo
    nrec = json.loads((root / f"elevation/records/normalizations/{run_id}.json").read_bytes())
    path = root / f"elevation/work/normalized/{run_id}/{nrec['outputs'][0]['acquisition_id']}.json"
    data = path.read_bytes().replace(b"2000", b"2001", 1)
    path.unlink()
    path.write_bytes(data)
    proc, doc = elevation(root, run_id, *centre(14550, 6450, 0, 0))
    assert proc.returncode == 12
    assert (doc["status"], doc["error_code"], doc["reason"]) == \
        ("FAILED", "STORAGE_INTEGRITY_FAILED", "CANDIDATE_CORRUPTED")


def test_non_fixture_or_missing_root(tmp_path, tokyo) -> None:
    root, run_id = tokyo
    plain = tmp_path / "plain"
    plain.mkdir()
    proc, doc = elevation(plain, run_id, 35.0, 139.0)
    assert proc.returncode == 3 and doc["reason"] == "NOT_FIXTURE"
    proc, doc = elevation(tmp_path / "missing", run_id, 35.0, 139.0)
    assert proc.returncode == 12 and doc["status"] == "FAILED" and doc["reason"] is None
    assert str(tmp_path) not in proc.stdout + proc.stderr  # no internal paths


def test_no_coordinates_or_paths_in_output(tokyo) -> None:
    root, run_id = tokyo
    lat, lon = centre(14550, 6450, 3, 4)
    proc, _ = elevation(root, run_id, lat, lon)
    for secret in (repr(lat)[:8], repr(lon)[:8], str(root)):
        assert secret not in proc.stdout and secret not in proc.stderr


def test_missing_arguments_use_fixed_usage_error(tokyo) -> None:
    root, run_id = tokyo
    proc = cli("elevation", "--run-id", run_id, "--lat", "35", "--zoom", "14",
               "--data-root", str(root))  # --lon missing
    assert proc.returncode == 2 and proc.stdout == ""
    assert proc.stderr == "hererisk-pipeline: invalid arguments (see --help)\n"


# -- read only / regression ----------------------------------------------------------------------
def test_data_root_unchanged(tokyo) -> None:
    root, run_id = tokyo
    before = tree(root)
    for tx in (14550, 14551):
        elevation(root, run_id, *centre(tx, 6450, 7, 7))
    elevation(root, run_id, 35.0, 139.0)  # rejected read
    elevation(root, run_id, "nan", "0")
    assert tree(root) == before


def test_existing_commands_unchanged(tmp_path) -> None:
    root = fixture_root(tmp_path)
    proc = cli("download", "--api", "elevation", "--region", "13",
               "--source", "fixture-dem-png-tokyo", "--fixture", str(FIXTURE),
               "--data-root", str(root))
    assert proc.returncode == 0 and json.loads(proc.stdout)["module"] == "download"
