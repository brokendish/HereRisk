"""Data Inventory (Phase 3-F): a read-only list of the data files HereRisk is configured to use.

Nothing here is a source of truth of its own. Every column is read from its owner:

    regions / local files     the regions file (``--address-regions``)
    source and usage terms    the Official Source Ledger (docs/data-sources/official-source-ledger.json)
    recorded SHA-256          the Ledger ``download_verification`` (an acquisition record)
    file existence / size     measured now (``os.stat``); SHA-256 only when asked (``measure_hashes``)
    publication               not read in this MVP (address data has no Dataset Registry entry)

Unknown stays unknown: a missing record is shown as ``unknown`` / ``not_recorded``, never as approved.
Reading a ZIP's member list (central directory) is the only access to file contents in a normal run.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any

from hererisk.location.address_regions import load_regions

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LEDGER = REPO_ROOT / "docs" / "data-sources" / "official-source-ledger.json"

# JIS X 0401, index + 1 = prefecture code
PREFECTURES = ["北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県", "茨城県", "栃木県", "群馬県",
               "埼玉県", "千葉県", "東京都", "神奈川県", "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
               "岐阜県", "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
               "鳥取県", "島根県", "岡山県", "広島県", "山口県", "徳島県", "香川県", "愛媛県", "高知県", "福岡県",
               "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県"]

# kind -> how to read the version from the ZIP member list, and the display names
KINDS = {
    "address_isj": {"category": "address", "category_label": "住所",
                    "title": "大字・町丁目レベル位置参照情報", "organization": "国土交通省",
                    "member": re.compile(r"(?:^|/)(?:\d{5}-(?P<edition>\d+\.\d+[a-z]?)/)?(?P<pref>\d{2})_(?P<year>\d{4})\.csv\Z"),
                    "id": "address-isj-{pref}", "edition_id": "mlit-isj-oaza-{year}-{pref}"},
    "address_n03": {"category": "administrative_boundary", "category_label": "行政区域",
                    "title": "国土数値情報（行政区域データ）N03", "organization": "国土交通省",
                    "member": re.compile(r"(?:^|/)N03-(?P<date>(?P<year>\d{4})\d{4})_(?P<pref>\d{2})\.geojson\Z"),
                    "id": "address-n03-{pref}", "edition_id": "ksj-n03-{year}-{pref}"},
}

USAGE_LABELS = {"approved": "承認済み", "review_required": "要確認", "prohibited": "禁止", "unverified": "未確認",
                "unknown": "未確認（台帳に記載なし）"}
FILE_LABELS = {"present": "ファイルあり", "missing": "ファイルなし", "unreadable": "読み取れない", "unknown": "未確認"}


def prefecture_name(code: str) -> str:
    n = int(code)
    return PREFECTURES[n - 1] if 1 <= n <= len(PREFECTURES) else "unknown"


def load_ledger(path: Path) -> list[dict[str, Any]]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))["entries"]
    except (OSError, ValueError, KeyError):
        return []


def _ledger_entry(entries: list[dict[str, Any]], file_name: str, pref: str) -> dict[str, Any] | None:
    for e in entries:
        d = e.get("distribution") or {}
        if d.get("file_name") == file_name and pref in (d.get("region_codes") or []):
            return e
    return None


def _file_state(path: Path) -> tuple[str, int | None]:
    try:
        st = path.stat()
    except FileNotFoundError:
        return "missing", None
    except OSError:
        return "unreadable", None
    if not path.is_file() or not os.access(path, os.R_OK):
        return "unreadable", st.st_size
    return "present", st.st_size


def _version(kind: str, path: Path) -> dict[str, Any]:
    """Version from the ZIP member list (or the CSV file name); never the data rows."""
    rule = KINDS[kind]["member"]
    try:
        names = zipfile.ZipFile(path).namelist() if zipfile.is_zipfile(path) else [path.name]
    except (OSError, zipfile.BadZipFile):
        return {"status": "unreadable"}
    hits = [m for m in (rule.search(n) for n in names) if m]
    if len(hits) != 1:
        return {"status": "not_found"}
    g = hits[0].groupdict()
    out = {"status": "read", "member": hits[0].group(0).lstrip("/"), "year": g["year"], "prefecture_code_in_file": g["pref"]}
    if g.get("edition"):
        out["edition"] = g["edition"]
    if g.get("date"):
        out["reference_date"] = f"{g['date'][:4]}-{g['date'][4:6]}-{g['date'][6:]}"
    return out


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def build_inventory(regions_file: Path, ledger_file: Path = DEFAULT_LEDGER, *, measure_hashes: bool = False) -> dict[str, Any]:
    regions = load_regions(regions_file)
    ledger = load_ledger(ledger_file)
    items = []
    for region in regions:
        pref = region["prefecture_code"]
        for kind in ("address_isj", "address_n03"):
            path: Path = region[kind]
            meta = KINDS[kind]
            file_state, size = _file_state(path)
            version = _version(kind, path) if file_state == "present" else {"status": "unknown"}
            year = version.get("year")
            entry = _ledger_entry(ledger, path.name, pref)
            usage = (entry or {}).get("usage_terms") or {}
            usage_status = usage.get("status", "unknown")
            recorded = ((entry or {}).get("availability") or {}).get("download_verification") or {}
            measured = sha256_file(path) if measure_hashes and file_state == "present" else None
            dataset = (entry or {}).get("dataset") or {}
            items.append({
                # stable: one registration per prefecture and kind; the edition is a separate column
                "data_id": meta["id"].format(pref=pref),
                "edition_id": meta["edition_id"].format(year=year, pref=pref) if year else "unknown",
                "name": f"{prefecture_name(pref)} / {meta['category_label']}（{meta['title']}）",
                "prefecture_code": pref,
                "prefecture_name": prefecture_name(pref),
                "category": meta["category"],
                "category_label": meta["category_label"],
                "title": meta["title"],
                "organization": meta["organization"],
                "year": year or "unknown",
                "version": version,
                "file": {"name": path.name, "path": str(path), "state": file_state, "size_bytes": size},
                "sha256": {"recorded": recorded.get("sha256"),
                           "recorded_source": f"official-source-ledger: {entry['entry_id']}" if recorded.get("sha256") else None,
                           "measured": measured,
                           "match": None if not (measured and recorded.get("sha256")) else measured == recorded["sha256"]},
                "prefecture_code_matches_file": None if "prefecture_code_in_file" not in version
                                                else version["prefecture_code_in_file"] == pref,
                "api_connection": {"configured": True, "via": "regions file (Location API --address-regions)",
                                   "running": "unknown"},
                "ledger": {"entry_id": entry["entry_id"] if entry else None,
                           "data_year": dataset.get("data_year"),
                           "year_matches_file": None if not (year and dataset.get("data_year")) else year == dataset["data_year"],
                           "usage_terms": usage_status,
                           "approval_ref": usage.get("approval_ref"),
                           "open_issues": usage.get("open_issues", [])},
                # public approval only from an OWNER approval record referenced by the Ledger
                "public_approval": "approved" if usage_status == "approved" and usage.get("approval_ref") else "unconfirmed",
                "publication": {"registry": "not_referenced",
                                "note": "address data is not published through a Dataset Registry in this MVP"},
            })
    return {"inventory_version": "0.1", "regions_file": str(Path(regions_file).expanduser()),
            "ledger_file": str(ledger_file), "hashes_measured": measure_hashes, "items": items}


def summary_line(item: dict[str, Any]) -> str:
    year = f"{item['year']}年版" if item["year"] != "unknown" else "年度unknown"
    usage = USAGE_LABELS.get(item["ledger"]["usage_terms"], item["ledger"]["usage_terms"])
    return " / ".join([item["prefecture_name"], item["category_label"], year, FILE_LABELS[item["file"]["state"]],
                       "API接続設定あり" if item["api_connection"]["configured"] else "API接続設定なし",
                       f"利用条件: {usage}",
                       "公開承認済み" if item["public_approval"] == "approved" else "公開承認未確認"])
