"""Unit tests: common Configuration Manager."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import fixture_builder as fb
from hererisk.common.config import (
    PREFECTURE_CODES,
    ConfigurationError,
    ConfigurationManager,
    parse_strict_json,
    sha256_hex,
)

REPO = fb.REPO_ROOT


def manager(root: Path) -> ConfigurationManager:
    return ConfigurationManager(definition_root=root, schema_root=REPO)


def write_definition(root: Path, raw: bytes) -> None:
    conf = root / "api" / "elevation" / "conf"
    conf.mkdir(parents=True, exist_ok=True)
    (conf / "sources.json").write_bytes(raw)


def test_production_definition_47_prefectures_valid() -> None:
    snap = manager(REPO).load("api", "elevation", "sources")
    prefectures = snap.data["prefectures"]
    assert tuple(sorted(prefectures)) == PREFECTURE_CODES
    targeted = [c for c, r in prefectures.items() if r["targeted"]]
    assert targeted == ["13"]
    for code, region in prefectures.items():
        assert region["name"]
        if code != "13":
            assert region["source_refs"] == ()
    assert snap.raw_sha256 == sha256_hex((REPO / "api/elevation/conf/sources.json").read_bytes())
    # Structurally valid but not executable: approvals are null.
    source = snap.data["sources"]["gsi-dem10b-candidate"]
    assert source["approval_ref"] is None and source["acquisition"]["tiles"] is None


def test_fixture_definition_passes_production_schema(tmp_path: Path) -> None:
    root = fb.build_tree(tmp_path)
    snap = manager(root).load("api", "elevation", "sources")
    assert snap.data["prefectures"]["27"]["targeted"] is True


def test_snapshot_is_immutable(tmp_path: Path) -> None:
    snap = manager(fb.build_tree(tmp_path)).load("api", "elevation", "sources")
    with pytest.raises(TypeError):
        snap.data["prefectures"]["01"] = {}  # type: ignore[index]
    with pytest.raises(AttributeError):
        snap.raw_sha256 = "x"  # type: ignore[misc]
    assert isinstance(snap.data["sources"]["fixture-dem-png-tokyo"]["acquisition"]["tiles"], tuple)


@pytest.mark.parametrize(
    "raw",
    [
        b'{"a": 1,',  # syntax
        b'{"a": 1, "a": 2}',  # duplicate key
        b'{"a": NaN}',  # non-standard constant
        b"\xef\xbb\xbf{}",  # BOM
        b"\xff\xfe",  # not UTF-8
    ],
)
def test_strict_json_rejects(raw: bytes) -> None:
    with pytest.raises(ConfigurationError):
        parse_strict_json(raw)


def test_duplicate_key_in_definition_rejected(tmp_path: Path) -> None:
    raw = fb.dump(fb.fixture_definition()).replace(
        b'"hazard": "elevation",', b'"hazard": "elevation",\n  "hazard": "elevation",'
    )
    write_definition(tmp_path, raw)
    with pytest.raises(ConfigurationError, match="duplicate"):
        manager(tmp_path).load("api", "elevation", "sources")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(unknown_key=1),
        lambda d: d["prefectures"].pop("01"),
        lambda d: d["prefectures"]["13"].update(name="東京"),
        lambda d: d["prefectures"]["01"].update(targeted=True),  # targeted w/o refs
        lambda d: d["sources"]["fixture-dem-png-tokyo"]["acquisition"].update(tiles=[]),
        lambda d: d["sources"]["fixture-dem-png-tokyo"].update(approval_ref=None, pipeline=None)
        or d["sources"]["fixture-dem-png-tokyo"].update(approval_ref="fixture-x"),
    ],
)
def test_schema_violations_rejected(tmp_path: Path, mutate) -> None:
    definition = fb.fixture_definition()
    mutate(definition)
    write_definition(tmp_path, fb.dump(definition))
    with pytest.raises(ConfigurationError):
        manager(tmp_path).load("api", "elevation", "sources")


def test_region_reference_to_unknown_source_rejected(tmp_path: Path) -> None:
    definition = fb.fixture_definition()
    definition["prefectures"]["14"].update(targeted=True, source_refs=["no-such-source"])
    write_definition(tmp_path, fb.dump(definition))
    with pytest.raises(ConfigurationError, match="unknown source"):
        manager(tmp_path).load("api", "elevation", "sources")


@pytest.mark.parametrize(
    "ident",
    [("api", "flood", "sources"), ("common", "elevation", "sources"), ("api", "../x", "sources"),
     ("api", "elevation", "settings")],
)
def test_unknown_or_malformed_identifier_rejected(ident) -> None:
    with pytest.raises(ConfigurationError):
        manager(REPO).load(*ident)


def test_missing_file_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        manager(tmp_path).load("api", "elevation", "sources")


def test_production_files_untouched_by_loading() -> None:
    path = REPO / "api/elevation/conf/sources.json"
    before = path.read_bytes()
    manager(REPO).load("api", "elevation", "sources")
    assert path.read_bytes() == before
    json.loads(before)  # still plain JSON
