"""Contract tests: Phase 1-F ProductionAuthorizer and the approval store.

These tests use the REAL ProductionAuthorizer. Its input is a TEST-ONLY
approval store written to a temporary directory outside the repository
(``apr-test-only-*`` records, ``test-only`` approver / basis), over a test-only
copy of the Source Definition and a fake GSI. None of this is a production
approval; the committed Source Definition stays unapproved.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest

from e2e_support import (
    REPO,
    SOURCE,
    TEST_APPROVAL_ID,
    TEST_ATTRIBUTION,
    TEST_TERMS,
    TOKYO_TILES,
    World,
    approval_record,
    centre,
    png_with,
    post,
    write_store,
)
from hererisk.common.approval_store import record_digest
from hererisk.common.authorization import ProductionAuthorizer
from hererisk.common.config import ConfigurationManager
from hererisk.common.storage import FIXTURE_ROOT_MARKER

A, B = TOKYO_TILES
BODIES = {A: png_with({(10, 20): (0, 4, 210), (11, 20): (0, 0, 0), (12, 20): (255, 255, 136),
                       (13, 20): (128, 0, 0)}),
          B: png_with({}, default=(0, 1, 0))}
OPS = ("download", "normalize", "validate", "publish")


def modules(results):
    return [(r.module, r.status.value, r.error_code) for r in results]


def files(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


@pytest.fixture
def world(tmp_path):
    return World(tmp_path, BODIES, approval_ref=TEST_APPROVAL_ID)


def definition(world):
    return ConfigurationManager(world.repo, REPO).load("api", "elevation", "sources")


def authorize(world, operation, regions=("13",), source=SOURCE):
    return world.authorizer.authorize(api_id="elevation", operation=operation, source_ref=source,
                                      region_codes=regions, definition=definition(world))


def assert_blocked_before_anything(world, results, module="download"):
    assert modules(results) == [(module, "BLOCKED", "APPROVAL_REQUIRED")]
    assert world.gsi.requested_paths == [] and files(world.data_root) == []


# -- grants ---------------------------------------------------------------------------------------
def test_explicit_record_grants_each_operation(world) -> None:
    world.use_store()
    for operation in OPS:
        grant = authorize(world, operation)
        assert grant.authorization_ref == TEST_APPROVAL_ID and grant.operation == operation
        assert grant.context.value == "production"
    assert dict(authorize(world, "download").policy) == {
        "policy_id": TEST_APPROVAL_ID, "version": "test-only-1", "max_tile_bytes": 1048576,
        "max_tiles_per_request": 16, "max_pending_acquisitions": 8}
    assert dict(authorize(world, "publish").policy) == TEST_TERMS
    assert dict(authorize(world, "normalize").policy) == {}


def test_end_to_end_with_real_authorizer(world) -> None:
    """mock GSI -> Download -> Normalize -> Validate -> Publish -> Registry -> API."""
    api_before = world.api()
    assert post(api_before, dict(zip(("lat", "lon"), centre(*A, 10, 20)))).json()["error"][
        "code"] == "no_coverage"  # nothing published yet
    world.use_store()
    results = world.run()
    assert [m[:2] for m in modules(results)] == [(m, "SUCCESS") for m in OPS]
    run_id = results[0].run_id
    api = world.data_root / "elevation"
    acq = json.loads((api / "records" / results[0].artifacts[0].record_ref).read_bytes())
    assert acq["usage_snapshot"]["approval_ref"] == TEST_APPROVAL_ID
    for kind in ("normalizations", "validations", "publications"):
        rec = json.loads((api / f"records/{kind}/{run_id}.json").read_bytes())
        assert rec["authorization_ref"] == TEST_APPROVAL_ID
        assert rec["execution_context"] == "production"
    sink_api = world.api()
    expected = {(A, 10): 12.34, (A, 11): 0.0, (A, 12): -1.2, (B, 3): 2.56}
    for (tile, px), value in expected.items():
        doc = post(sink_api, dict(zip(("lat", "lon"), centre(*tile, px, 20)))).json()
        assert doc["status"] == "success" and doc["result"] == {"elevation_m": value}
        assert doc["dataset"]["publication_version"] == f"pub-{run_id}"
        assert doc["dataset"]["attribution"] == {"text": TEST_ATTRIBUTION,
                                                 "license": TEST_TERMS["license"],
                                                 "url": TEST_TERMS["attribution_url"]}
    nodata = post(sink_api, dict(zip(("lat", "lon"), centre(*A, 13, 20)))).json()
    assert nodata["error"]["code"] == "elevation_nodata"
    assert post(sink_api, {"lat": 43.06, "lon": 141.35}).json()["error"]["code"] == "no_coverage"


# -- denials (all before any network access or write) --------------------------------------------
def test_no_store_configured_blocks(world) -> None:
    world.authorizer = ProductionAuthorizer()
    world.orchestrator._authorizer = world.authorizer
    assert_blocked_before_anything(world, world.run())


@pytest.mark.parametrize("missing", ["root", "revocations", "approvals"])
def test_incomplete_store_blocks(world, missing) -> None:
    store = world.use_store()
    if missing == "root":
        world.orchestrator._authorizer = ProductionAuthorizer(store / "absent",
                                                              protected_roots=(REPO,))
    elif missing == "revocations":
        (store / "revocations.json").unlink()
    else:
        for p in (store / "approvals").iterdir():
            p.unlink()
        (store / "approvals").rmdir()
    assert_blocked_before_anything(world, world.run())


@pytest.mark.parametrize("operation", OPS)
def test_unlisted_operation_blocks_whole_run(world, operation) -> None:
    ops = tuple(o for o in OPS if o != operation)
    world.use_store([approval_record(world.definition_sha256, operations=ops)])
    assert_blocked_before_anything(world, world.run(), module=operation)


@pytest.mark.parametrize("change,kwargs", [
    ("region", {"regions": ("14",)}),
    ("tiles", {"tiles": [A]}),
    ("source", {"source_ref": "gsi-other-source"}),
    ("definition", {"definition": {"revision": "test-only-1", "raw_sha256": "0" * 64}}),
], ids=lambda v: v if isinstance(v, str) else "")
def test_scope_mismatch_blocks(world, change, kwargs) -> None:
    world.use_store([approval_record(world.definition_sha256, **kwargs)])
    assert_blocked_before_anything(world, world.run())


def test_requested_regions_are_never_widened(world) -> None:
    world.use_store()
    with pytest.raises(Exception, match="APPROVAL_REQUIRED"):
        authorize(world, "download", regions=("13", "14"))


def test_tile_count_and_host_limits(world) -> None:
    rec = approval_record(world.definition_sha256)
    rec["acquisition"] = dict(rec["acquisition"], max_tiles_per_run=1)
    rec["record_sha256"] = record_digest(rec)
    world.use_store([rec])
    assert_blocked_before_anything(world, world.run())
    rec = approval_record(world.definition_sha256)
    rec["acquisition"] = dict(rec["acquisition"], allowed_host="example.org")
    rec["record_sha256"] = record_digest(rec)
    world.use_store([rec])
    assert_blocked_before_anything(world, world.run())


def test_source_definition_change_invalidates_approval(world) -> None:
    world.use_store()
    path = world.repo / "api/elevation/conf/sources.json"
    doc = json.loads(path.read_text())
    doc["sources"][SOURCE]["acquisition"]["tiles"].append({"x": 14554, "y": 6451})
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
    assert_blocked_before_anything(world, world.run())


def test_source_definition_must_name_the_record(tmp_path) -> None:
    world = World(tmp_path, BODIES, approval_ref="apr-test-only-other")
    world.use_store()
    assert_blocked_before_anything(world, world.run())


@pytest.mark.parametrize("now", ["2019-12-31T23:59:59", "2099-01-01T00:00:00"],
                         ids=["not-yet-valid", "expired"])
def test_validity_window(world, now) -> None:
    moment = datetime.fromisoformat(now).replace(tzinfo=timezone.utc)
    world.use_store(clock=lambda: moment)
    assert_blocked_before_anything(world, world.run())


def test_revoked_record_blocks(world) -> None:
    world.use_store(revoked=[TEST_APPROVAL_ID])
    assert_blocked_before_anything(world, world.run())


def test_two_matching_records_are_ambiguous(world) -> None:
    world.use_store([approval_record(world.definition_sha256),
                     approval_record(world.definition_sha256, approval_id="apr-test-only-twin")])
    assert_blocked_before_anything(world, world.run())


def _tamper(store):
    path = store / "approvals" / f"{TEST_APPROVAL_ID}.json"
    doc = json.loads(path.read_text())
    doc["region_codes"] = ["13", "14"]  # widening without a new digest
    path.write_text(json.dumps(doc))


def _symlink(store):
    path = store / "approvals" / f"{TEST_APPROVAL_ID}.json"
    real = store.parent / "elsewhere.json"
    path.rename(real)
    path.symlink_to(real)


def _hardlink(store):
    os.link(store / "approvals" / f"{TEST_APPROVAL_ID}.json", store.parent / "alias.json")


def _group_writable_file(store):
    os.chmod(store / "approvals" / f"{TEST_APPROVAL_ID}.json", 0o664)


def _group_writable_dir(store):
    os.chmod(store / "approvals", 0o775)


def _world_writable_root(store):
    os.chmod(store, 0o777)


def _unexpected_entry(store):
    # A valid record under a name outside the convention must not be skipped silently.
    src = store / "approvals" / f"{TEST_APPROVAL_ID}.json"
    (store / "approvals" / "backup.json").write_bytes(src.read_bytes())


def _renamed(store):
    (store / "approvals" / f"{TEST_APPROVAL_ID}.json").rename(
        store / "approvals" / "apr-test-only-renamed.json")


def _fixture_marker(store):
    (store / FIXTURE_ROOT_MARKER).write_text("x")


def _pending_eligibility(store):
    path = store / "approvals" / f"{TEST_APPROVAL_ID}.json"
    doc = json.loads(path.read_text())
    doc["publication"]["eligibility_status"] = "pending"
    doc["record_sha256"] = record_digest(doc)
    path.write_text(json.dumps(doc))


def _fixture_style_record(store):
    path = store / "approvals" / f"{TEST_APPROVAL_ID}.json"
    path.write_bytes((REPO / "tests/fixtures/elevation-fixture/authorization/download.json")
                     .read_bytes())


@pytest.mark.parametrize("damage", [
    _tamper, _symlink, _hardlink, _group_writable_file, _group_writable_dir,
    _world_writable_root, _unexpected_entry, _renamed, _fixture_marker, _pending_eligibility,
    _fixture_style_record,
])
def test_untrusted_or_tampered_store_blocks(world, damage) -> None:
    damage(world.use_store())
    assert_blocked_before_anything(world, world.run())


def test_store_inside_repository_is_refused(world) -> None:
    record = approval_record(world.definition_sha256)
    world.use_store([record])
    authorizer = ProductionAuthorizer(world.store, protected_roots=(world.store.parent,))
    with pytest.raises(Exception, match="APPROVAL_REQUIRED"):
        authorizer.authorize(api_id="elevation", operation="download", source_ref=SOURCE,
                             region_codes=("13",), definition=definition(world))


def test_publish_attribution_must_match_source_definition(world) -> None:
    rec = approval_record(world.definition_sha256)
    rec["publication"] = dict(rec["publication"], attribution_text="something else")
    rec["record_sha256"] = record_digest(rec)
    world.use_store([rec])
    assert_blocked_before_anything(world, world.run(), module="publish")


def test_production_run_refuses_fixture_data_root(world) -> None:
    world.use_store()
    (world.data_root / FIXTURE_ROOT_MARKER).write_text("x")
    results = world.run()
    assert modules(results) == [("download", "FAILED", "INVALID_INPUT")]
    assert world.gsi.requested_paths == []


def test_failed_republish_authorization_keeps_published_state(world) -> None:
    world.use_store()
    first = world.run()
    assert modules(first)[-1][:2] == ("publish", "SUCCESS")
    before = files(world.data_root)
    world.use_store(revoked=[TEST_APPROVAL_ID])
    assert modules(world.run()) == [("download", "BLOCKED", "APPROVAL_REQUIRED")]
    assert files(world.data_root) == before
    doc = post(world.api(), dict(zip(("lat", "lon"), centre(*A, 10, 20)))).json()
    assert doc["status"] == "success" and doc["dataset"]["publication_version"] == \
        f"pub-{first[0].run_id}"


# -- CLI ----------------------------------------------------------------------------------------
def test_cli_approval_check_and_digest(tmp_path) -> None:
    from test_cli import cli

    store = write_store(tmp_path / "store", [approval_record("0" * 64)])
    proc = cli("approval-check", "--api", "elevation", "--region", "13", "--source", SOURCE,
               "--approval-root", str(store), "--publish")
    doc = json.loads(proc.stdout)
    assert proc.returncode == 3 and doc["status"] == "BLOCKED"
    assert [e["decision"] for e in doc["operations"]] == ["BLOCKED"] * 4
    assert doc["definition_raw_sha256"] and str(store) not in proc.stdout
    record = store / "approvals" / f"{TEST_APPROVAL_ID}.json"
    digest = cli("approval-digest", "--record", str(record))
    assert json.loads(digest.stdout)["record_sha256"] == json.loads(record.read_text())[
        "record_sha256"]
    before = record.read_bytes()
    assert record.read_bytes() == before  # read only


def test_cli_production_with_store_is_blocked_for_committed_definition(tmp_path) -> None:
    from test_cli import FIXTURE, cli, fixture_root

    store = write_store(tmp_path / "store", [approval_record("0" * 64)])
    data = tmp_path / "data"
    data.mkdir()
    proc = cli("pipeline", "--api", "elevation", "--region", "13", "--source", SOURCE,
               "--production", "--approval-root", str(store), "--data-root", str(data),
               "--allow-network", "--publish")
    assert proc.returncode == 3 and json.loads(proc.stdout)["error_code"] == "APPROVAL_REQUIRED"
    assert files(data) == []
    (tmp_path / "fx").mkdir()
    root = fixture_root(tmp_path / "fx")
    misuse = cli("pipeline", "--api", "elevation", "--region", "13",
                 "--source", "fixture-dem-png-tokyo", "--fixture", str(FIXTURE),
                 "--approval-root", str(store), "--data-root", str(root))
    assert misuse.returncode == 2 and json.loads(misuse.stdout)["error_code"] == "INVALID_INPUT"


def test_committed_definition_remains_unapproved() -> None:
    src = json.loads((REPO / "api/elevation/conf/sources.json").read_text())["sources"][SOURCE]
    assert src["approval_ref"] is None and src["acquisition"]["tiles"] is None
    assert not list(REPO.rglob("apr-*.json"))  # no approval record is committed


def test_published_schemas_match_code() -> None:
    from hererisk.common.approval_store import APPROVAL_RECORD_SCHEMA, REVOCATIONS_SCHEMA

    base = REPO / "docs/architecture/schemas"
    assert json.loads((base / "production-approval-record.schema.json").read_text()) == \
        APPROVAL_RECORD_SCHEMA
    assert json.loads((base / "approval-revocations.schema.json").read_text()) == \
        REVOCATIONS_SCHEMA
    example = json.loads((base / "production-approval-record.example.json").read_text())
    assert example["record_sha256"].startswith("<")  # a template: never a valid record


def test_runbook_two_phase_acquire_then_publish(tmp_path) -> None:
    """Runbook: approve download..validate first, add publish to the same record later."""
    from hererisk.elevation.normalize.stage import NormalizeStage
    from hererisk.elevation.publish.stage import PublishStage
    from hererisk.elevation.validate.stage import ValidateStage

    world = World(tmp_path, BODIES, approval_ref=TEST_APPROVAL_ID,
                  stages=(NormalizeStage(), ValidateStage()))
    world.use_store([approval_record(world.definition_sha256,
                                     operations=("download", "normalize", "validate"))])
    first = world.run()
    assert [m[1] for m in modules(first)] == ["SUCCESS"] * 3
    assert world.api()._published.datasets == ()
    requests = list(world.gsi.requested_paths)
    world.stages = (NormalizeStage(), ValidateStage(), PublishStage())
    world.orchestrator._stages = {"elevation": world.stages}
    assert modules(world.run(resume=first[0].run_id))[-1] == (
        "publish", "BLOCKED", "APPROVAL_REQUIRED")  # not yet approved for publish
    world.use_store()  # the same record, publish + publication added (new digest)
    again = world.run(resume=first[0].run_id)
    assert [m[:2] for m in modules(again)] == [(m, "SUCCESS") for m in OPS]
    assert world.gsi.requested_paths == requests  # resume: no new download
    doc = post(world.api(), dict(zip(("lat", "lon"), centre(*A, 10, 20)))).json()
    assert doc["result"] == {"elevation_m": 12.34}
