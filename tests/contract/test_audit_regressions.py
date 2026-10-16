"""Regression tests for the Phase 1-A.1 independent verification findings (F03-F12).

Storage confinement / symlink races (F01/F02) are in tests/unit/test_storage_area.py,
PNG container rules (F07) in tests/unit/test_png_result_logging.py, CLI echo (F09)
in tests/contract/test_cli.py and real-process kills in test_process_kill.py.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import zlib
from pathlib import Path

import pytest

import fixture_builder as fb
from hererisk.common.config import ConfigurationError, ConfigurationManager, validate_with_schema
from hererisk.common.result import PipelineError, Status
from hererisk.common.storage import FIXTURE_ROOT_MARKER, init_fixture_data_root
from hererisk.elevation.download import record as rec
from hererisk.elevation.download.transport import FixtureTransport

REPO = fb.REPO_ROOT


def evidence(harness, run_id, art):
    root = harness.api_root
    return (
        root / "records" / art.record_ref,
        root / "records/commits" / f"{art.acquisition_id}.json",
        root / "work/acquisitions" / run_id / art.acquisition_id / "original.png",
    )


def forge(harness, run_id, art, edit) -> None:
    """Rewrite a Record and re-sign its marker hash so both stay hash-consistent."""
    record_path, marker_path, _ = evidence(harness, run_id, art)
    record = json.loads(record_path.read_bytes())
    edit(record)
    data = rec.to_bytes(record)
    record_path.write_bytes(data)
    marker = json.loads(marker_path.read_bytes())
    marker["record_sha256"] = hashlib.sha256(data).hexdigest()
    marker_path.write_bytes(rec.to_bytes(marker))


def assert_recovery(harness, run_id) -> None:
    before = harness.files()
    harness.transport.requested_urls.clear()
    result = harness.run(resume=run_id)
    assert result.status is Status.BLOCKED and result.error_code == "RECOVERY_REQUIRED", result
    assert result.artifacts == ()
    assert harness.transport.requested_urls == []
    assert harness.files() == before  # nothing deleted, moved or overwritten


# -- F03: semantic consistency, not just hashes ---------------------------------------
FORGERIES = {
    "requested_url": lambda r: r.update(requested_url="https://fixture.invalid/dem_png/14/1/1.png"),
    "effective_url": lambda r: r.update(effective_url="https://fixture.invalid/other.png"),
    "provider": lambda r: r["provider"].update(name="Someone else"),
    "data_name": lambda r: r.update(data_name="forged"),
    "official_page_url": lambda r: r.update(official_page_url="https://fixture.invalid/x"),
    "pipeline_version": lambda r: r["pipeline"].update(version="fixture-9.9"),
    "regions": lambda r: r.update(management_prefectures=["14"]),
    "tile_outside_plan": lambda r: r["tile"].update(x=1, y=1),
    "tile_other_plan_tile": lambda r: r["tile"].update(x=14551),
    "raw_sha256": lambda r: r["source_definition"].update(raw_sha256="0" * 64),
    "source_ref": lambda r: r["source_definition"].update(source_ref="fixture-dem-png-osaka"),
    "definition_revision": lambda r: r["source_definition"].update(definition_revision="x"),
    "snapshot_ref": lambda r: r["effective_configuration"].update(
        snapshot_ref="configurations/missing/effective.json"),
    "effective_sha256": lambda r: r["effective_configuration"].update(sha256="1" * 64),
    "acquired_at_invalid": lambda r: r.update(acquired_at="2026-99-99T99:99:99Z"),
    "acquired_at_feb30": lambda r: r.update(acquired_at="2026-02-30T00:00:00Z"),
    "usage_approval": lambda r: r["usage_snapshot"].update(approval_ref="fixture-other"),
    "size_bytes": lambda r: r.update(size_bytes=r["size_bytes"] + 1),
    "original_version": lambda r: r.update(
        original_version="v1", source_metadata_evidence="https://fixture.invalid/meta"),
    "codex_combined": lambda r: (
        r.update(requested_url="https://fixture.invalid/not-the-requested-tile",
                 acquired_at="2026-99-99T99:99:99Z"),
        r["source_definition"].update(raw_sha256="0" * 64),
        r["effective_configuration"].update(snapshot_ref="configurations/missing/effective.json"),
    ),
}


@pytest.mark.parametrize("name", sorted(FORGERIES))
def test_forged_but_hash_consistent_record_is_rejected(harness, name) -> None:
    first = harness.run()
    forge(harness, first.run_id, first.artifacts[0], FORGERIES[name])
    assert_recovery(harness, first.run_id)


def test_forged_snapshot_is_rejected(harness) -> None:
    first = harness.run()
    eff = harness.api_root / f"records/configurations/{first.run_id}/effective.json"
    doc = json.loads(eff.read_bytes())
    doc["region_codes"] = ["14"]
    eff.write_bytes(json.dumps(doc).encode())
    harness.transport.requested_urls.clear()
    result = harness.run(resume=first.run_id)
    assert result.status is not Status.SUCCESS and harness.transport.requested_urls == []


def test_swapped_artifacts_between_tiles_rejected(harness) -> None:
    first = harness.run()
    a, b = first.artifacts
    pa = evidence(harness, first.run_id, a)[2]
    pb = evidence(harness, first.run_id, b)[2]
    da, db = pa.read_bytes(), pb.read_bytes()
    pa.unlink(), pb.unlink()
    pa.write_bytes(db), pb.write_bytes(da)
    assert_recovery(harness, first.run_id)


# -- F04: marker-side reconciliation ----------------------------------------------------
def test_orphan_marker_without_record_and_artifact(harness) -> None:
    first = harness.run()
    record_path, _, artifact = evidence(harness, first.run_id, first.artifacts[0])
    record_path.unlink()
    shutil.rmtree(artifact.parent)
    assert_recovery(harness, first.run_id)


@pytest.mark.parametrize("remove", ["record", "artifact_dir", "marker"])
def test_any_single_missing_evidence_blocks(harness, remove) -> None:
    first = harness.run()
    record_path, marker_path, artifact = evidence(harness, first.run_id, first.artifacts[1])
    {"record": record_path.unlink, "marker": marker_path.unlink,
     "artifact_dir": lambda: shutil.rmtree(artifact.parent)}[remove]()
    assert_recovery(harness, first.run_id)


def test_extra_marker_pointing_into_run_blocks(harness) -> None:
    first = harness.run()
    _, marker_path, _ = evidence(harness, first.run_id, first.artifacts[0])
    marker = json.loads(marker_path.read_bytes())
    ghost = "99999999-9999-4999-8999-999999999999"
    marker.update(acquisition_id=ghost,
                  record_ref=f"acquisitions/{first.run_id}/{ghost}.json",
                  artifact_ref=f"acquisitions/{first.run_id}/{ghost}/original.png")
    (marker_path.parent / f"{ghost}.json").write_bytes(rec.to_bytes(marker))
    assert_recovery(harness, first.run_id)


def test_unexpected_files_beside_evidence_block(harness) -> None:
    first = harness.run()
    _, _, artifact = evidence(harness, first.run_id, first.artifacts[0])
    (artifact.parent / "extra.bin").write_bytes(b"x")
    assert_recovery(harness, first.run_id)


def test_unparseable_marker_blocks_resume(harness) -> None:
    first = harness.run()
    (harness.api_root / "records/commits/garbage.json").write_bytes(b"{")
    assert_recovery(harness, first.run_id)


# -- F05: no schema retrieval ------------------------------------------------------------
@pytest.mark.parametrize(
    "schema",
    [
        {"$ref": "https://audit.invalid/never-fetch"},
        {"type": "object", "properties": {"a": {"$ref": "https://audit.invalid/x#/a"}}},
        {"$defs": {"x": {"$dynamicRef": "https://audit.invalid/y"}}},
        {"$id": "https://audit.invalid/base", "$ref": "#/$defs/a", "$defs": {"a": {}}},
        {"$ref": "other.schema.json"},
    ],
)
def test_external_schema_reference_never_fetched(tmp_path, no_network, schema) -> None:
    root = tmp_path / "schema"
    path = root / "api/elevation/conf/sources.schema.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(schema))
    fixture = fb.build_tree(tmp_path / "fixture")
    with pytest.raises(ConfigurationError):
        ConfigurationManager(fixture, root).load("api", "elevation", "sources")
    with pytest.raises(ConfigurationError):
        validate_with_schema({}, schema)
    assert no_network == []


def test_registry_alone_never_retrieves(monkeypatch, no_network) -> None:
    """Defence in depth: even without the static $ref check nothing is fetched."""
    from hererisk.common import config

    monkeypatch.setattr(config, "_check_local_refs", lambda schema: None)
    with pytest.raises(ConfigurationError):
        validate_with_schema({}, {"$ref": "https://audit.invalid/never-fetch"})
    assert no_network == []


def test_local_references_still_work() -> None:
    schema = {"$defs": {"n": {"type": "integer"}}, "properties": {"a": {"$ref": "#/$defs/n"}}}
    validate_with_schema({"a": 1}, schema)
    with pytest.raises(ConfigurationError):
        validate_with_schema({"a": "x"}, schema)


def test_external_schema_via_orchestrator_is_invalid_configuration(harness, tmp_path, no_network):
    schema_root = tmp_path / "schema"
    path = schema_root / "api/elevation/conf/sources.schema.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"$ref": "https://audit.invalid/never-fetch"}')
    orch = harness.orchestrator()
    orch._config = ConfigurationManager(harness.fixture_root, schema_root)
    from hererisk.common.orchestrator import DownloadRequest

    result = orch.run_download(DownloadRequest("elevation", ("13",), "fixture-dem-png-tokyo"))
    assert result.error_code == "INVALID_CONFIGURATION" and no_network == []


# -- F06: bounded reads ---------------------------------------------------------------------
def _sparse(path: Path, size: int) -> None:
    path.unlink()
    with path.open("wb") as fh:
        fh.truncate(size)


@pytest.mark.parametrize("which", ["artifact", "record", "marker"])
def test_oversized_committed_evidence_rejected(harness, which, monkeypatch) -> None:
    first = harness.run()
    record_path, marker_path, artifact = evidence(harness, first.run_id, first.artifacts[0])
    target = {"artifact": artifact, "record": record_path, "marker": marker_path}[which]
    _sparse(target, 64 * 1024 * 1024)
    reads: list[int] = []
    real_read = os.read
    def counting_read(fd, n):
        data = real_read(fd, n)
        reads.append(len(data))
        return data

    monkeypatch.setattr(os, "read", counting_read)
    assert_recovery(harness, first.run_id)
    assert sum(reads) < 1024 * 1024  # bytes actually read: never streamed the 64 MiB file


def test_oversized_configuration_rejected(harness) -> None:
    conf = harness.fixture_root / "api/elevation/conf/sources.json"
    _sparse(conf, 64 * 1024 * 1024)
    result = harness.run()
    assert result.error_code == "INVALID_CONFIGURATION" and harness.transport.requested_urls == []


def test_oversized_authorization_rejected(harness) -> None:
    _sparse(harness.fixture_root / "authorization/download.json", 64 * 1024 * 1024)
    assert harness.run().error_code == "APPROVAL_REQUIRED"


# -- F07: container rules end to end -------------------------------------------------------
def _chunk(ctype: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + ctype + body + struct.pack(
        ">I", zlib.crc32(ctype + body) & 0xFFFFFFFF)


def test_bad_ihdr_methods_and_iend_rejected_end_to_end(harness) -> None:
    tile = harness.fixture_root / "tiles/dem_png/14/14550/6450.png"
    raw = tile.read_bytes()
    raw = (raw[:8] + _chunk(b"IHDR", struct.pack(">IIBBBBB", 256, 256, 8, 2, 99, 99, 99))
           + raw[33:-12] + _chunk(b"IEND", b"bad"))
    tile.write_bytes(raw)
    result = harness.run()
    assert result.error_code == "PNG_INVALID"
    assert not list((harness.api_root / "records/commits").glob("*.json"))


# -- F08: nothing secret is persisted --------------------------------------------------------
SECRET_URLS = {
    "query": ("official_page_url", "https://fixture.invalid/official?token=AUDIT_CANARY"),
    "fragment": ("official_page_url", "https://fixture.invalid/official#AUDIT_CANARY"),
    "userinfo": ("official_page_url", "https://user:AUDIT_CANARY@fixture.invalid/official"),
    "terms_query": ("terms_url", "https://fixture.invalid/terms?key=AUDIT_CANARY"),
}


@pytest.mark.parametrize("case", sorted(SECRET_URLS))
def test_secret_url_rejected_before_any_snapshot(harness, case) -> None:
    field, value = SECRET_URLS[case]
    definition = fb.fixture_definition()
    source = definition["sources"]["fixture-dem-png-tokyo"]
    (source["usage"] if field == "terms_url" else source)[field] = value
    harness.rebuild(definition_bytes=fb.dump(definition))
    result = harness.run()
    assert result.status is Status.FAILED and result.error_code == "INVALID_CONFIGURATION"
    assert not (harness.api_root / "records/configurations").exists() or not list(
        (harness.api_root / "records/configurations").iterdir())
    leaked = [p for p in harness.data_root.rglob("*") if p.is_file()
              and b"AUDIT_CANARY" in p.read_bytes()]
    assert leaked == []
    assert "AUDIT_CANARY" not in json.dumps(harness.sink.entries + [result.to_dict()])
    assert harness.transport.requested_urls == []


def test_secret_in_other_source_of_definition_also_rejected(harness) -> None:
    definition = fb.fixture_definition()
    definition["sources"]["fixture-dem-png-osaka"]["official_page_url"] = (
        "https://fixture.invalid/o?token=AUDIT_CANARY")
    harness.rebuild(definition_bytes=fb.dump(definition))
    assert harness.run().error_code == "INVALID_CONFIGURATION"
    assert not any(b"AUDIT_CANARY" in p.read_bytes()
                   for p in harness.data_root.rglob("*") if p.is_file())


# -- F10: hardlink aliases --------------------------------------------------------------------
@pytest.mark.parametrize("which", ["artifact", "record", "marker"])
def test_external_hardlink_alias_blocks_resume(harness, tmp_path, which) -> None:
    first = harness.run()
    record_path, marker_path, artifact = evidence(harness, first.run_id, first.artifacts[0])
    target = {"artifact": artifact, "record": record_path, "marker": marker_path}[which]
    os.link(target, tmp_path / "alias")
    assert_recovery(harness, first.run_id)


# -- F11: bounded accumulation of uncommitted data --------------------------------------------
class BrokenTransport(FixtureTransport):
    def _read(self, handle):
        with handle:
            yield handle.read(1000)
            raise PipelineError("TRANSFER_INTERRUPTED")


def test_pending_parts_are_capped_without_deletion(harness) -> None:
    good = harness.transport
    harness.transport = BrokenTransport(harness.fixture_root / "tiles")
    for _ in range(8):  # fixture policy max_pending_acquisitions = 8
        assert harness.run().error_code == "TRANSFER_INTERRUPTED"
    parts = sorted((harness.api_root / "work/download").rglob("*.part"))
    assert len(parts) == 8
    before = harness.files()
    harness.transport = good
    blocked = harness.run()
    assert blocked.status is Status.BLOCKED and blocked.error_code == "RECOVERY_REQUIRED"
    assert good.requested_urls == []
    after = harness.files()
    assert {k: v for k, v in after.items() if "configurations" not in k} == {
        k: v for k, v in before.items() if "configurations" not in k}
    assert sorted((harness.api_root / "work/download").rglob("*.part")) == parts


# -- F12: fixture data root boundary in the common entry ----------------------------------------
def test_orchestrator_requires_marked_fixture_root(harness, tmp_path) -> None:
    unmarked = tmp_path / "unmarked"
    unmarked.mkdir()
    harness.data_root = unmarked
    result = harness.run()
    assert result.status is Status.FAILED and result.error_code == "INVALID_INPUT"
    assert list(unmarked.iterdir()) == [] and harness.transport.requested_urls == []


def test_orchestrator_rejects_root_inside_config_or_fixture_tree(harness, tmp_path) -> None:
    inside_fixture = harness.fixture_root / "data"
    inside_fixture.mkdir()
    init_fixture_data_root(inside_fixture)
    harness.data_root = inside_fixture
    assert harness.run().error_code == "INVALID_INPUT"
    assert [p.name for p in inside_fixture.iterdir()] == [FIXTURE_ROOT_MARKER]

    schema_root = tmp_path / "schema-root"
    conf = schema_root / "api/elevation/conf"
    conf.mkdir(parents=True)
    shutil.copy(REPO / "api/elevation/conf/sources.schema.json", conf)
    inside_schema = schema_root / "data"
    inside_schema.mkdir()
    init_fixture_data_root(inside_schema)
    orch = harness.orchestrator()
    orch._config = ConfigurationManager(harness.fixture_root, schema_root)
    orch._data_root = inside_schema
    from hererisk.common.orchestrator import DownloadRequest

    result = orch.run_download(DownloadRequest("elevation", ("13",), "fixture-dem-png-tokyo"))
    assert result.error_code == "INVALID_INPUT"
    assert [p.name for p in inside_schema.iterdir()] == [FIXTURE_ROOT_MARKER]


def test_orchestrator_rejects_production_data_root(harness) -> None:
    harness.data_root = Path("/data/hererisk-test")
    assert harness.run().error_code == "INVALID_INPUT"
    assert not Path("/data/hererisk-test").exists()


def test_symlinked_data_root_cannot_redirect_into_repo(harness, tmp_path) -> None:
    link = tmp_path / "sneaky"
    link.symlink_to(REPO / "tests", target_is_directory=True)
    harness.data_root = link
    assert harness.run().error_code == "INVALID_INPUT"
    assert not (REPO / "tests" / "elevation").exists()
