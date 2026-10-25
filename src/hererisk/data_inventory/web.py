"""Read-only Data Inventory page on 127.0.0.1 (Phase 3-F).

GET /                -> HTML table (built from the same build_inventory() as the CLI)
GET /inventory.json  -> the same inventory as JSON
Anything else -> 404; any method other than GET -> 405. There is no parameter: the page cannot
read a path chosen by the browser, and nothing can be downloaded, updated, deleted or published.
The inventory is rebuilt on every request (file states are measured now; no SHA-256 is computed).
"""

from __future__ import annotations

import html
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from hererisk.data_inventory.inventory import FILE_LABELS, USAGE_LABELS, build_inventory, summary_line


def render(inv: dict[str, Any]) -> str:
    e = html.escape
    rows = []
    for i in inv["items"]:
        usage = USAGE_LABELS.get(i["ledger"]["usage_terms"], i["ledger"]["usage_terms"])
        approval = "承認済み" if i["public_approval"] == "approved" else "未確認"
        version = " ".join(v for v in (i["year"], i["version"].get("edition"), i["version"].get("reference_date")) if v)
        detail = json.dumps({k: i[k] for k in ("data_id", "edition_id", "version", "file", "sha256", "ledger", "api_connection", "publication",
                                              "prefecture_code_matches_file")}, ensure_ascii=False, indent=1)
        rows.append(
            f"<tr class='file-{e(i['file']['state'])}'><td>{e(i['prefecture_code'])} {e(i['prefecture_name'])}</td>"
            f"<td>{e(i['category_label'])}</td><td>{e(i['title'])}</td><td>{e(version)}</td>"
            f"<td>{e(i['file']['name'])}</td><td>{e(FILE_LABELS[i['file']['state']])}</td>"
            f"<td class='num'>{'-' if i['file']['size_bytes'] is None else format(i['file']['size_bytes'], ',')}</td>"
            f"<td>{e(i['organization'])}</td><td>{'設定あり（実行中かは不明）' if i['api_connection']['configured'] else '設定なし'}</td>"
            f"<td>{e(usage)}</td><td>{e(approval)}</td></tr>"
            f"<tr><td colspan='11'><details><summary>{e(summary_line(i))}</summary><pre>{e(detail)}</pre></details></td></tr>")
    return ("<!doctype html><html lang='ja'><head><meta charset='utf-8'><title>HereRisk Data Inventory</title>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<style>body{font-family:system-ui,sans-serif;margin:16px;background:#fff;color:#111}"
            "table{border-collapse:collapse;width:100%;font-size:14px}th,td{border:1px solid #ccc;padding:4px 6px;text-align:left;vertical-align:top}"
            "th{background:#f3f3f3}.num{text-align:right}.file-missing td,.file-unreadable td{background:#fdecea}"
            "pre{white-space:pre-wrap;margin:4px 0}summary{cursor:pointer}</style></head><body>"
            "<h1>Data Inventory（読み取り専用）</h1>"
            "<p>地域ファイル・取得元台帳・ファイルの実測から表示しています。この画面から取得・更新・削除・公開はできません。"
            "「公開承認」は、取得元台帳がOWNERの承認記録を参照している場合だけ「承認済み」になります。</p>"
            "<table><thead><tr><th>都道府県</th><th>分類</th><th>データ</th><th>年度・版</th><th>ファイル</th><th>状態</th>"
            "<th>サイズ（バイト）</th><th>提供組織</th><th>API接続</th><th>利用条件</th><th>公開承認</th></tr></thead><tbody>"
            + "".join(rows) + "</tbody></table></body></html>")


def make_handler(regions: Path, ledger: Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "HereRisk"
        sys_version = ""

        def log_message(self, format, *args):  # noqa: A002
            return

        def _send(self, status: int, ctype: str, body: bytes, extra: dict[str, str] | None = None) -> None:
            self.send_response(status)
            for k, v in {"Content-Type": ctype, "Cache-Control": "no-store", "Content-Length": str(len(body)),
                         "X-Content-Type-Options": "nosniff", **(extra or {})}.items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path not in ("/", "/inventory.json"):
                return self._send(404, "text/plain; charset=utf-8", b"not found")
            try:
                inv = build_inventory(regions, ledger)
            except Exception:  # noqa: BLE001 - no details on the page
                return self._send(500, "text/plain; charset=utf-8", "inventory unavailable".encode())
            if self.path == "/":
                return self._send(200, "text/html; charset=utf-8", render(inv).encode("utf-8"))
            return self._send(200, "application/json; charset=utf-8", json.dumps(inv, ensure_ascii=False).encode("utf-8"))

        def _refuse(self) -> None:
            self._send(405, "text/plain; charset=utf-8", b"read only", {"Allow": "GET"})

        do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _refuse

    return Handler


def build_server(regions: Path, ledger: Path, port: int) -> ThreadingHTTPServer:
    build_inventory(regions, ledger)              # fail at start on a bad regions file
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(regions, ledger))   # loopback only, fixed
    server.daemon_threads = True
    return server


def serve(regions: Path, ledger: Path, port: int) -> int:
    try:
        server = build_server(regions, ledger, port)
    except (ValueError, OSError) as exc:
        sys.stderr.write(f"data_inventory: not serving ({type(exc).__name__})\n")
        return 3
    sys.stderr.write(f"data_inventory: read-only page on http://127.0.0.1:{server.server_address[1]}/\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
