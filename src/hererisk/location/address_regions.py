"""Address regions file (Phase 3-E): which prefectures' data the address provider loads.

A local JSON file outside Git (it holds local paths), given with ``--address-regions``:

    {"regions": [
      {"prefecture_code": "<JIS 2-digit>", "address_isj": "~/hererisk-data/isj/<pref>000-19.0b.zip",
       "address_n03": "~/hererisk-data/n03/N03-20260101_<pref>_GML.zip"},
      {"prefecture_code": "<another>", "address_isj": "...", "address_n03": "..."}]}

Adding a prefecture means adding one entry; the address logic has no per-prefecture code.
Relative paths are resolved against the file's directory. Each data file is checked against its
``prefecture_code`` when it is loaded (file name and contents).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from hererisk.common.config import ConfigurationError, parse_strict_json
from hererisk.location.address_provider import AddressDataError

MAX_REGIONS_FILE_BYTES = 64 * 1024
_PREF = re.compile(r"(0[1-9]|[1-3][0-9]|4[0-7])\Z")
KEYS = {"prefecture_code", "address_isj", "address_n03"}


def load_regions(path: Path) -> list[dict[str, Any]]:
    """Returns [{"prefecture_code", "address_isj": Path, "address_n03": Path}], in file order."""
    path = Path(path).expanduser()
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AddressDataError("regions file unavailable") from exc
    if len(raw) > MAX_REGIONS_FILE_BYTES:
        raise AddressDataError("regions file too large")
    try:
        doc = parse_strict_json(raw)        # UTF-8, duplicate keys rejected
    except ConfigurationError as exc:
        raise AddressDataError("regions file is not valid JSON") from exc
    if not isinstance(doc, dict) or set(doc) != {"regions"} or not isinstance(doc["regions"], list) or not doc["regions"]:
        raise AddressDataError('regions file must be {"regions": [ ... ]} with at least one region')
    out, seen = [], set()
    for n, r in enumerate(doc["regions"], start=1):
        if not isinstance(r, dict) or set(r) != KEYS:
            raise AddressDataError(f"region {n}: keys must be {sorted(KEYS)}")
        code = r["prefecture_code"]
        if not isinstance(code, str) or not _PREF.match(code):
            raise AddressDataError(f"region {n}: prefecture_code must be a 2-digit JIS code (01-47)")
        if code in seen:
            raise AddressDataError(f"region {n}: prefecture {code} registered twice")
        seen.add(code)
        files = {}
        for key in ("address_isj", "address_n03"):
            if not isinstance(r[key], str) or not r[key]:
                raise AddressDataError(f"region {n}: {key} must be a path")
            p = Path(r[key]).expanduser()
            files[key] = p if p.is_absolute() else path.parent / p
        out.append({"prefecture_code": code, **files})
    return out
