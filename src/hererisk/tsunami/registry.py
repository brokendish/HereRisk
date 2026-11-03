"""Tsunami data registration (Phase 4-M): ``"tsunami_sources"`` in the regions file (outside Git).

    {"regions": [ ...address entries, each with its N03 file... ],
     "tsunami_sources": [
       {"source_id": "local-a40-<year>-<pref>",
        "organization": "<prefecture that made the assumption>",
        "title": "津波浸水想定（<prefecture>）",
        "format": "ksj-a40-geojson",
        "data_year": "<year>",
        "prefecture_code": "<A40_002>",
        "service_region": {"prefecture_codes": ["<pref>", ...]},
        "files": [{"path": "a40/A40-<yy>_<pref>_GML.zip", "ledger_entry": "<Official Source Ledger entry_id>"}]}]}

* ``prefecture_code``: the ``A40_002`` every feature must carry, and the code in the file name
* ``service_region``: where this source is searched (N03 polygons of those prefectures, each needs an
  N03 file in ``regions``). Being searched is not having an assessed extent: A40 states none
* ``ledger_entry``: the Official Source Ledger entry of the file (usage terms are read from there)

Adding a prefecture is adding data and one entry; nothing here names a prefecture.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from hererisk.location.address_regions import load_regions, read_registration
from hererisk.tsunami import a40
from hererisk.tsunami.errors import TsunamiRegistrationError

SOURCE_KEYS = {"source_id", "organization", "title", "format", "data_year", "prefecture_code", "service_region", "files"}
FILE_KEYS = {"path", "ledger_entry"}
CATEGORY, CATEGORY_LABEL = "tsunami_inundation", "津波浸水想定"
DEFAULT_LEDGER = Path(__file__).resolve().parents[3] / "docs" / "data-sources" / "official-source-ledger.json"
_ID = re.compile(r"[a-z0-9][a-z0-9-]{2,63}\Z")
_PREF = re.compile(r"(0[1-9]|[1-3]\d|4[0-7])\Z")
_YEAR = re.compile(r"\d{4}\Z")


def _text(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def load_tsunami_sources(path: Path) -> list[dict[str, Any]]:
    """[] when the regions file has no ``tsunami_sources``; otherwise checked entries, file paths
    resolved against the file's directory, in file order."""
    path = Path(path).expanduser()
    doc = read_registration(path)
    if "tsunami_sources" not in doc:
        return []
    entries = doc["tsunami_sources"]
    if not isinstance(entries, list) or not entries:
        raise TsunamiRegistrationError("tsunami_sources must be a non-empty list")
    region_prefs = {r["prefecture_code"] for r in load_regions(path)}
    out, ids, files_seen = [], set(), set()
    for n, e in enumerate(entries, start=1):
        if not isinstance(e, dict) or set(e) != SOURCE_KEYS:
            raise TsunamiRegistrationError(f"tsunami source {n}: keys must be {sorted(SOURCE_KEYS)}")
        sid = e["source_id"]
        if not isinstance(sid, str) or not _ID.match(sid) or sid in ids:
            raise TsunamiRegistrationError(f"tsunami source {n}: source_id missing, malformed or duplicated")
        ids.add(sid)
        for key in ("organization", "title"):
            if not _text(e[key]):
                raise TsunamiRegistrationError(f"tsunami source {n}: {key} must be a non-empty string")
        if e["format"] != a40.FORMAT_ID:
            raise TsunamiRegistrationError(f"tsunami source {n}: format must be {a40.FORMAT_ID}")
        if not isinstance(e["data_year"], str) or not _YEAR.match(e["data_year"]):
            raise TsunamiRegistrationError(f"tsunami source {n}: data_year must be a 4-digit string")
        if not isinstance(e["prefecture_code"], str) or not _PREF.match(e["prefecture_code"]):
            raise TsunamiRegistrationError(f"tsunami source {n}: prefecture_code must be a 2-digit JIS code")
        region = e["service_region"]
        prefs = region.get("prefecture_codes") if isinstance(region, dict) and set(region) == {"prefecture_codes"} else None
        if not isinstance(prefs, list) or not prefs or len(set(prefs)) != len(prefs) \
                or not all(isinstance(p, str) and p in region_prefs for p in prefs):
            raise TsunamiRegistrationError(f"tsunami source {n}: service_region.prefecture_codes must list registered "
                                           "regions (each needs an N03 file in \"regions\")")
        if not isinstance(e["files"], list) or not e["files"]:
            raise TsunamiRegistrationError(f"tsunami source {n}: files must be a non-empty list")
        files = []
        for f in e["files"]:
            if not isinstance(f, dict) or set(f) != FILE_KEYS or not _text(f["path"]) or not _text(f["ledger_entry"]):
                raise TsunamiRegistrationError(f"tsunami source {n}: each file needs {sorted(FILE_KEYS)}")
            p = Path(f["path"]).expanduser()
            p = p if p.is_absolute() else path.parent / p
            codes = a40.zip_name_codes(p)
            if codes is None or codes["pref"] != e["prefecture_code"] or codes["yy"] != e["data_year"][2:]:
                raise TsunamiRegistrationError(f"tsunami source {n}: file name does not match prefecture_code / data_year")
            if p.name in files_seen:
                raise TsunamiRegistrationError(f"tsunami source {n}: the same file is registered twice")
            files_seen.add(p.name)
            files.append({"path": p, "file_name": p.name, "ledger_entry": f["ledger_entry"]})
        out.append({**{k: e[k] for k in SOURCE_KEYS - {"files", "service_region"}},
                    "service_prefectures": list(prefs), "files": files})
    return out


def load_ledger(path: Path = DEFAULT_LEDGER) -> dict[str, dict[str, Any]]:
    """Official Source Ledger entries by entry_id ({} when unreadable: usage terms then stay unconfirmed)."""
    try:
        return {e.get("entry_id"): e for e in json.loads(Path(path).read_text(encoding="utf-8"))["entries"]}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def registration_view(source: dict[str, Any]) -> dict[str, Any]:
    """Path-free form of one source (the same on the host and in a container)."""
    return {**{k: source[k] for k in sorted(SOURCE_KEYS - {"files", "service_region"})},
            "service_prefectures": source["service_prefectures"],
            "files": [{k: f[k] for k in ("file_name", "ledger_entry")} for f in source["files"]]}
