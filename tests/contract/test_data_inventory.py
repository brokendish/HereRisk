"""Phase 3-F: read-only Data Inventory (CLI and page share build_inventory)."""

from __future__ import annotations

import json
import socket
import threading
import zipfile

import pytest

from hererisk.data_inventory import web
from hererisk.data_inventory.__main__ import main as cli
from hererisk.data_inventory.inventory import build_inventory, summary_line
from hererisk.location.address_provider import HEADER, MlitAddressProvider
from hererisk.location.api import PATH, LocationApi
from hererisk.location.orchestrator import Orchestrator
from hererisk.location.providers import default_providers

_REAL_CONNECT = socket.socket.connect


def make_isj(d, pref):
    row = (pref, "テスト県", f"{pref}901", "西市", f"{pref}9010001001", "本町一丁目", "35.005000", "139.002000", "0", "3")
    text = "\r\n".join(",".join(f'"{v}"' for v in r) for r in (HEADER, row)) + "\r\n"
    p = d / f"{pref}000-19.0b.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(f"{pref}000-19.0b/{pref}_2025.csv", text.encode("cp932"))
    return p


def make_n03(d, pref):
    p = d / f"N03-20260101_{pref}_GML.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr(f"N03-20260101_{pref}.geojson", json.dumps({"type": "FeatureCollection", "features": []}))
    return p


def ledger(d, entries):
    p = d / "ledger.json"
    p.write_text(json.dumps({"entries": entries}, ensure_ascii=False))
    return p


def n03_entry(pref, usage="review_required", approval_ref=None, year="2026"):
    return {"entry_id": f"ksj-n03-{year}-{pref}", "dataset": {"data_year": year},
            "distribution": {"file_name": f"N03-20260101_{pref}_GML.zip", "region_codes": [pref]},
            "availability": {"download_verification": {"sha256": "ab" * 32}},
            "usage_terms": {"status": usage, "approval_ref": approval_ref, "open_issues": ["測量法の記載"]}}


@pytest.fixture
def setup(tmp_path):
    prefs = ["13", "14"]
    for pref in prefs:
        make_isj(tmp_path, pref)
        make_n03(tmp_path, pref)
    regions = tmp_path / "regions.json"

    def write(codes):
        regions.write_text(json.dumps({"regions": [
            {"prefecture_code": c, "address_isj": f"{c}000-19.0b.zip", "address_n03": f"N03-20260101_{c}_GML.zip"} for c in codes]}))
        return regions
    write(prefs)
    return tmp_path, write, ledger(tmp_path, [n03_entry("13")])


# 1 + 2 + 4: four items, readable names, year from the file and agreement with the ledger -----------
def test_four_items_with_names_and_years(setup) -> None:
    d, _, led = setup
    inv = build_inventory(d / "regions.json", led)
    items = {i["data_id"]: i for i in inv["items"]}
    assert set(items) == {"address-isj-13", "address-n03-13", "address-isj-14", "address-n03-14"}
    assert items["address-isj-13"]["name"] == "東京都 / 住所（大字・町丁目レベル位置参照情報）"
    assert items["address-n03-14"]["name"] == "神奈川県 / 行政区域（国土数値情報（行政区域データ）N03）"
    assert items["address-isj-14"]["year"] == "2025" and items["address-isj-14"]["version"]["edition"] == "19.0b"
    n03 = items["address-n03-13"]
    assert n03["year"] == "2026" and n03["version"]["reference_date"] == "2026-01-01"
    assert n03["ledger"]["entry_id"] == "ksj-n03-2026-13" and n03["ledger"]["year_matches_file"] is True
    assert n03["edition_id"] == "ksj-n03-2026-13" and n03["prefecture_code_matches_file"] is True
    assert summary_line(items["address-n03-14"]).startswith("神奈川県 / 行政区域 / 2026年版 / ファイルあり / API接続設定あり")


# 3: a missing file is shown as missing ------------------------------------------------------------
def test_missing_file(setup) -> None:
    d, _, led = setup
    (d / "14000-19.0b.zip").unlink()
    i = next(x for x in build_inventory(d / "regions.json", led)["items"] if x["data_id"] == "address-isj-14")
    assert i["file"]["state"] == "missing" and i["file"]["size_bytes"] is None and i["year"] == "unknown"
    assert "ファイルなし" in summary_line(i)


# recorded vs measured SHA-256 are kept apart ------------------------------------------------------
def test_recorded_hash_is_not_shown_as_measured(setup) -> None:
    d, _, led = setup
    i = next(x for x in build_inventory(d / "regions.json", led)["items"] if x["data_id"] == "address-n03-13")
    assert i["sha256"]["recorded"] == "ab" * 32 and i["sha256"]["measured"] is None and i["sha256"]["match"] is None
    j = next(x for x in build_inventory(d / "regions.json", led, measure_hashes=True)["items"] if x["data_id"] == "address-n03-13")
    assert j["sha256"]["measured"] and j["sha256"]["match"] is False     # synthetic file != recorded value


# 5: a third prefecture appears without code changes ------------------------------------------------
def test_third_prefecture_is_picked_up(setup) -> None:
    d, write, led = setup
    make_isj(d, "11")
    make_n03(d, "11")
    inv = build_inventory(write(["13", "14", "11"]), led)
    assert len(inv["items"]) == 6
    assert {i["prefecture_name"] for i in inv["items"] if i["prefecture_code"] == "11"} == {"埼玉県"}


# 7: usage terms / approval are never upgraded ----------------------------------------------------
@pytest.mark.parametrize("usage,ref,expected", [("review_required", None, "unconfirmed"), ("approved", None, "unconfirmed"),
                                                ("unverified", None, "unconfirmed"), ("approved", "docs/decisions/x.md", "approved")])
def test_public_approval_needs_an_approval_record(setup, usage, ref, expected) -> None:
    d, _, _ = setup
    led = ledger(d, [n03_entry("13", usage, ref)])
    items = {i["data_id"]: i for i in build_inventory(d / "regions.json", led)["items"]}
    assert items["address-n03-13"]["public_approval"] == expected
    assert items["address-isj-13"]["ledger"]["usage_terms"] == "unknown"        # not in the ledger
    assert items["address-isj-13"]["public_approval"] == "unconfirmed"
    assert items["address-isj-13"]["publication"]["registry"] == "not_referenced"


# 8 + 9: CLI and page give the same inventory; the page is read only -------------------------------
def test_cli_and_page_share_the_inventory(setup, capsys, monkeypatch) -> None:
    d, _, led = setup
    assert cli(["--regions", str(d / "regions.json"), "--ledger", str(led), "--format", "json"]) == 0
    from_cli = json.loads(capsys.readouterr().out)
    monkeypatch.setattr(socket.socket, "connect", lambda self, a: _REAL_CONNECT(self, a))
    httpd = web.build_server(d / "regions.json", led, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    assert httpd.server_address[0] == "127.0.0.1"          # loopback only, not configurable

    def req(method, target):
        with socket.socket() as s:
            s.settimeout(5)
            s.connect(("127.0.0.1", port))
            s.sendall(f"{method} {target} HTTP/1.1\r\nHost: x\r\nContent-Length: 0\r\n\r\n".encode())
            data = b""
            while chunk := s.recv(65536):
                data += chunk
                if b"\r\n\r\n" in data:
                    head, _, body = data.partition(b"\r\n\r\n")
                    n = next((int(line.split(b":")[1]) for line in head.split(b"\r\n") if line.lower().startswith(b"content-length")), 0)
                    if len(body) >= n:
                        break
        head, _, body = data.partition(b"\r\n\r\n")
        return int(head.split()[1]), body
    try:
        status, body = req("GET", "/inventory.json")
        assert status == 200 and json.loads(body) == from_cli
        status, page = req("GET", "/")
        text = page.decode()
        assert status == 200 and "東京都" in text and "神奈川県" in text and "N03-20260101_14_GML.zip" in text
        assert "<details>" in text and "公開承認" in text
        assert req("GET", "/?path=/etc/passwd")[0] == 404
        assert req("GET", "/../../etc/passwd")[0] == 404
        for m in ("POST", "PUT", "DELETE"):
            assert req(m, "/")[0] == 405
    finally:
        httpd.shutdown()
        httpd.server_close()


# 6 + 9: the Location API is unaffected and never shows file names or paths ------------------------
def test_location_api_does_not_expose_paths(setup) -> None:
    d, _, _ = setup
    providers = default_providers()
    providers["address"] = MlitAddressProvider([("13", d / "13000-19.0b.zip")])
    doc = LocationApi(Orchestrator(providers, mode="local", allow_synthetic=False)).handle(
        "GET", PATH, "lat=35.005&lon=139.002").json()
    assert doc["address"]["status"] == "available"
    text = json.dumps(doc, ensure_ascii=False)
    assert str(d) not in text and ".zip" not in text and "regions" not in text
