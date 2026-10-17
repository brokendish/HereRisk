"""Builds fixture trees for the elevation Download fixture MVP.

The committed tree ``tests/fixtures/elevation-fixture`` is produced by
``python tests/fixture_builder.py`` and tests build variants in temp dirs with
the same functions. Fixture values are fixture-only: every approval/review id
has the ``fixture-`` prefix, URLs use the reserved ``fixture.invalid`` host and
no value here is an approval of the production Source Definition.

Tile PNGs are synthetic 256x256 RGB images in the GSI elevation PNG encoding
(value = (R*65536 + G*256 + B) * 0.01 m, no-data = (128,0,0)). They contain no
real GSI data.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMITTED_ROOT = REPO_ROOT / "tests" / "fixtures" / "elevation-fixture"
PRODUCTION_SOURCES = REPO_ROOT / "api" / "elevation" / "conf" / "sources.json"

ZOOM = 14
FIXTURE_SOURCES: dict[str, dict[str, Any]] = {
    # region "13" (Tokyo) and "27" (Osaka): identical code path, no special-casing.
    "fixture-dem-png-tokyo": {"regions": ["13"], "tiles": [(14550, 6450), (14551, 6450)]},
    "fixture-dem-png-osaka": {"regions": ["27"], "tiles": [(14370, 6495)]},
}


def _chunk(ctype: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + ctype + body + struct.pack(
        ">I", zlib.crc32(ctype + body) & 0xFFFFFFFF
    )


def make_png(seed: int, width: int = 256, height: int = 256) -> bytes:
    """Deterministic RGB PNG; includes 0 m, negative-free values and no-data pixels."""
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # filter: none
        for x in range(width):
            if (x + y + seed) % 97 == 0:
                rows += bytes((128, 0, 0))  # no-data
                continue
            value = (seed * 1000 + x * 37 + y * 11) % 400000  # 0.00 .. 3999.99 m
            rows += bytes(((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + _chunk(b"IEND", b"")
    )


def fixture_source(source_ref: str, tiles: list[tuple[int, int]] | None) -> dict[str, Any]:
    return {
        "provider": {"id": "fixture", "name": "Fixture provider (not GSI data)"},
        "name": f"Fixture elevation PNG ({source_ref})",
        "official_page_url": "https://fixture.invalid/official",
        "documentation_checked_on": "2026-10-17",
        "acquisition": {
            "method": "xyz_png",
            "url_template": "https://fixture.invalid/dem_png/{z}/{x}/{y}.png",
            "zoom": ZOOM,
            "tiles": None if tiles is None else [{"x": x, "y": y} for x, y in tiles],
        },
        "vertical_reference": "fixture-vertical-reference",
        "usage": {
            "terms_url": "https://fixture.invalid/terms",
            "attribution_text": "Fixture attribution (not a real data source)",
            "review_ref": "fixture-terms-review",
        },
        "pipeline": {"id": "elevation-download", "version": "fixture-0.1"},
        "approval_ref": "fixture-owner-approval",
    }


def fixture_definition(sources: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """47-prefecture definition built from the production one (names/codes kept)."""
    sources = FIXTURE_SOURCES if sources is None else sources
    production = json.loads(PRODUCTION_SOURCES.read_text(encoding="utf-8"))
    prefectures = {
        code: {"name": entry["name"], "targeted": False, "source_refs": []}
        for code, entry in production["prefectures"].items()
    }
    for ref, spec in sources.items():
        for code in spec["regions"]:
            prefectures[code]["targeted"] = True
            prefectures[code]["source_refs"].append(ref)
    return {
        "$schema": "./sources.schema.json",
        "schema_version": "0.1",
        "definition_revision": "fixture-1",
        "hazard": "elevation",
        "sources": {ref: fixture_source(ref, spec["tiles"]) for ref, spec in sources.items()},
        "prefectures": prefectures,
    }


def dump(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def authorization(definition_bytes: bytes, sources: dict[str, dict[str, Any]],
                  operation: str = "download") -> dict[str, Any]:
    doc = {
        "authorization_ref": f"fixture-auth-elevation-{operation}",
        "execution_context": "fixture",
        "api_id": "elevation",
        "operation": operation,
        "grants": [
            {
                "source_ref": ref,
                "region_codes": spec["regions"],
                "definition_raw_sha256": hashlib.sha256(definition_bytes).hexdigest(),
            }
            for ref, spec in sources.items()
        ],
        "policy": {
            "policy_id": "fixture-download-policy",
            "version": "0.1",
            "max_tile_bytes": 1048576,
            "max_tiles_per_request": 16,
            "max_pending_acquisitions": 8,
        },
    }
    if operation != "download":
        del doc["policy"]  # the acquisition safety policy belongs to download only
    if operation == "publish":
        # Fixture-only publication terms: not a licence for any real data.
        doc["publication"] = {"license": "Fixture licence (test data only, not redistributable)",
                              "attribution_url": "https://fixture.invalid/terms"}
    return doc


def build_tree(
    root: Path,
    sources: dict[str, dict[str, Any]] | None = None,
    *,
    definition_bytes: bytes | None = None,
) -> Path:
    """Write ``api/elevation/conf/sources.json``, ``authorization/download.json``, tiles."""
    sources = FIXTURE_SOURCES if sources is None else sources
    if definition_bytes is None:
        definition_bytes = dump(fixture_definition(sources))
    conf = root / "api" / "elevation" / "conf"
    conf.mkdir(parents=True, exist_ok=True)
    (conf / "sources.json").write_bytes(definition_bytes)
    auth_dir = root / "authorization"
    auth_dir.mkdir(parents=True, exist_ok=True)
    for operation in ("download", "normalize", "validate", "publish"):
        (auth_dir / f"{operation}.json").write_bytes(
            dump(authorization(definition_bytes, sources, operation)))
    for seed, (x, y) in enumerate(
        sorted({t for spec in sources.values() for t in (spec["tiles"] or [])})
    ):
        tile = root / "tiles" / "dem_png" / str(ZOOM) / str(x) / f"{y}.png"
        tile.parent.mkdir(parents=True, exist_ok=True)
        tile.write_bytes(make_png(seed + 1))
    return root


if __name__ == "__main__":
    build_tree(COMMITTED_ROOT)
    sys.stdout.write(f"fixture tree written: {COMMITTED_ROOT.relative_to(REPO_ROOT)}\n")
