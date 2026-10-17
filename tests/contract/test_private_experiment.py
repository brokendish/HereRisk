"""Contract tests: Phase 1-G private_experiment mode.

The real ProductionAuthorizer (bound to the private_experiment or production
context) reads TEST-ONLY approval stores in temporary directories; GSI is a
fake connection (no network). Nothing here is a real approval of any kind.
"""

from __future__ import annotations

import json

import pytest

from e2e_support import (
    PRIVATE_APPROVAL_ID,
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
from hererisk.common.authorization import ExecutionContext, ProductionAuthorizer
from hererisk.common.config import ConfigurationManager
from hererisk.common.storage import (
    FIXTURE_ROOT_MARKER,
    PRIVATE_ROOT_MARKER,
    init_private_data_root,
)
from hererisk.elevation.api import server
from hererisk.elevation.api.published import PublishedSet, StartupError

PRIVATE = ExecutionContext.PRIVATE_EXPERIMENT
A, B = TOKYO_TILES
BODIES = {A: png_with({(10, 20): (0, 4, 210), (11, 20): (0, 0, 0), (12, 20): (255, 255, 136),
                       (13, 20): (128, 0, 0)}),
          B: png_with({}, default=(0, 1, 0))}
OPS = ("download", "normalize", "validate", "publish")


def modules(results):
    return [(r.module, r.status.value, r.error_code) for r in results]


def files(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def at(tile, px, py=20):
    return dict(zip(("lat", "lon"), centre(*tile, px, py)))


@pytest.fixture
def private(tmp_path):
    (tmp_path / "private").mkdir()
    return World(tmp_path / "private", BODIES, approval_ref=PRIVATE_APPROVAL_ID, context=PRIVATE)


@pytest.fixture
def public(tmp_path):
    (tmp_path / "public").mkdir()
    return World(tmp_path / "public", BODIES, approval_ref=TEST_APPROVAL_ID)


def blocked_before_anything(world, results, module="download", code="APPROVAL_REQUIRED",
                            status="BLOCKED"):
    assert modules(results) == [(module, status, code)]
    assert world.gsi.requested_paths == []
    assert [f for f in files(world.data_root) if f != PRIVATE_ROOT_MARKER] == []


# -- private end to end ------------------------------------------------------------------------
def test_private_four_stages_and_private_api(private) -> None:
    private.use_store()
    results = private.run()
    assert [m[:2] for m in modules(results)] == [(m, "SUCCESS") for m in OPS]
    run_id = results[0].run_id
    api_dir = private.data_root / "elevation"
    for kind in ("normalizations", "validations", "publications"):
        rec = json.loads((api_dir / f"records/{kind}/{run_id}.json").read_bytes())
        assert rec["execution_context"] == "private_experiment"
        assert rec["authorization_ref"] == PRIVATE_APPROVAL_ID
    api = private.api()
    for (tile, px), value in {(A, 10): 12.34, (A, 11): 0.0, (A, 12): -1.2, (B, 3): 2.56}.items():
        doc = post(api, at(tile, px)).json()
        assert doc["status"] == "success" and doc["result"] == {"elevation_m": value}
        assert doc["dataset"]["publication_version"] == f"pub-{run_id}"
        assert doc["dataset"]["attribution"] == {"text": TEST_ATTRIBUTION,
                                                 "license": TEST_TERMS["license"],
                                                 "url": TEST_TERMS["attribution_url"]}
    assert post(api, at(A, 13)).json()["error"]["code"] == "elevation_nodata"
    assert post(api, {"lat": 43.06, "lon": 141.35}).json()["error"]["code"] == "no_coverage"
    assert private.gsi.requested_paths  # served by the fake GSI only (no real HTTPS)


def test_private_data_is_invisible_to_public_api(private, public) -> None:
    private.use_store()
    private.run()
    with pytest.raises(StartupError):
        PublishedSet.load(private.data_root)  # public mode refuses a private root
    with pytest.raises(StartupError):
        server.build_server(private.data_root, "127.0.0.1", 0)
    # The public root stays empty: nothing is copied or promoted.
    assert not (public.data_root / "elevation").exists()
    assert public.api(private=False)._published.datasets == ()


def test_public_side_stays_blocked(public) -> None:
    public.use_store([])  # no approvals
    blocked_before_anything(public, public.run())
    public.authorizer = ProductionAuthorizer()  # the CLI default without --approval-root
    public.orchestrator._authorizer = public.authorizer
    blocked_before_anything(public, public.run())


# -- no inheritance between modes ----------------------------------------------------------------
def test_private_approval_never_authorizes_public(public) -> None:
    record = approval_record(public.definition_sha256, context="private_experiment",
                             approval_id=TEST_APPROVAL_ID.replace("apr-", "apr-private-"))
    public.use_store([record])
    blocked_before_anything(public, public.run())


def test_private_publish_approval_cannot_publish_publicly(public) -> None:
    # Public record without publish; a private record grants publish only privately.
    public.use_store([
        approval_record(public.definition_sha256, operations=("download", "normalize", "validate")),
        approval_record(public.definition_sha256, context="private_experiment")])
    blocked_before_anything(public, public.run(), module="publish")


def test_public_approval_never_authorizes_private(private) -> None:
    record = approval_record(private.definition_sha256, context="production",
                             approval_id="apr-public-for-private-test")
    private.use_store([record])
    blocked_before_anything(private, private.run())


def _edit(record, **changes):
    record = json.loads(json.dumps(record))
    for path, value in changes.items():
        target = record
        *parents, last = path.split("__")
        for key in parents:
            target = target[key]
        if value is None:
            target.pop(last, None)
        else:
            target[last] = value
    record["record_sha256"] = record_digest(record)
    return record


@pytest.mark.parametrize("change", [
    {"publication__eligibility_status": "approved",
     "publication__eligibility_ref": "x"},                       # public qualification reused
    {"publication__private_use": None},                         # no private-use confirmation
    {"publication__private_use__purpose": "commercial"},
    {"publication__private_use__access": "public"},
    {"approval_id": "apr-test-only-not-private"},              # wrong id space
])
def test_private_record_needs_its_own_qualification(private, change) -> None:
    approval_id = change.get("approval_id", PRIVATE_APPROVAL_ID)
    if approval_id != PRIVATE_APPROVAL_ID:  # Source Definition names that id
        (private.tmp / "alt").mkdir()
        private = World(private.tmp / "alt", BODIES, approval_ref=approval_id, context=PRIVATE)
    record = _edit(approval_record(private.definition_sha256, context="private_experiment"),
                   **change)
    private.use_store([record])
    blocked_before_anything(private, private.run())


@pytest.mark.parametrize("change", [
    {"publication__private_use": {"purpose": "non_commercial_personal_experiment",
                                  "access": "owner_only_loopback", "usage_review_ref": "x",
                                  "confirmed_by": "x", "confirmed_at": "2026-01-01T00:00:00Z"}},
    {"approval_id": "apr-private-looks-public"},
])
def test_public_record_cannot_carry_private_qualification(public, change) -> None:
    approval_id = change.get("approval_id", TEST_APPROVAL_ID)
    if approval_id != TEST_APPROVAL_ID:
        (public.tmp / "alt").mkdir()
        public = World(public.tmp / "alt", BODIES, approval_ref=approval_id)
    record = _edit(approval_record(public.definition_sha256), **change)
    public.use_store([record])
    blocked_before_anything(public, public.run())


# -- private denials -------------------------------------------------------------------------------
def test_private_definition_mismatch(private) -> None:
    private.use_store([approval_record("0" * 64, context="private_experiment")])
    blocked_before_anything(private, private.run())


@pytest.mark.parametrize("case", ["expired", "revoked", "tampered", "unlisted-publish"])
def test_private_expired_revoked_tampered(private, case) -> None:
    from datetime import datetime, timezone

    if case == "expired":
        private.use_store(clock=lambda: datetime(2099, 1, 1, tzinfo=timezone.utc))
    elif case == "revoked":
        private.use_store(revoked=[PRIVATE_APPROVAL_ID])
    elif case == "tampered":
        store = private.use_store()
        path = store / "approvals" / f"{PRIVATE_APPROVAL_ID}.json"
        doc = json.loads(path.read_text())
        doc["tiles"].append({"z": 14, "x": 1, "y": 1})
        path.write_text(json.dumps(doc))
    else:
        private.use_store([approval_record(private.definition_sha256,
                                           context="private_experiment",
                                           operations=("download", "normalize", "validate"))])
        blocked_before_anything(private, private.run(), module="publish")
        return
    blocked_before_anything(private, private.run())


# -- data root separation -------------------------------------------------------------------------
def test_private_run_requires_private_root(tmp_path) -> None:
    (tmp_path / "w").mkdir()
    world = World(tmp_path / "w", BODIES, approval_ref=PRIVATE_APPROVAL_ID, context=PRIVATE)
    world.use_store()
    (world.data_root / PRIVATE_ROOT_MARKER).unlink()  # a plain (public) root
    blocked_before_anything(world, world.run(), status="FAILED", code="INVALID_INPUT")
    (world.data_root / PRIVATE_ROOT_MARKER).write_text("something else\n")  # wrong marker
    blocked_before_anything(world, world.run(), status="FAILED", code="INVALID_INPUT")


def test_private_run_refuses_fixture_marked_root(private) -> None:
    private.use_store()
    (private.data_root / FIXTURE_ROOT_MARKER).write_text("x")
    results = private.run()
    assert modules(results) == [("download", "FAILED", "INVALID_INPUT")]
    assert private.gsi.requested_paths == []


def test_public_run_refuses_private_root(public) -> None:
    public.use_store()
    init_private_data_root(public.data_root, protected_roots=(REPO,))
    results = public.run()
    assert modules(results) == [("download", "FAILED", "INVALID_INPUT")]
    assert public.gsi.requested_paths == [] and files(public.data_root) == [PRIVATE_ROOT_MARKER]


def test_fixture_run_refuses_private_marker(harness) -> None:
    (harness.data_root / PRIVATE_ROOT_MARKER).write_text("x")
    result = harness.run()
    assert result.status.value == "FAILED" and result.error_code == "INVALID_INPUT"


def test_private_root_init_rules(tmp_path) -> None:
    with pytest.raises(Exception):
        init_private_data_root(REPO / "tests", protected_roots=(REPO,))
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "x").write_text("x")
    with pytest.raises(Exception):
        init_private_data_root(busy)
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    init_private_data_root(fresh)
    assert (fresh / PRIVATE_ROOT_MARKER).read_bytes().startswith(b"hererisk private_experiment")


# -- private API startup -------------------------------------------------------------------------
def test_private_api_refuses_public_and_fixture_roots(public, harness) -> None:
    with pytest.raises(StartupError):
        PublishedSet.load(public.data_root, private_experiment=True)
    with pytest.raises(StartupError):
        PublishedSet.load(harness.data_root, private_experiment=True)
    with pytest.raises(StartupError):
        PublishedSet.load(harness.data_root, private_experiment=True, allow_fixture_root=True)


def test_private_api_refuses_corrupt_registry(private) -> None:
    private.use_store()
    private.run()
    PublishedSet.load(private.data_root, private_experiment=True).close()
    pointer = private.data_root / "elevation/rel/registry/13/current.json"
    pointer.write_bytes(b"{")
    with pytest.raises(StartupError):
        PublishedSet.load(private.data_root, private_experiment=True)


def test_private_server_is_loopback_only(private) -> None:
    private.use_store()
    private.run()
    for host in ("0.0.0.0", "192.0.2.1", "::"):
        with pytest.raises(StartupError):
            server.build_server(private.data_root, host, 0, private_experiment=True)
    with pytest.raises(StartupError):
        server.build_server(private.data_root, "127.0.0.1", 0, private_experiment=True,
                            fixture_demo=True)
    httpd = server.build_server(private.data_root, "127.0.0.1", 0, private_experiment=True)
    assert httpd.server_address[0] == "127.0.0.1"
    httpd.server_close()


def test_private_server_main_exit_codes(private, public) -> None:
    assert server.main(["--data-root", str(public.data_root), "--port", "0",
                        "--private-experiment"]) == 3
    assert server.main(["--data-root", str(private.data_root), "--port", "0",
                        "--host", "0.0.0.0", "--private-experiment"]) == 3


# -- CLI ----------------------------------------------------------------------------------------
def test_cli_private_root_and_blocked_pipeline(tmp_path) -> None:
    from test_cli import cli

    root = tmp_path / "private-root"
    root.mkdir()
    assert cli("init-private-root", "--data-root", str(root)).returncode == 0
    assert cli("init-private-root", "--data-root", str(root)).returncode == 2  # not empty
    assert cli("init-private-root", "--data-root", str(REPO / "docs")).returncode == 2
    store = write_store(tmp_path / "store", [approval_record("0" * 64,
                                                            context="private_experiment")])
    for extra in ([], ["--approval-root", str(store), "--allow-network", "--publish"]):
        proc = cli("pipeline", "--api", "elevation", "--region", "13", "--source", SOURCE,
                   "--private-experiment", "--data-root", str(root), *extra)
        assert proc.returncode == 3 and json.loads(proc.stdout)["error_code"] == \
            "APPROVAL_REQUIRED", extra
    assert files(root) == [PRIVATE_ROOT_MARKER]
    check = cli("approval-check", "--api", "elevation", "--region", "13", "--source", SOURCE,
                "--approval-root", str(store), "--context", "private_experiment", "--publish")
    doc = json.loads(check.stdout)
    assert check.returncode == 3 and doc["context"] == "private_experiment"
    assert {e["decision"] for e in doc["operations"]} == {"BLOCKED"}


def test_definition_for_private_needs_private_record(private) -> None:
    """Direct check: the private authorizer ignores production records entirely."""
    private.use_store([approval_record(private.definition_sha256),  # public record
                       approval_record(private.definition_sha256, context="private_experiment")])
    definition = ConfigurationManager(private.repo, REPO).load("api", "elevation", "sources")
    grant = private.authorizer.authorize(api_id="elevation", operation="publish",
                                         source_ref=SOURCE, region_codes=("13",),
                                         definition=definition)
    assert grant.context is PRIVATE and grant.authorization_ref == PRIVATE_APPROVAL_ID
    public_authorizer = ProductionAuthorizer(private.store, protected_roots=(REPO,))
    with pytest.raises(Exception, match="APPROVAL_REQUIRED"):
        public_authorizer.authorize(api_id="elevation", operation="publish", source_ref=SOURCE,
                                    region_codes=("13",), definition=definition)


def test_publication_terms_check_each_mode_independently_of_schema() -> None:
    """Defense in depth: the authorizer re-checks what the schema already enforces."""
    source = {"usage": {"attribution_text": "t"}}
    base = {"license": "l", "attribution_url": "https://example.invalid/x", "attribution_text": "t"}
    private_use = {"purpose": "non_commercial_personal_experiment"}
    private = ProductionAuthorizer(context=PRIVATE)
    public = ProductionAuthorizer()
    ok_private = {"publication": dict(base, private_use=private_use)}
    ok_public = {"publication": dict(base, eligibility_status="approved", eligibility_ref="r")}
    assert private._publication_terms(ok_private, source)["license"] == "l"
    assert public._publication_terms(ok_public, source)["license"] == "l"
    for authorizer, record in [
            (private, ok_public), (private, {"publication": dict(base)}),
            (private, {"publication": dict(base, private_use=private_use,
                                           eligibility_status="approved")}),
            (public, ok_private), (public, {"publication": dict(base)}),
            (public, {"publication": dict(base, eligibility_status="approved",
                                          private_use=private_use)})]:
        with pytest.raises(Exception, match="APPROVAL_REQUIRED"):
            authorizer._publication_terms(record, source)


def test_private_api_refuses_private_root_with_fixture_marker(private) -> None:
    private.use_store()
    private.run()
    (private.data_root / FIXTURE_ROOT_MARKER).write_text("x")
    with pytest.raises(StartupError):
        PublishedSet.load(private.data_root, private_experiment=True)


def test_server_mode_flags_are_exclusive_before_loading(monkeypatch, tmp_path) -> None:
    def must_not_load(*a, **k):
        raise AssertionError("loaded")

    monkeypatch.setattr(server.PublishedSet, "load", must_not_load)
    with pytest.raises(StartupError):
        server.build_server(tmp_path, "127.0.0.1", 0, private_experiment=True, fixture_demo=True)
