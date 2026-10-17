"""Contract tests: Phase 1-H OWNER helpers for the private experiment.

All values are TEST-ONLY (approver "owner-test", references "test case ...");
GSI is a fake connection, nothing touches the network or the repository.
"""

from __future__ import annotations

import json
import os

import pytest

from e2e_support import REPO, SOURCE, GsiFake, centre, png_with, post
from hererisk.common.api_auth import BearerAuth
from hererisk.common.authorization import ExecutionContext, ProductionAuthorizer
from hererisk.common.config import ConfigurationManager
from hererisk.common.logging import ListSink, StructuredLogger
from hererisk.common.orchestrator import DownloadRequest, Orchestrator
from hererisk.common.storage import PRIVATE_ROOT_MARKER
from hererisk.elevation import private_ops as po
from hererisk.elevation.api.handler import ElevationApi, Settings
from hererisk.elevation.api.published import PublishedSet
from hererisk.elevation.download.download import ElevationDownload
from hererisk.elevation.download.gsi_transport import GsiHttpTransport
from hererisk.elevation.normalize.stage import NormalizeStage
from hererisk.elevation.publish.stage import PublishStage
from hererisk.elevation.validate.stage import ValidateStage

PRIVATE = ExecutionContext.PRIVATE_EXPERIMENT
TILE = (14552, 6451)
APPROVAL = "apr-private-elevation-13-0001"
BODY = png_with({(10, 20): (0, 4, 210)})
DEFINITION = dict(approval_id=APPROVAL, tiles=[TILE],
                  attribution_text="test case attribution (not a decided text)",
                  vertical_reference="test case vertical reference", review_ref="test case review",
                  revision="private-test-1")
OWNER = dict(approved_by="owner-test", basis_ref="test case basis", valid_days=7)


@pytest.fixture
def base(tmp_path):
    b = po.private_base(tmp_path / "private-base", REPO)
    po.init_base(b, REPO)
    po.write_definition(b, REPO, **DEFINITION)
    return b


def register(base, operations, **extra):
    return po.register_approval(base, REPO, approval_id=APPROVAL, confirm=APPROVAL,
                                operations=operations, regions=["13"], **OWNER, **extra)


def pipeline(base, *, publish=False, resume=None, gsi=None):
    gsi = gsi or GsiFake({TILE: BODY})
    stages = (NormalizeStage(), ValidateStage()) + ((PublishStage(),) if publish else ())
    orch = Orchestrator(
        config_manager=ConfigurationManager(base.config, REPO),
        authorizer=ProductionAuthorizer(base.approvals, protected_roots=(REPO,), context=PRIVATE),
        modules={"elevation": ElevationDownload(GsiHttpTransport(connection_factory=gsi,
                                                                  context=PRIVATE))},
        data_root=base.data, logger=StructuredLogger(ListSink()), stages={"elevation": stages})
    results = orch.run_pipeline(DownloadRequest("elevation", ("13",), SOURCE, resume_run_id=resume),
                                context=PRIVATE)
    return [(r.module, r.status.value, r.error_code) for r in results], results, gsi


def files(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


# -- layout and definition ----------------------------------------------------------------------
def test_init_creates_private_layout(tmp_path) -> None:
    b = po.private_base(tmp_path / "pb", REPO)
    po.init_base(b, REPO)
    for d in (b.root, b.approvals, b.approvals / "approvals", b.root / "secrets", b.root / "audit"):
        assert os.stat(d).st_mode & 0o077 == 0
    assert os.stat(b.token).st_mode & 0o777 == 0o600
    assert os.stat(b.auth_header).st_mode & 0o777 == 0o600
    token = b.token.read_text().strip()
    assert b.auth_header.read_text() == f"Authorization: Bearer {token}\n"
    assert (b.data / PRIVATE_ROOT_MARKER).is_file()
    assert token not in b.audit.read_text()
    with pytest.raises(po.PrivateOpsError):
        po.init_base(b, REPO)  # never twice


@pytest.mark.parametrize("bad", ["relative", "inside-repo", "symlink"])
def test_private_base_location_rules(tmp_path, bad) -> None:
    from pathlib import Path

    if bad == "relative":
        path = Path("relative/base")
    elif bad == "inside-repo":
        path = REPO / "private-base"
    else:
        (tmp_path / "real").mkdir()
        (tmp_path / "link").symlink_to(tmp_path / "real")
        path = tmp_path / "link" / "base"
    with pytest.raises(po.PrivateOpsError):
        po.private_base(path, REPO)


def test_definition_is_outside_git_and_committed_one_untouched(base) -> None:
    committed = (REPO / "api/elevation/conf/sources.json").read_bytes()
    snapshot = po.load_definition(base, REPO)
    src = snapshot.data["sources"][SOURCE]
    assert src["approval_ref"] == APPROVAL and [dict(t) for t in src["acquisition"]["tiles"]] == [
        {"x": TILE[0], "y": TILE[1]}]
    assert src["pipeline"] == {"id": "elevation-download", "version": "0.1"}
    assert (REPO / "api/elevation/conf/sources.json").read_bytes() == committed
    assert json.loads(committed)["sources"][SOURCE]["approval_ref"] is None
    with pytest.raises(po.PrivateOpsError):
        po.write_definition(base, REPO, **DEFINITION)  # exists: needs --replace


@pytest.mark.parametrize("change", [{"approval_id": "apr-public-0001"},
                                    {"attribution_text": "<出典>"}, {"review_ref": " "},
                                    {"tiles": []}, {"tiles": [TILE, TILE]}])
def test_definition_refuses_placeholders(tmp_path, change) -> None:
    b = po.private_base(tmp_path / "pb", REPO)
    po.init_base(b, REPO)
    with pytest.raises(po.PrivateOpsError):
        po.write_definition(b, REPO, **{**DEFINITION, **change})
    assert not b.sources.exists()


# -- approvals are explicit OWNER acts ------------------------------------------------------------
def test_nothing_runs_before_registration(base) -> None:
    outcome, _, gsi = pipeline(base)
    assert outcome == [("download", "BLOCKED", "APPROVAL_REQUIRED")]
    assert gsi.requested_paths == [] and files(base.data) == [PRIVATE_ROOT_MARKER]


@pytest.mark.parametrize("change", [
    {"confirm": "apr-private-other-0001"},
    {"approved_by": "<OWNER>"}, {"approved_by": "test-only"}, {"basis_ref": ""},
    {"valid_days": 0}, {"valid_days": 31}, {"regions": ["14"]}, {"regions": []},
    {"license_text": "x"},  # publication values without publish
])
def test_register_refusals(base, change) -> None:
    args = dict(approval_id=APPROVAL, confirm=APPROVAL, operations=["download"], regions=["13"],
                **OWNER)
    args.update(change)
    with pytest.raises(po.PrivateOpsError):
        po.register_approval(base, REPO, **args)
    assert not base.record(APPROVAL).exists()


def test_publish_cannot_be_approved_before_a_reviewed_validate(base) -> None:
    ops = ["download", "normalize", "validate", "publish"]
    terms = dict(license_text="test case licence", attribution_url="https://example.invalid/t",
                 usage_review_ref="test case usage review")
    with pytest.raises(po.PrivateOpsError):
        register(base, ops, **terms)  # no reviewed run: no one-shot acquire+publish approval
    with pytest.raises(po.PrivateOpsError):
        register(base, ops, **terms, reviewed_run_id="00000000-0000-4000-8000-000000000000")
    assert not base.record(APPROVAL).exists()


def test_full_private_flow(base) -> None:
    # 2-3: approve acquisition only, then run
    record = register(base, ["download", "normalize", "validate"])
    assert record["region_codes"] == ["13"] and record["tiles"] == [
        {"z": 14, "x": TILE[0], "y": TILE[1]}]
    assert record["acquisition"]["max_tiles_per_run"] == 1
    assert record["acquisition"]["allowed_host"] == "cyberjapandata.gsi.go.jp"
    assert os.stat(base.record(APPROVAL)).st_mode & 0o777 == 0o600
    outcome, results, gsi = pipeline(base, publish=True)
    assert outcome[-1] == ("publish", "BLOCKED", "APPROVAL_REQUIRED")  # publish not approved
    assert gsi.requested_paths == []
    outcome, results, gsi = pipeline(base)
    assert [o[1] for o in outcome] == ["SUCCESS"] * 3
    assert gsi.requested_paths == [f"/xyz/dem_png/14/{TILE[0]}/{TILE[1]}.png"]
    run_id = results[0].run_id
    assert not (base.data / "elevation/rel").exists()
    # 5-6: OWNER approves publish for the reviewed run, then publish (no new download)
    terms = dict(license_text="test case licence", attribution_url="https://example.invalid/t",
                 usage_review_ref="test case usage review")
    with pytest.raises(po.PrivateOpsError):
        register(base, ["download", "normalize", "validate", "publish"], **terms,
                 reviewed_run_id=run_id)  # exists: must be an explicit --replace
    register(base, ["download", "normalize", "validate", "publish"], **terms,
             reviewed_run_id=run_id, replace=True)
    outcome, _, gsi2 = pipeline(base, publish=True, resume=run_id)
    assert [o[1] for o in outcome] == ["SUCCESS"] * 4 and gsi2.requested_paths == []
    # 7: Bearer token API on the private data
    api = ElevationApi(PublishedSet.load(base.data, private_experiment=True), Settings(1024, 3000),
                       StructuredLogger(ListSink()), auth=BearerAuth.from_file(base.token))
    header = base.auth_header.read_text().strip().split(": ", 1)
    lat, lon = centre(*TILE, 10, 20)
    ok = post(api, {"lat": lat, "lon": lon},
              headers={"Content-Type": "application/json", header[0]: header[1]})
    assert ok.status == 200 and ok.json()["result"] == {"elevation_m": 12.34}
    assert post(api, {"lat": lat, "lon": lon}).status == 401
    # status and audit carry no secrets
    summary = po.status(base, REPO)
    assert summary["registry"] == {"13": f"rev-{run_id}"}
    assert summary["approvals"][0]["in_force"] and summary["approvals"][0]["matches_definition"]
    text = json.dumps(summary) + base.audit.read_text()
    token = base.token.read_text().strip()
    assert token not in text and repr(lat)[:6] not in text
    # 8: revoke -> everything blocked again
    po.revoke_approval(base, approval_id=APPROVAL, confirm=APPROVAL, reason_ref="test case end")
    outcome, _, gsi3 = pipeline(base)
    assert outcome == [("download", "BLOCKED", "APPROVAL_REQUIRED")] and gsi3.requested_paths == []
    assert po.status(base, REPO)["approvals"][0]["revoked"] is True
    with pytest.raises(po.PrivateOpsError):
        po.revoke_approval(base, approval_id=APPROVAL, confirm=APPROVAL, reason_ref="again")


def test_definition_change_invalidates_registered_approval(base) -> None:
    register(base, ["download", "normalize", "validate"])
    po.write_definition(base, REPO, **{**DEFINITION, "revision": "private-test-2"}, replace=True)
    outcome, _, gsi = pipeline(base)
    assert outcome == [("download", "BLOCKED", "APPROVAL_REQUIRED")] and gsi.requested_paths == []
    assert po.status(base, REPO)["approvals"][0]["matches_definition"] is False


def test_revoke_requires_confirmation(base) -> None:
    register(base, ["download"])
    with pytest.raises(po.PrivateOpsError):
        po.revoke_approval(base, approval_id=APPROVAL, confirm="x", reason_ref="r")


# -- CLI ----------------------------------------------------------------------------------------
def test_cli_private_commands(tmp_path) -> None:
    from test_cli import cli

    b = tmp_path / "pb"
    assert cli("private-init", "--base", str(b)).returncode == 0
    token = (b / "secrets/api-token").read_text().strip()
    d = cli("private-definition", "--base", str(b), "--approval-id", APPROVAL,
            "--tile", f"{TILE[0]},{TILE[1]}", "--attribution-text", "test case attribution",
            "--vertical-reference", "test case vref", "--review-ref", "test case review")
    sha = json.loads(d.stdout)["definition_raw_sha256"]
    check = cli("approval-check", "--api", "elevation", "--region", "13", "--source", SOURCE,
                "--private-base", str(b))
    doc = json.loads(check.stdout)
    assert check.returncode == 3 and doc["context"] == "private_experiment"
    assert doc["definition_raw_sha256"] == sha
    reg = cli("approval-register", "--base", str(b), "--approval-id", APPROVAL,
              "--confirm", APPROVAL, "--operations", "download,normalize,validate",
              "--region", "13", "--approved-by", "owner-test", "--basis-ref", "test case basis",
              "--valid-days", "3")
    assert reg.returncode == 0, reg.stdout
    check = cli("approval-check", "--api", "elevation", "--region", "13", "--source", SOURCE,
                "--private-base", str(b), "--publish")
    decisions = {e["operation"]: e["decision"] for e in json.loads(check.stdout)["operations"]}
    assert decisions == {"download": "GRANTED", "normalize": "GRANTED", "validate": "GRANTED",
                         "publish": "BLOCKED"}
    status = cli("private-status", "--base", str(b))
    assert status.returncode == 0 and token not in status.stdout
    for proc in (d, check, reg, status):
        assert token not in proc.stdout + proc.stderr
    # misuse of --private-base
    for extra in (["--production"], ["--private-experiment", "--data-root", str(tmp_path)],
                  ["--private-experiment", "--approval-root", str(b / "approvals")]):
        bad = cli("pipeline", "--api", "elevation", "--region", "13", "--source", SOURCE,
                  "--private-base", str(b), *extra)
        assert bad.returncode == 2 and json.loads(bad.stdout)["error_code"] == "INVALID_INPUT"
    assert cli("private-init", "--base", str(REPO / "x")).returncode == 2
    assert not (REPO / "x").exists()


def test_cli_private_pipeline_without_network_flag_never_fetches(tmp_path) -> None:
    from test_cli import cli

    b = tmp_path / "pb"
    cli("private-init", "--base", str(b))
    cli("private-definition", "--base", str(b), "--approval-id", APPROVAL,
        "--tile", f"{TILE[0]},{TILE[1]}", "--attribution-text", "test case attribution",
        "--vertical-reference", "test case vref", "--review-ref", "test case review")
    proc = cli("pipeline", "--api", "elevation", "--region", "13", "--source", SOURCE,
               "--private-experiment", "--private-base", str(b))
    assert proc.returncode == 3 and json.loads(proc.stdout)["error_code"] == "APPROVAL_REQUIRED"


def test_server_private_base_flags() -> None:
    from hererisk.elevation.api import server

    assert server.main(["--private-base", "/nonexistent-base"]) == 2  # needs --private-experiment
    assert server.main(["--private-base", "/x", "--private-experiment",
                        "--data-root", "/y"]) == 2
    assert server.main(["--private-base", "/nonexistent-base", "--private-experiment",
                        "--port", "0"]) == 3


def _reviewed_run(base):
    register(base, ["download", "normalize", "validate"])
    outcome, results, _ = pipeline(base)
    assert [o[1] for o in outcome] == ["SUCCESS"] * 3
    return results[0].run_id


@pytest.mark.parametrize("field,value", [("license_text", "<ライセンス>"),
                                         ("attribution_url", "<URL>"),
                                         ("usage_review_ref", "<確認記録>")])
def test_publish_registration_refuses_placeholders(base, field, value) -> None:
    run_id = _reviewed_run(base)
    before = base.record(APPROVAL).read_bytes()
    terms = dict(license_text="test case licence", attribution_url="https://example.invalid/t",
                 usage_review_ref="test case usage review", reviewed_run_id=run_id)
    terms[field] = value
    with pytest.raises(po.PrivateOpsError):
        register(base, ["download", "normalize", "validate", "publish"], replace=True, **terms)
    assert base.record(APPROVAL).read_bytes() == before


@pytest.mark.parametrize("change", [{"status": "FAILED"},
                                    {"execution_context": "production"},
                                    {"authorization_ref": "apr-private-someone-else"}])
def test_reviewed_run_must_be_a_private_success_of_this_approval(base, change) -> None:
    run_id = "11111111-1111-4111-8111-111111111111"
    validations = base.data / "elevation/records/validations"
    validations.mkdir(parents=True)
    doc = {"status": "SUCCESS", "execution_context": "private_experiment",
           "authorization_ref": APPROVAL, "run_id": run_id}
    doc.update(change)
    (validations / f"{run_id}.json").write_text(json.dumps(doc))
    register(base, ["download", "normalize", "validate"])
    with pytest.raises(po.PrivateOpsError):
        register(base, ["download", "normalize", "validate", "publish"], replace=True,
                 license_text="test case licence", attribution_url="https://example.invalid/t",
                 usage_review_ref="test case usage review", reviewed_run_id=run_id)
