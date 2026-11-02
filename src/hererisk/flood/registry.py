"""Flood data registration (Phase 4-A): ``"flood_sources"`` in the regions file (outside Git).

    {"regions": [ ...address entries, each with its N03 file... ],
     "flood_sources": [
       {"source_id": "local-a31a-<year>-<code>",
        "organization": "<publisher>",
        "title": "洪水浸水想定区域（想定最大規模）<publisher>管理河川",
        "category": "flood_inundation",
        "format": "ksj-a31a-geojson",
        "scenario": "maximum",
        "data_year": "<year>",
        "river_manager_code": "<A31a_203>",
        "service_region": {"prefecture_codes": ["<pref>", ...]},
        "files": [{"path": "a31a/A31a-<yy>_<code>_<nn>_GEOJSON.zip", "distribution_code": "<code>",
                   "ledger_entry": "<Official Source Ledger entry_id>"}, ...]}]}

* ``source_id``: the registration's own identifier (``^[a-z0-9][a-z0-9-]{2,63}$``). The Catalog /
  Identity contract's ledger-assigned ``fl-src-`` identifiers are not adopted
* ``river_manager_code``: the ``A31a_203`` every feature must carry (01-47 都道府県, 81-90 地方整備局等)
* ``distribution_code``: the distribution unit of the ZIP (a prefecture or a 地方整備局); NOT the search area
* ``service_region``: the prefectures where this source is searched. Each needs an N03 file in
  ``regions``; the search area is those N03 polygons, never the distribution code
* ``ledger_entry``: the Official Source Ledger entry of the file (usage terms are read from there)

Adding a prefecture or a source is adding data and one entry; nothing here names a prefecture.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from hererisk.flood import a31a
from hererisk.location.address_provider import AddressDataError
from hererisk.location.address_regions import load_regions, read_registration

SOURCE_KEYS = {"source_id", "organization", "title", "category", "format", "scenario", "data_year",
               "river_manager_code", "service_region", "files"}
FILE_KEYS = {"path", "distribution_code", "ledger_entry"}
CATEGORIES = {"flood_inundation": "洪水浸水想定区域"}
SCENARIO_LABELS = {"maximum": "想定最大規模"}
FORMATS = {a31a.FORMAT_ID}
_ID = re.compile(r"[a-z0-9][a-z0-9-]{2,63}\Z")
_CODE2 = re.compile(r"\d{2}\Z")
_YEAR = re.compile(r"\d{4}\Z")


class FloodRegistrationError(AddressDataError):
    """The flood registration is malformed. Fixed messages (no paths)."""


def _text(v: Any) -> bool:
    return isinstance(v, str) and bool(v.strip())


def load_flood_sources(path: Path) -> list[dict[str, Any]]:
    """[] when the regions file has no ``flood_sources``; otherwise checked entries, file paths
    resolved against the file's directory, in file order."""
    path = Path(path).expanduser()
    doc = read_registration(path)
    if "flood_sources" not in doc:
        return []
    entries = doc["flood_sources"]
    if not isinstance(entries, list) or not entries:
        raise FloodRegistrationError("flood_sources must be a non-empty list")
    region_prefs = {r["prefecture_code"] for r in load_regions(path)}
    out, ids, files_seen = [], set(), set()
    for n, e in enumerate(entries, start=1):
        if not isinstance(e, dict) or set(e) != SOURCE_KEYS:
            raise FloodRegistrationError(f"flood source {n}: keys must be {sorted(SOURCE_KEYS)}")
        sid = e["source_id"]
        if not isinstance(sid, str) or not _ID.match(sid) or sid in ids:
            raise FloodRegistrationError(f"flood source {n}: source_id missing, malformed or duplicated")
        ids.add(sid)
        for key in ("organization", "title"):
            if not _text(e[key]):
                raise FloodRegistrationError(f"flood source {n}: {key} must be a non-empty string")
        if e["category"] not in CATEGORIES:
            raise FloodRegistrationError(f"flood source {n}: category must be one of {sorted(CATEGORIES)}")
        if e["format"] not in FORMATS:
            raise FloodRegistrationError(f"flood source {n}: format must be one of {sorted(FORMATS)}")
        if e["scenario"] not in a31a.SCENARIO_FOLDERS:
            raise FloodRegistrationError(f"flood source {n}: scenario must be one of {sorted(a31a.SCENARIO_FOLDERS)}")
        if not isinstance(e["data_year"], str) or not _YEAR.match(e["data_year"]):
            raise FloodRegistrationError(f"flood source {n}: data_year must be a 4-digit string")
        if not isinstance(e["river_manager_code"], str) or not _CODE2.match(e["river_manager_code"]):
            raise FloodRegistrationError(f"flood source {n}: river_manager_code must be a 2-digit string")
        region = e["service_region"]
        prefs = region.get("prefecture_codes") if isinstance(region, dict) and set(region) == {"prefecture_codes"} else None
        if not isinstance(prefs, list) or not prefs or len(set(prefs)) != len(prefs) \
                or not all(isinstance(p, str) and p in region_prefs for p in prefs):
            raise FloodRegistrationError(f"flood source {n}: service_region.prefecture_codes must list registered "
                                         "regions (each needs an N03 file in \"regions\")")
        if not isinstance(e["files"], list) or not e["files"]:
            raise FloodRegistrationError(f"flood source {n}: files must be a non-empty list")
        files = []
        for f in e["files"]:
            if not isinstance(f, dict) or set(f) != FILE_KEYS or not _text(f["path"]) or not _text(f["ledger_entry"]) \
                    or not isinstance(f["distribution_code"], str) or not _CODE2.match(f["distribution_code"]):
                raise FloodRegistrationError(f"flood source {n}: each file needs {sorted(FILE_KEYS)}")
            p = Path(f["path"]).expanduser()
            p = p if p.is_absolute() else path.parent / p
            codes = a31a.zip_name_codes(p)
            if codes is None or codes["dist"] != f["distribution_code"] or codes["yy"] != e["data_year"][2:]:
                raise FloodRegistrationError(f"flood source {n}: file name does not match distribution_code / data_year")
            if p.name in files_seen:
                raise FloodRegistrationError(f"flood source {n}: the same file is registered twice")
            files_seen.add(p.name)
            files.append({"path": p, "file_name": p.name, "distribution_code": f["distribution_code"],
                          "ledger_entry": f["ledger_entry"]})
        out.append({**{k: e[k] for k in SOURCE_KEYS - {"files", "service_region"}},
                    "service_prefectures": list(prefs), "files": files})
    return out


def registration_view(source: dict[str, Any]) -> dict[str, Any]:
    """Path-free form of one source (the same on the host and in a container)."""
    return {**{k: source[k] for k in sorted(SOURCE_KEYS - {"files", "service_region"})},
            "service_prefectures": source["service_prefectures"],
            "files": [{k: f[k] for k in ("file_name", "distribution_code", "ledger_entry")} for f in source["files"]]}
