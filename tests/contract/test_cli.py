"""Contract tests: CLI process (stdout JSON only, stderr logs, exit codes).

Runs the CLI in a child process with its own socket/DNS guard installed before
the CLI is imported, because the parent's monkeypatch does not reach children.
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

_GUARDED_MAIN = """
import socket, sys
def _deny(*a, **k):
    sys.stderr.write("NETWORK_ATTEMPT\\n"); raise OSError("network forbidden")
socket.socket.connect = _deny; socket.socket.connect_ex = _deny
socket.create_connection = _deny; socket.getaddrinfo = _deny
from hererisk.cli import main
raise SystemExit(main(sys.argv[1:]))
"""


def cli(*args: str, cwd: Path = REPO) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    proc = subprocess.run(
        [sys.executable, "-c", _GUARDED_MAIN, *args],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=60, check=False,
    )
    assert "NETWORK_ATTEMPT" not in proc.stderr
    return proc


def fixture_root(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    assert cli("init-fixture-root", "--data-root", str(root)).returncode == 0
    return root


def download(data_root: Path, *extra: str, region: str = "13",
             source: str = "fixture-dem-png-tokyo", fixture: Path | None = FIXTURE):
    args = ["download", "--api", "elevation", "--region", region, "--source", source,
            "--data-root", str(data_root), *extra]
    if fixture is not None:
        args += ["--fixture", str(fixture)]
    return cli(*args)


def test_committed_fixture_tree_is_current(tmp_path: Path) -> None:
    rebuilt = fb.build_tree(tmp_path / "t")
    for path in rebuilt.rglob("*"):
        if path.is_file():
            assert (FIXTURE / path.relative_to(rebuilt)).read_bytes() == path.read_bytes(), path


def test_cli_fixture_success(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    proc = download(root)
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert len(lines) == 1
    result = json.loads(lines[0])
    assert result["status"] == "SUCCESS" and len(result["artifacts"]) == 2
    logs = [json.loads(line) for line in proc.stderr.splitlines()]
    assert logs and all(e["run_id"] == result["run_id"] for e in logs)
    for art in result["artifacts"]:
        assert (root / "elevation/records" / art["record_ref"]).is_file()
        assert (root / f"elevation/records/commits/{art['acquisition_id']}.json").is_file()

    # Same run_id again: verified reuse, exit 0.
    again = download(root, "--resume-run-id", result["run_id"])
    assert again.returncode == 0
    assert json.loads(again.stdout)["artifacts"] == result["artifacts"]


def test_cli_production_blocked(tmp_path: Path) -> None:
    proc = download(tmp_path, source="gsi-dem10b-candidate", fixture=None)
    assert proc.returncode == 3
    out = json.loads(proc.stdout)
    assert out["status"] == "BLOCKED" and out["error_code"] == "APPROVAL_REQUIRED"
    assert list(tmp_path.iterdir()) == []


def test_cli_fixture_requires_initialised_root(tmp_path: Path) -> None:
    proc = download(tmp_path)
    assert proc.returncode == 2
    assert json.loads(proc.stdout)["error_code"] == "INVALID_INPUT"
    assert list(tmp_path.iterdir()) == []


def test_cli_rejects_production_or_repo_data_root_for_fixture(tmp_path: Path) -> None:
    for root in ("/data", "/data/elevation", str(REPO / "tmp-out"), str(REPO)):
        proc = download(Path(root))
        assert proc.returncode == 2, root
        assert json.loads(proc.stdout)["error_code"] == "INVALID_INPUT"
    assert not (REPO / "tmp-out").exists() and not (REPO / "elevation").exists()


def test_cli_init_fixture_root_refusals(tmp_path: Path) -> None:
    non_empty = tmp_path / "busy"
    non_empty.mkdir()
    (non_empty / "keep").write_bytes(b"x")
    for root in (str(non_empty), str(tmp_path / "missing"), "/data", str(REPO / "tests")):
        proc = cli("init-fixture-root", "--data-root", root)
        assert proc.returncode == 2, root
        assert root not in proc.stderr
    assert (non_empty / "keep").read_bytes() == b"x" and len(list(non_empty.iterdir())) == 1


def test_cli_invalid_region_and_usage(tmp_path: Path) -> None:
    proc = download(fixture_root(tmp_path), region="99")
    assert proc.returncode == 2
    assert json.loads(proc.stdout)["error_code"] == "INVALID_INPUT"
    usage = cli("download", "--api", "elevation")
    assert usage.returncode == 2 and usage.stdout == ""


def test_cli_syntax_errors_do_not_echo_values(tmp_path: Path) -> None:
    cases = [
        ["download", "--api", "elevation", "--region", "13", "--source", "x",
         "--data-root", "/private/SECRET_PATH", "--secret=AUDIT_CANARY"],
        ["download", "--api", "elevation", "--region", "13", "--source", "x",
         "--data-root", "/tmp", "AUDIT_CANARY_POSITIONAL"],
        ["AUDIT_CANARY_COMMAND"],
        ["download", "--region"],
    ]
    for args in cases:
        proc = cli(*args)
        assert proc.returncode == 2 and proc.stdout == ""
        assert "AUDIT_CANARY" not in proc.stderr and "SECRET_PATH" not in proc.stderr
        assert proc.stderr == "hererisk-pipeline: invalid arguments (see --help)\n"


def test_cli_untargeted_region_blocked(tmp_path: Path) -> None:
    proc = download(fixture_root(tmp_path), region="01")
    assert proc.returncode == 3
    assert json.loads(proc.stdout)["error_code"] == "TARGET_UNCONFIGURED"
