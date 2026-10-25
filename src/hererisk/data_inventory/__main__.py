"""python -m hererisk.data_inventory --regions <regions.json> [--format table|json] [--hash] [--serve]

* ``--format table`` (default) / ``json``: print the inventory
* ``--hash``: also measure SHA-256 of every present file (reads the whole files)
* ``--serve [--port 8090]``: read-only HTML page on 127.0.0.1 (hererisk.data_inventory.web)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from hererisk.data_inventory.inventory import DEFAULT_LEDGER, USAGE_LABELS, FILE_LABELS, build_inventory, summary_line
from hererisk.location.address_provider import AddressDataError


def table(inv: dict) -> str:
    cols = [("データID", lambda i: i["data_id"]), ("都道府県", lambda i: f"{i['prefecture_code']} {i['prefecture_name']}"),
            ("分類", lambda i: i["category_label"]),
            ("年度・版", lambda i: " ".join(v for v in (i["year"], i["version"].get("edition"), i["version"].get("reference_date")) if v)),
            ("ファイル", lambda i: i["file"]["name"]), ("状態", lambda i: FILE_LABELS[i["file"]["state"]]),
            ("サイズ", lambda i: "-" if i["file"]["size_bytes"] is None else f"{i['file']['size_bytes']:,}"),
            ("SHA-256（記録）", lambda i: (i["sha256"]["recorded"] or "記録なし")[:12]),
            ("SHA-256（実測）", lambda i: (i["sha256"]["measured"] or "未計測")[:12]),
            ("利用条件", lambda i: USAGE_LABELS.get(i["ledger"]["usage_terms"], i["ledger"]["usage_terms"])),
            ("公開承認", lambda i: "承認済み" if i["public_approval"] == "approved" else "未確認")]
    rows = [[h for h, _ in cols]] + [[f(i) for _, f in cols] for i in inv["items"]]
    width = [max(_w(r[c]) for r in rows) for c in range(len(cols))]
    lines = ["  ".join(cell + " " * (width[c] - _w(cell)) for c, cell in enumerate(r)) for r in rows]
    lines.insert(1, "  ".join("-" * w for w in width))
    return "\n".join(lines + [""] + [summary_line(i) for i in inv["items"]])


def _w(s: str) -> int:   # display width: CJK characters take two columns
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in s)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m hererisk.data_inventory")
    parser.add_argument("--regions", type=Path, required=True, help="regions file (same as --address-regions)")
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER, help="Official Source Ledger JSON")
    parser.add_argument("--format", choices=("table", "json"), default="table")
    parser.add_argument("--hash", action="store_true", help="measure SHA-256 of present files (slow for large files)")
    parser.add_argument("--serve", action="store_true", help="serve a read-only HTML page on 127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args(argv)
    if args.serve:
        from hererisk.data_inventory.web import serve
        return serve(args.regions, args.ledger, args.port)
    try:
        inv = build_inventory(args.regions, args.ledger, measure_hashes=args.hash)
    except AddressDataError as exc:
        sys.stderr.write(f"data_inventory: {exc}\n")
        return 2
    print(json.dumps(inv, ensure_ascii=False, indent=1) if args.format == "json" else table(inv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
