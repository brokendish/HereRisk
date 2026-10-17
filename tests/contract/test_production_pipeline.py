"""Contract tests: Phase 1-D.3 production-format pipeline (mocked GSI, no real network).

The production context needs a production authorization. Production code can
never grant one (``ProductionAuthorizer`` always BLOCKS), so the success paths
here use the TEST-ONLY authorizer double from tests/e2e_support.py and a
temporary test-only copy of the Source Definition. This is not a production
approval and must never be reported as one.
"""

from __future__ import annotations

import json

import pytest

import fixture_builder as fb
from e2e_support import (
    REPO,
    SOURCE,
    TOKYO_TILES,
    GsiFake,
    TestOnlyProductionAuthorizer,
    World,
    png_with,
)
from hererisk.common.authorization import ExecutionContext, ProductionAuthorizer
from hererisk.common.config import ConfigurationManager
from hererisk.common.logging import ListSink, StructuredLogger
from hererisk.common.orchestrator import DownloadRequest, Orchestrator
from hererisk.common.result import Status
from hererisk.elevation.download.download import ElevationDownload
from hererisk.elevation.download.gsi_transport import GsiHttpTransport
from hererisk.elevation.normalize.stage import NormalizeStage
from hererisk.elevation.validate.stage import ValidateStage

BODIES = {TOKYO_TILES[0]: png_with({(1, 1): (0, 4, 210)}), TOKYO_TILES[1]: png_with({})}


def modules(results):
    return [(r.module, r.status.value, r.error_code) for r in results]


def files(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


# -- success with mocks ----------------------------------------------------------------------
@pytest.mark.parametrize("tiles", [TOKYO_TILES[:1], TOKYO_TILES], ids=["1-tile", "2-tiles"])
def test_production_format_pipeline_with_mocked_gsi(tmp_path, tiles) -> None:
    world = World(tmp_path, {t: BODIES[t] for t in tiles},
                  stages=(NormalizeStage(), ValidateStage()))
    results = world.run()
    assert modules(results) == [("download", "SUCCESS", None), ("normalize", "SUCCESS", None),
                                ("validate", "SUCCESS", None)]
    assert world.gsi.requested_paths == [f"/xyz/dem_png/14/{x}/{y}.png" for x, y in tiles]
    run_id = results[0].run_id
    api = world.data_root / "elevation"
    record = json.loads((api / "records" / results[0].artifacts[0].record_ref).read_bytes())
    assert record["requested_url"].startswith("https://cyberjapandata.gsi.go.jp/xyz/dem_png/14/")
    assert record["pipeline"] == {"id": "elevation-download", "version": "0.1"}
    assert record["usage_snapshot"]["approval_ref"] == "test-only-not-an-approval"
    nrec = json.loads((api / f"records/normalizations/{run_id}.json").read_bytes())
    vrec = json.loads((api / f"records/validations/{run_id}.json").read_bytes())
    assert nrec["execution_context"] == vrec["execution_context"] == "production"
    assert nrec["authorization_ref"] == "test-only-not-an-approval-normalize"
    assert vrec["profile"] == "elevation-normalized-v0.1"
    assert not (api / "rel").exists()  # Validate never publishes


def test_resume_reuses_without_new_requests(tmp_path) -> None:
    world = World(tmp_path, BODIES, stages=(NormalizeStage(), ValidateStage()))
    first = world.run()
    before = files(world.data_root)
    again = world.run(resume=first[0].run_id)
    assert again == first and files(world.data_root) == before
    assert len(world.gsi.requested_paths) == 2  # only the first run fetched


def test_gsi_http_error_stops_pipeline(tmp_path) -> None:
    world = World(tmp_path, BODIES, stages=(NormalizeStage(), ValidateStage()))
    world.gsi.kwargs = {"status": 404}
    results = world.run()
    assert modules(results) == [("download", "FAILED", "HTTP_404")]
    assert not (world.data_root / "elevation/records/normalizations").exists()


def test_nodata_pixels_are_not_errors_and_breakage_is_not_nodata(tmp_path) -> None:
    world = World(tmp_path, {TOKYO_TILES[0]: b"not a png"}, stages=(NormalizeStage(), ValidateStage()))
    results = world.run()
    assert modules(results)[-1][2] in ("PNG_INVALID",)  # broken data is a failure, not no-data


# -- real production paths are BLOCKED ---------------------------------------------------------
def test_real_production_authorizer_blocks_before_any_request(tmp_path) -> None:
    gsi = GsiFake(BODIES)
    orch = Orchestrator(
        config_manager=ConfigurationManager(REPO, REPO), authorizer=ProductionAuthorizer(),
        modules={"elevation": ElevationDownload(GsiHttpTransport(connection_factory=gsi))},
        data_root=tmp_path, logger=StructuredLogger(ListSink()),
        stages={"elevation": (NormalizeStage(), ValidateStage())})
    results = orch.run_pipeline(DownloadRequest("elevation", ("13",), SOURCE),
                                context=ExecutionContext.PRODUCTION)
    assert modules(results) == [("download", "BLOCKED", "APPROVAL_REQUIRED")]
    assert gsi.requested_paths == [] and files(tmp_path) == []


def test_unapproved_real_source_definition_blocks_even_with_test_double(tmp_path) -> None:
    gsi = GsiFake(BODIES)
    orch = Orchestrator(
        config_manager=ConfigurationManager(REPO, REPO), authorizer=TestOnlyProductionAuthorizer(),
        modules={"elevation": ElevationDownload(GsiHttpTransport(connection_factory=gsi))},
        data_root=tmp_path, logger=StructuredLogger(ListSink()),
        stages={"elevation": (NormalizeStage(), ValidateStage())})
    results = orch.run_pipeline(DownloadRequest("elevation", ("13",), SOURCE),
                                context=ExecutionContext.PRODUCTION)
    # The committed sources.json keeps approval_ref = null: never activated.
    assert modules(results) == [("download", "BLOCKED", "APPROVAL_REQUIRED")]
    assert gsi.requested_paths == [] and files(tmp_path) == []
    src = json.loads((REPO / "api/elevation/conf/sources.json").read_text())["sources"][SOURCE]
    assert src["approval_ref"] is None and src["acquisition"]["tiles"] is None


@pytest.mark.parametrize("refused", ["normalize", "validate", "publish"])
def test_missing_stage_authorization_blocks_before_network(tmp_path, refused) -> None:
    world = World(tmp_path, BODIES, authorizer=TestOnlyProductionAuthorizer(refuse={refused}))
    results = world.run()
    assert modules(results) == [(refused, "BLOCKED", "APPROVAL_REQUIRED")]
    assert world.gsi.requested_paths == [] and files(world.data_root) == []


def test_fixture_authorization_never_runs_production_context(harness) -> None:
    orch = harness.orchestrator(stages={"elevation": (NormalizeStage(), ValidateStage())})
    results = orch.run_pipeline(DownloadRequest("elevation", ("13",), "fixture-dem-png-tokyo"),
                                context=ExecutionContext.PRODUCTION)
    assert modules(results) == [("download", "BLOCKED", "APPROVAL_REQUIRED")]
    assert harness.files() == {}


def test_production_transport_refuses_fixture_and_foreign_urls() -> None:
    transport = GsiHttpTransport(connection_factory=GsiFake(BODIES))
    for url in ("https://fixture.invalid/dem_png/14/1/1.png",
                "https://cyberjapandata.gsi.go.jp/xyz/std/14/1/1.png",
                "http://cyberjapandata.gsi.go.jp/xyz/dem_png/14/1/1.png",
                "https://cyberjapandata.gsi.go.jp.evil/xyz/dem_png/14/1/1.png"):
        assert not transport.accepts(url)
    assert transport.context is ExecutionContext.PRODUCTION


# -- CLI ------------------------------------------------------------------------------------------
def test_cli_production_pipeline_is_blocked_without_network(tmp_path) -> None:
    from test_cli import cli

    for extra in ([], ["--allow-network"], ["--allow-network", "--publish"]):
        proc = cli("pipeline", "--api", "elevation", "--region", "13", "--source", SOURCE,
                   "--production", "--data-root", str(tmp_path), *extra)
        doc = json.loads(proc.stdout)
        assert proc.returncode == 3 and doc["error_code"] == "APPROVAL_REQUIRED", extra
    assert files(tmp_path) == []


def test_cli_allow_network_requires_production(tmp_path) -> None:
    from test_cli import FIXTURE, cli, fixture_root

    root = fixture_root(tmp_path)
    proc = cli("pipeline", "--api", "elevation", "--region", "13",
               "--source", "fixture-dem-png-tokyo", "--fixture", str(FIXTURE),
               "--data-root", str(root), "--allow-network")
    assert proc.returncode == 2 and json.loads(proc.stdout)["error_code"] == "INVALID_INPUT"
    both = cli("pipeline", "--api", "elevation", "--region", "13", "--source", SOURCE,
               "--fixture", str(FIXTURE), "--production", "--data-root", str(root))
    assert both.returncode == 2 and both.stdout == ""  # mutually exclusive: usage error


def test_cli_fixture_pipeline_with_publish(tmp_path) -> None:
    from test_cli import FIXTURE, cli, fixture_root

    root = fixture_root(tmp_path)
    proc = cli("pipeline", "--api", "elevation", "--region", "13",
               "--source", "fixture-dem-png-tokyo", "--fixture", str(FIXTURE),
               "--data-root", str(root), "--publish")
    doc = json.loads(proc.stdout)
    assert proc.returncode == 0, doc
    assert [r["module"] for r in doc["results"]] == ["download", "normalize", "validate", "publish"]
    assert (root / "elevation/rel/registry/13/current.json").is_file()
