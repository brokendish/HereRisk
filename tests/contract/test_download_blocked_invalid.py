"""Contract tests: BLOCKED and invalid-input/configuration paths start no transfer."""

from __future__ import annotations

import pytest

import fixture_builder as fb
from hererisk.common.authorization import FixtureAuthorizer, ProductionAuthorizer
from hererisk.common.config import ConfigurationManager
from hererisk.common.logging import ListSink, StructuredLogger
from hererisk.common.orchestrator import DownloadRequest, Orchestrator
from hererisk.common.result import Status
from hererisk.elevation.download.download import ElevationDownload
from hererisk.elevation.download.transport import FixtureTransport, UnavailableTransport

REPO = fb.REPO_ROOT


def assert_nothing_happened(harness, result, status, code) -> None:
    assert result.status is status, result
    assert result.error_code == code
    assert result.artifacts == ()
    assert harness.transport.requested_urls == []
    assert not any("acquisitions" in p or "commits" in p for p in harness.files())


def production_orchestrator(data_root, authorizer, transport):
    return Orchestrator(
        config_manager=ConfigurationManager(REPO, REPO),
        authorizer=authorizer,
        modules={"elevation": ElevationDownload(transport)},
        data_root=data_root,
        logger=StructuredLogger(ListSink()),
    )


def test_production_definition_is_blocked(harness) -> None:
    orch = production_orchestrator(harness.data_root, ProductionAuthorizer(), UnavailableTransport())
    result = orch.run_download(DownloadRequest("elevation", ("13",), "gsi-dem10b-candidate"))
    assert result.status is Status.BLOCKED and result.error_code == "APPROVAL_REQUIRED"
    assert result.exit_code == 3
    assert harness.files() == {} and list(harness.data_root.iterdir()) == []


def test_fixture_approval_cannot_authorize_production_definition(harness) -> None:
    authorizer = FixtureAuthorizer(harness.fixture_root / "authorization/download.json", REPO)
    orch = production_orchestrator(harness.data_root, authorizer, harness.transport)
    result = orch.run_download(DownloadRequest("elevation", ("13",), "gsi-dem10b-candidate"))
    assert_nothing_happened(harness, result, Status.BLOCKED, "APPROVAL_REQUIRED")


def test_production_authorizer_blocks_even_fixture_definition(harness) -> None:
    result = harness.run(authorizer=ProductionAuthorizer())
    assert_nothing_happened(harness, result, Status.BLOCKED, "APPROVAL_REQUIRED")


def test_fixture_authorizer_with_production_transport_is_blocked(harness) -> None:
    result = harness.run(module=ElevationDownload(UnavailableTransport()))
    assert_nothing_happened(harness, result, Status.BLOCKED, "APPROVAL_REQUIRED")


def test_authorization_bound_to_definition_hash(harness) -> None:
    conf = harness.fixture_root / "api/elevation/conf/sources.json"
    conf.write_bytes(conf.read_bytes().replace(b'"fixture-1"', b'"fixture-2"'))
    result = harness.run()
    assert_nothing_happened(harness, result, Status.BLOCKED, "APPROVAL_REQUIRED")


def test_missing_authorization_is_blocked(harness) -> None:
    (harness.fixture_root / "authorization/download.json").unlink()
    assert_nothing_happened(harness, harness.run(), Status.BLOCKED, "APPROVAL_REQUIRED")


def test_authorization_inside_production_conf_rejected(harness, tmp_path) -> None:
    # A fixture authorization file must not live in the production conf tree.
    prod_root = tmp_path / "prod"
    planted = prod_root / "api" / "elevation" / "conf" / "download-authorization.json"
    planted.parent.mkdir(parents=True)
    planted.write_bytes((harness.fixture_root / "authorization/download.json").read_bytes())
    result = harness.run(authorizer=FixtureAuthorizer(planted, prod_root))
    assert_nothing_happened(harness, result, Status.BLOCKED, "APPROVAL_REQUIRED")


@pytest.mark.parametrize(
    "regions,code,status",
    [
        (("01",), "TARGET_UNCONFIGURED", Status.BLOCKED),
        (("13", "01"), "TARGET_UNCONFIGURED", Status.BLOCKED),
        (("27",), "TARGET_UNCONFIGURED", Status.BLOCKED),  # region exists, other source
        (("48",), "INVALID_INPUT", Status.FAILED),
        (("1",), "INVALID_INPUT", Status.FAILED),
        ((), "INVALID_INPUT", Status.FAILED),
        (("13", "13"), "INVALID_INPUT", Status.FAILED),
    ],
)
def test_region_validation(harness, regions, code, status) -> None:
    assert_nothing_happened(harness, harness.run(regions=regions), status, code)


@pytest.mark.parametrize("source", ["no-such-source", "../etc", "Fixture", ""])
def test_source_ref_validation(harness, source) -> None:
    assert_nothing_happened(harness, harness.run(source=source), Status.FAILED, "INVALID_INPUT")


@pytest.mark.parametrize("api", ["flood", "../elevation", ""])
def test_unknown_api_rejected(harness, api) -> None:
    result = harness.orchestrator().run_download(DownloadRequest(api, ("13",), "x"))
    assert_nothing_happened(harness, result, Status.FAILED, "INVALID_INPUT")
    assert all(e["api_id"] is None for e in harness.sink.entries)


@pytest.mark.parametrize(
    "transform",
    [
        lambda raw: raw[:-10],  # JSON syntax
        lambda raw: raw.replace(b'"hazard": "elevation",', b'"hazard": "elevation", "hazard": "elevation",'),
        lambda raw: raw.replace(b'"hazard": "elevation",', b'"hazard": "elevation", "extra": 1,'),
        lambda raw: raw.replace(b'"x": 14550', b'"x": 16384'),  # out of 2^14 range
    ],
    ids=["syntax", "duplicate-key", "unknown-key", "tile-out-of-range"],
)
def test_invalid_configuration_starts_no_transfer(harness, transform) -> None:
    raw = fb.dump(fb.fixture_definition())
    harness.rebuild(definition_bytes=transform(raw))  # authorization re-bound to new bytes
    result = harness.run()
    assert_nothing_happened(harness, result, Status.FAILED, "INVALID_CONFIGURATION")
    assert result.exit_code == 2


def test_unapproved_source_without_tiles_blocked(harness) -> None:
    definition = fb.fixture_definition()
    src = definition["sources"]["fixture-dem-png-tokyo"]
    src.update(approval_ref=None)
    src["acquisition"]["tiles"] = None
    harness.rebuild(definition_bytes=fb.dump(definition))
    assert_nothing_happened(harness, harness.run(), Status.BLOCKED, "APPROVAL_REQUIRED")


def test_unsupported_pipeline_version_blocked(harness) -> None:
    definition = fb.fixture_definition()
    definition["sources"]["fixture-dem-png-tokyo"]["pipeline"]["version"] = "fixture-9.9"
    harness.rebuild(definition_bytes=fb.dump(definition))
    assert_nothing_happened(harness, harness.run(), Status.BLOCKED, "APPROVAL_REQUIRED")


def test_source_alias_with_same_tiles_rejected(harness) -> None:
    sources = {
        "fixture-dem-png-tokyo": {"regions": ["13"], "tiles": [(14550, 6450)]},
        "fixture-dem-png-alias": {"regions": ["14"], "tiles": [(14550, 6450)]},
    }
    harness.rebuild(sources)
    assert_nothing_happened(harness, harness.run(), Status.FAILED, "INVALID_CONFIGURATION")


def test_too_many_tiles_for_policy(harness) -> None:
    tiles = [(14000 + i, 6000) for i in range(17)]
    harness.rebuild({"fixture-dem-png-tokyo": {"regions": ["13"], "tiles": tiles}})
    assert_nothing_happened(harness, harness.run(), Status.FAILED, "INVALID_CONFIGURATION")


def test_fixture_transport_never_serves_real_urls(tmp_path) -> None:
    transport = FixtureTransport(tmp_path)
    assert not transport.accepts("https://cyberjapandata.gsi.go.jp/xyz/dem_png/14/1/1.png")
    assert not transport.accepts("https://fixture.invalid/../14/1/1.png")
    assert not transport.accepts("https://user@fixture.invalid/dem_png/14/1/1.png")
