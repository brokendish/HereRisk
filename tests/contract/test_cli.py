"""Contract tests: CLI process (stdout JSON only, stderr logs, exit codes).

Runs the CLI as a subprocess. The child process has no socket guard, but the
only transport it can construct is FixtureTransport (no socket code exists).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import fixture_builder as fb

REPO = fb.REPO_ROOT
FIXTURE = REPO / "tests" / "fixtures" / "elevation-fixture"


def cli(*args: str, cwd: Path = REPO) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    return subprocess.run(
        [sys.executable, "-m", "hererisk.cli", *args],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=60, check=False,
    )


def test_committed_fixture_tree_is_current(tmp_path: Path) -> None:
    rebuilt = fb.build_tree(tmp_path / "t")
    for path in rebuilt.rglob("*"):
        if path.is_file():
            assert (FIXTURE / path.relative_to(rebuilt)).read_bytes() == path.read_bytes(), path


def test_cli_fixture_success(tmp_path: Path) -> None:
    proc = cli("download", "--api", "elevation", "--region", "13",
               "--source", "fixture-dem-png-tokyo", "--fixture", str(FIXTURE),
               "--data-root", str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert result["status"] == "SUCCESS" and len(result["artifacts"]) == 2
    logs = [json.loads(line) for line in proc.stderr.splitlines()]
    assert logs and all(e["run_id"] == result["run_id"] for e in logs)
    for art in result["artifacts"]:
        assert (tmp_path / "elevation/records" / art["record_ref"]).is_file()
        assert (tmp_path / f"elevation/records/commits/{art['acquisition_id']}.json").is_file()

    # Same run_id again: verified reuse, exit 0.
    again = cli("download", "--api", "elevation", "--region", "13",
                "--source", "fixture-dem-png-tokyo", "--fixture", str(FIXTURE),
                "--data-root", str(tmp_path), "--resume-run-id", result["run_id"])
    assert again.returncode == 0
    assert json.loads(again.stdout)["artifacts"] == result["artifacts"]


def test_cli_production_blocked(tmp_path: Path) -> None:
    proc = cli("download", "--api", "elevation", "--region", "13",
               "--source", "gsi-dem10b-candidate", "--data-root", str(tmp_path))
    assert proc.returncode == 3
    out = json.loads(proc.stdout)
    assert out["status"] == "BLOCKED" and out["error_code"] == "APPROVAL_REQUIRED"
    assert list(tmp_path.iterdir()) == []


def test_cli_rejects_production_or_repo_data_root_for_fixture(tmp_path: Path) -> None:
    for root in ("/data", "/data/elevation", str(REPO / "tmp-out")):
        proc = cli("download", "--api", "elevation", "--region", "13",
                   "--source", "fixture-dem-png-tokyo", "--fixture", str(FIXTURE),
                   "--data-root", root)
        assert proc.returncode == 2, root
        assert json.loads(proc.stdout)["error_code"] == "INVALID_INPUT"
    assert not (REPO / "tmp-out").exists()


def test_cli_invalid_region_and_usage(tmp_path: Path) -> None:
    proc = cli("download", "--api", "elevation", "--region", "99",
               "--source", "fixture-dem-png-tokyo", "--fixture", str(FIXTURE),
               "--data-root", str(tmp_path))
    assert proc.returncode == 2
    assert json.loads(proc.stdout)["error_code"] == "INVALID_INPUT"
    usage = cli("download", "--api", "elevation")
    assert usage.returncode == 2 and usage.stdout == ""


def test_cli_untargeted_region_blocked(tmp_path: Path) -> None:
    proc = cli("download", "--api", "elevation", "--region", "01",
               "--source", "fixture-dem-png-tokyo", "--fixture", str(FIXTURE),
               "--data-root", str(tmp_path))
    assert proc.returncode == 3
    assert json.loads(proc.stdout)["error_code"] == "TARGET_UNCONFIGURED"
