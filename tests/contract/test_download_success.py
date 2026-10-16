"""Contract tests: successful fixture download and Record / marker consistency."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import fixture_builder as fb
from hererisk.common.result import Status
from hererisk.elevation.download.download import ElevationDownload, verify_commit
from hererisk.common.storage import ApiDataArea


def test_fixture_download_success(harness) -> None:
    result = harness.run()
    assert result.status is Status.SUCCESS and result.exit_code == 0
    assert result.error_code is None and result.module == "download"
    assert len(result.artifacts) == 2
    assert harness.transport.requested_urls == [
        "https://fixture.invalid/dem_png/14/14550/6450.png",
        "https://fixture.invalid/dem_png/14/14551/6450.png",
    ]

    root = harness.api_root
    for art, (x, y) in zip(result.artifacts, [(14550, 6450), (14551, 6450)]):
        fixture = (harness.fixture_root / f"tiles/dem_png/14/{x}/{y}.png").read_bytes()
        stored = root / f"work/acquisitions/{result.run_id}/{art.acquisition_id}/original.png"
        assert stored.read_bytes() == fixture
        assert art.size_bytes == len(fixture)
        assert art.sha256 == hashlib.sha256(fixture).hexdigest()

        record_bytes = (root / "records" / art.record_ref).read_bytes()
        record = json.loads(record_bytes)
        marker = json.loads((root / f"records/commits/{art.acquisition_id}.json").read_bytes())
        assert marker == {
            "schema_version": "0.1",
            "acquisition_id": art.acquisition_id,
            "record_ref": art.record_ref,
            "record_sha256": hashlib.sha256(record_bytes).hexdigest(),
            "artifact_ref": f"acquisitions/{result.run_id}/{art.acquisition_id}/original.png",
            "artifact_sha256": art.sha256,
        }
        assert record["run_id"] == result.run_id
        assert record["acquisition_id"] == art.acquisition_id == art.artifact_id
        assert record["tile"] == {"z": 14, "x": x, "y": y}
        assert record["sha256"] == art.sha256 and record["size_bytes"] == art.size_bytes
        assert record["requested_url"] == record["effective_url"]
        assert record["management_prefectures"] == ["13"]
        assert record["original_version"] is None
        assert record["data_reference_date"] is None
        assert record["source_metadata_evidence"] is None
        assert record["usage_snapshot"]["approval_ref"].startswith("fixture-")
        assert record["pipeline"] == {"id": "elevation-download", "version": "fixture-0.1"}

        # Configuration snapshot binding.
        snap_dir = root / f"records/configurations/{result.run_id}"
        effective = (snap_dir / "effective.json").read_bytes()
        assert record["effective_configuration"] == {
            "snapshot_ref": f"configurations/{result.run_id}/effective.json",
            "sha256": hashlib.sha256(effective).hexdigest(),
        }
        source_raw = (snap_dir / "source.json").read_bytes()
        assert source_raw == (harness.fixture_root / "api/elevation/conf/sources.json").read_bytes()
        assert record["source_definition"]["raw_sha256"] == hashlib.sha256(source_raw).hexdigest()
        assert json.loads(effective)["execution_context"] == "fixture"

        verify_commit(ApiDataArea(harness.data_root, "elevation"), result.run_id, art.acquisition_id)

    # No uncommitted leftovers after success.
    assert list((root / "work/download").rglob("*.part")) == []


def test_injected_ids_and_clock_propagate(harness) -> None:
    ids = iter(["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2"])
    module = ElevationDownload(
        harness.transport,
        id_factory=lambda: next(ids),
        clock=lambda: datetime(2026, 10, 17, 1, 2, 3, tzinfo=timezone.utc),
    )
    result = harness.run(module=module)
    assert [a.acquisition_id for a in result.artifacts] == [
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2"]
    record = json.loads((harness.api_root / "records" / result.artifacts[0].record_ref).read_text())
    assert record["acquired_at"] == "2026-10-17T01:02:03Z"


def test_non_tokyo_region_uses_same_path(harness) -> None:
    result = harness.run(regions=("27",), source="fixture-dem-png-osaka")
    assert result.status is Status.SUCCESS and len(result.artifacts) == 1
    record = json.loads((harness.api_root / "records" / result.artifacts[0].record_ref).read_text())
    assert record["management_prefectures"] == ["27"]


def test_other_region_variant_without_tokyo(harness) -> None:
    # A definition where only Hokkaido (01) is targeted.
    harness.rebuild({"fixture-dem-png-hokkaido": {"regions": ["01"], "tiles": [(14600, 5900)]}})
    result = harness.run(regions=("01",), source="fixture-dem-png-hokkaido")
    assert result.status is Status.SUCCESS
    assert harness.run(regions=("13",), source="fixture-dem-png-hokkaido").error_code == (
        "TARGET_UNCONFIGURED")


def test_no_code_special_cases_region_13() -> None:
    from pathlib import Path

    src = Path(fb.REPO_ROOT / "src")
    for path in src.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert '"13"' not in text and "'13'" not in text, path


def test_logs_are_structured_and_safe(harness) -> None:
    result = harness.run()
    entries = harness.sink.entries
    assert entries and all(e["run_id"] == result.run_id for e in entries)
    assert {e["level"] for e in entries} <= {"INFO", "WARNING", "ERROR"}
    dump = json.dumps(entries)
    assert "fixture.invalid" not in dump and str(harness.data_root) not in dump
    assert "14550" not in dump  # no tile/location detail in logs
