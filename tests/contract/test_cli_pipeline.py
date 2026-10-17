"""CLI integration tests: ``hererisk-pipeline pipeline`` (fixture Download -> Normalize -> Validate).

Reuses the guarded child-process helper of test_cli (socket/DNS denied in the child).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import fixture_builder as fb
from hererisk.cli import pipeline_summary
from hererisk.common.result import ModuleResult, Status
from test_cli import FIXTURE, REPO, cli, fixture_root
from test_normalize_stage import _undecodable_png

TOKYO = ("13", "fixture-dem-png-tokyo")
OSAKA = ("27", "fixture-dem-png-osaka")


def run_pipeline(data_root: Path, target=TOKYO, fixture: Path = FIXTURE, *extra: str):
    region, source = target
    return cli("pipeline", "--api", "elevation", "--region", region, "--source", source,
               "--fixture", str(fixture), "--data-root", str(data_root), *extra)


def parse(proc) -> dict:
    lines = proc.stdout.splitlines()
    assert len(lines) == 1, proc.stdout  # result only; logs go to stderr
    return json.loads(lines[0])


def stages(doc) -> list[tuple[str, str, str | None]]:
    return [(r["module"], r["status"], r["error_code"]) for r in doc["results"]]


def tree_hashes(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


ALL_SUCCESS = [("download", "SUCCESS", None), ("normalize", "SUCCESS", None),
               ("validate", "SUCCESS", None)]


# -- success ---------------------------------------------------------------------------------
def test_two_tiles_pipeline_success(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    fixture_before = tree_hashes(FIXTURE)
    proc = run_pipeline(root)
    assert proc.returncode == 0, proc.stderr
    doc = parse(proc)
    assert set(doc) == {"run_id", "status", "error_code", "results"}
    assert doc["status"] == "SUCCESS" and doc["error_code"] is None
    assert stages(doc) == ALL_SUCCESS
    assert all(r["run_id"] == doc["run_id"] for r in doc["results"])
    dl, norm, val = doc["results"]
    assert len(dl["artifacts"]) == len(norm["artifacts"]) == len(val["artifacts"]) == 2
    assert [a["acquisition_id"] for a in dl["artifacts"]] == \
        [a["acquisition_id"] for a in val["artifacts"]]
    assert [a["sha256"] for a in norm["artifacts"]] == [a["sha256"] for a in val["artifacts"]]
    # Each stage result has exactly the ModuleResult keys.
    assert all(set(r) == {"run_id", "module", "status", "artifacts", "error_code", "message"}
               for r in doc["results"])
    record = json.loads((root / f"elevation/records/validations/{doc['run_id']}.json").read_bytes())
    assert record["status"] == "SUCCESS" and len(record["validation"]["tiles"]) == 2
    logs = [json.loads(line) for line in proc.stderr.splitlines()]
    assert logs and all(e["run_id"] == doc["run_id"] for e in logs)
    assert {e["module"] for e in logs} >= {"download", "normalize", "validate"}
    assert tree_hashes(FIXTURE) == fixture_before


def test_one_tile_pipeline_success(tmp_path: Path) -> None:
    proc = run_pipeline(fixture_root(tmp_path), OSAKA)
    assert proc.returncode == 0
    doc = parse(proc)
    assert stages(doc) == ALL_SUCCESS and len(doc["results"][2]["artifacts"]) == 1


def test_resume_returns_same_results(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    first = parse(run_pipeline(root))
    before = tree_hashes(root)
    proc = run_pipeline(root, TOKYO, FIXTURE, "--resume-run-id", first["run_id"])
    assert proc.returncode == 0 and parse(proc) == first
    assert tree_hashes(root) == before


def test_writes_confined_to_managed_areas(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    repo_fixture = tree_hashes(FIXTURE)
    doc = parse(run_pipeline(root))
    assert doc["status"] == "SUCCESS"
    allowed = ("elevation/work/download", "elevation/work/acquisitions", "elevation/work/locks",
               "elevation/work/normalized", "elevation/records/")
    files = set(tree_hashes(root)) - {".hererisk-fixture-data-root"}
    assert files and all(f.startswith(allowed) for f in files)
    assert not (root / "elevation/dl").exists() and not (root / "elevation/rel").exists()
    assert list(tmp_path.iterdir()) == [root]
    assert tree_hashes(FIXTURE) == repo_fixture
    assert not (REPO / "elevation").exists()


# -- not successful --------------------------------------------------------------------------
def test_unauthorized_stage_blocks_before_writing(tmp_path: Path) -> None:
    fixture = fb.build_tree(tmp_path / "fx")
    (fixture / "authorization/validate.json").unlink()
    root = fixture_root(tmp_path)
    proc = run_pipeline(root, TOKYO, fixture)
    assert proc.returncode == 3
    doc = parse(proc)
    assert doc["status"] == "BLOCKED" and doc["error_code"] == "APPROVAL_REQUIRED"
    assert stages(doc) == [("validate", "BLOCKED", "APPROVAL_REQUIRED")]
    assert set(tree_hashes(root)) == {".hererisk-fixture-data-root"}


def test_mid_pipeline_failure_is_not_success(tmp_path: Path) -> None:
    fixture = fb.build_tree(tmp_path / "fx")
    (fixture / "tiles/dem_png/14/14551/6450.png").write_bytes(_undecodable_png())
    proc = run_pipeline(fixture_root(tmp_path), TOKYO, fixture)
    assert proc.returncode == 11
    doc = parse(proc)
    assert doc["status"] == "FAILED" and doc["error_code"] == "PNG_INVALID"
    assert stages(doc) == [("download", "SUCCESS", None), ("normalize", "FAILED", "PNG_INVALID")]


def test_download_failure_stops_pipeline(tmp_path: Path) -> None:
    fixture = fb.build_tree(tmp_path / "fx")
    (fixture / "tiles/dem_png/14/14551/6450.png").unlink()
    proc = run_pipeline(fixture_root(tmp_path), TOKYO, fixture)
    assert proc.returncode == 10
    assert stages(parse(proc)) == [("download", "FAILED", "HTTP_404")]


def test_invalid_input_and_targets(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    cases = [
        (("99", TOKYO[1]), 2, "INVALID_INPUT"),
        (("01", TOKYO[1]), 3, "TARGET_UNCONFIGURED"),
        (("13", "gsi-dem10b-candidate"), 2, "INVALID_INPUT"),  # not in the fixture definition
    ]
    for target, code, error in cases:
        proc = run_pipeline(root, target)
        assert proc.returncode == code, target
        doc = parse(proc)
        assert doc["error_code"] == error and doc["status"] != "SUCCESS"
        assert len(doc["results"]) == 1


def test_uninitialised_or_protected_root_rejected(tmp_path: Path) -> None:
    for root in (tmp_path, Path("/data"), REPO / "tmp-out"):
        proc = run_pipeline(root)
        assert proc.returncode == 2, root
        assert parse(proc)["error_code"] == "INVALID_INPUT"
    assert list(tmp_path.iterdir()) == [] and not (REPO / "tmp-out").exists()


def test_argument_errors_use_fixed_message(tmp_path: Path) -> None:
    for args in (
        ["pipeline", "--api", "elevation", "--region", "13", "--source", "x",
         "--data-root", str(tmp_path)],  # --fixture missing: no production pipeline
        ["pipeline", "--api", "elevation", "--region", "13", "--source", "x",
         "--data-root", str(tmp_path), "--fixture", str(FIXTURE), "--token=AUDIT_CANARY"],
    ):
        proc = cli(*args)
        assert proc.returncode == 2 and proc.stdout == ""
        assert proc.stderr == "hererisk-pipeline: invalid arguments (see --help)\n"
    assert list(tmp_path.iterdir()) == []


def test_download_command_unchanged(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    proc = cli("download", "--api", "elevation", "--region", "13", "--source", TOKYO[1],
               "--fixture", str(FIXTURE), "--data-root", str(root))
    assert proc.returncode == 0
    result = json.loads(proc.stdout)
    assert result["module"] == "download" and result["status"] == "SUCCESS"
    assert not (root / "elevation/work/normalized").exists()
    assert not (root / "elevation/records/validations").exists()


# -- summary rule (unit) ----------------------------------------------------------------------
def test_summary_never_reports_partial_success() -> None:
    run = "11111111-1111-4111-8111-111111111111"
    ok = lambda m: ModuleResult(run, m, Status.SUCCESS, None, "ok")  # noqa: E731
    doc, code = pipeline_summary([ok("download"), ok("normalize")])
    assert doc["status"] == "FAILED" and doc["error_code"] == "INTERNAL_ERROR" and code == 14
    doc, code = pipeline_summary([ok("download"), ok("normalize"), ok("validate")])
    assert (doc["status"], doc["error_code"], code) == ("SUCCESS", None, 0)
    failed = ModuleResult.error(run, "validate", "VALIDATION_FAILED")
    doc, code = pipeline_summary([ok("download"), ok("normalize"), failed])
    assert (doc["status"], doc["error_code"], code) == ("FAILED", "VALIDATION_FAILED", 11)
    doc, code = pipeline_summary([ok("download"), ok("validate"), ok("normalize")])
    assert doc["status"] == "FAILED" and code == 14  # wrong order is not success
