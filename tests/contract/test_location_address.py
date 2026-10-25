"""Phase 3-C: Location API ``address`` section from MLIT 大字・町丁目レベル位置参照情報.

Unit tests use a small synthetic Shift-JIS CSV (fictional names). The real-data test runs only
when HERERISK_ISJ_DATA points at the official Tokyo ZIP (kept outside Git).
"""

from __future__ import annotations

import json
import math
import os
import random
import socket
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from hererisk.location import server as location_server
from hererisk.location.address_provider import HEADER, AddressDataError, MlitAddressProvider, haversine_m
from hererisk.location.api import PATH, LocationApi
from hererisk.location.orchestrator import Orchestrator
from hererisk.location.providers import default_providers

_REAL_CONNECT = socket.socket.connect
ROWS = [  # fictional names; positions around Tokyo Station (dense) and one sparse rural point
    ("13", "東京都", "13901", "テスト区", "139010001001", "見本町一丁目", "35.681000", "139.767000", "0", "3"),
    ("13", "東京都", "13901", "テスト区", "139010001002", "見本町二丁目", "35.684000", "139.767000", "0", "3"),
    ("13", "東京都", "13901", "テスト区", "139010002000", "架空", "35.681000", "139.771000", "0", "1"),
    ("13", "東京都", "13902", "テスト村", "139020001000", "山奥", "35.800000", "139.000000", "0", "1"),
    ("13", "東京都", "13902", "テスト村", "139020002000", "谷間", "35.830000", "139.000000", "0", "2"),
]


def write_csv(path: Path, rows=ROWS, header=HEADER, encoding="cp932") -> Path:
    lines = [",".join(f'"{v}"' for v in header)] + [",".join(f'"{v}"' for v in r) for r in rows]
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode(encoding))
    return path


@pytest.fixture
def csv_path(tmp_path):
    return write_csv(tmp_path / "13_2025.csv")


def api_with(address, **more):
    providers = default_providers()
    providers["address"] = address
    providers.update(more)
    return LocationApi(Orchestrator(providers, mode="local", allow_synthetic=False))


# 2 + 4: address text and distance --------------------------------------------------------------
def test_address_is_built_from_csv_parts_with_distance(csv_path) -> None:
    s = MlitAddressProvider(csv_path).lookup(35.6812, 139.7671)
    r = s["result"]
    assert s["status"] == "available" and s["synthetic"] is False
    assert r["display_name"] == "東京都テスト区見本町一丁目付近"
    assert (r["prefecture"], r["municipality"], r["area"]) == ("東京都", "テスト区", "見本町一丁目")
    assert r["precision"] == "chome" and r["method"] == "nearest_representative_point"
    assert r["is_confirmed_address"] is False
    doc = api_with(MlitAddressProvider(csv_path)).handle("GET", PATH, "lat=35.6812&lon=139.7671").json()
    assert "推定" in doc["address"]["notice"] and "確定ではありません" in doc["address"]["notice"]
    assert r["distance_m"] == pytest.approx(haversine_m(35.6812, 139.7671, 35.681, 139.767), abs=0.1)
    assert 0 < r["distance_m"] < 50
    assert s["source"]["organization"] == "国土交通省" and s["source"]["data_version"] == "2025"
    assert "位置参照情報 国土交通省" in s["source"]["attribution"]["text"]


def test_haversine_is_a_distance_on_the_sphere() -> None:
    assert haversine_m(35.0, 139.0, 36.0, 139.0) == pytest.approx(111195, rel=1e-3)
    # the same longitude difference is shorter at higher latitude (not a plain degree difference)
    assert haversine_m(60.0, 0.0, 60.0, 1.0) == pytest.approx(haversine_m(0.0, 0.0, 0.0, 1.0) / 2, rel=1e-3)


# 3: nearest representative point (same answer as a full scan) --------------------------------------
def test_nearest_point_matches_a_full_scan(csv_path) -> None:
    p = MlitAddressProvider(csv_path)
    rnd = random.Random(7)
    for _ in range(300):
        lat, lon = rnd.uniform(35.67, 35.85), rnd.uniform(138.99, 139.78)
        want = min(ROWS, key=lambda r: haversine_m(lat, lon, float(r[6]), float(r[7])))
        d, i = p._nearest(lat, lon)
        assert p._points[i].area == want[5]
        assert d == pytest.approx(haversine_m(lat, lon, float(want[6]), float(want[7])))


# 5: far positions never get a Tokyo address --------------------------------------------------------
@pytest.mark.parametrize("lat,lon", [(34.7025, 135.4959), (37.5665, 126.978), (35.70, 139.767), (0.0, 0.0)])
def test_out_of_coverage_returns_no_address(csv_path, lat, lon) -> None:
    doc = api_with(MlitAddressProvider(csv_path)).handle("GET", PATH, f"lat={lat}&lon={lon}").json()
    a = doc["address"]
    assert a["status"] == "not_available" and a["result"] is None and a["reason"] == "out_of_coverage"
    assert "東京都" not in json.dumps(a, ensure_ascii=False).replace(a["source"]["attribution"]["text"], "")


def test_sparse_rural_points_get_a_larger_radius(csv_path) -> None:
    p = MlitAddressProvider(csv_path)
    rural = p.lookup(35.80 + 0.012, 139.0)             # ~1.3 km from 山奥, spacing ~3.3 km
    assert rural["status"] == "available" and rural["result"]["area"] == "山奥"
    city = p.lookup(35.681 - 0.009, 139.767)           # ~1 km from 見本町一丁目, spacing ~330 m
    assert city["status"] == "not_available"


# 6: missing / malformed data stops the start -------------------------------------------------------
@pytest.mark.parametrize("make", [
    lambda d: d / "missing.csv",
    lambda d: write_csv(d / "13_2025.csv", header=HEADER[:-1]),
    lambda d: write_csv(d / "13_2025.csv", rows=[ROWS[0][:9]]),
    lambda d: write_csv(d / "13_2025.csv", rows=[ROWS[0][:6] + ("abc", "139.7", "0", "3")]),
    lambda d: write_csv(d / "13_2025.csv", rows=[ROWS[0][:6] + ("95.0", "139.7", "0", "3")]),
    lambda d: write_csv(d / "13_2025.csv", rows=[ROWS[0][:5] + ("",) + ROWS[0][6:]]),
    lambda d: write_csv(d / "13_2025.csv", rows=[]),
    lambda d: (d / "13_2025.csv").write_bytes(b'"\x82\xff"\r\n') and d / "13_2025.csv",   # not cp932
])
def test_bad_data_is_rejected(tmp_path, make) -> None:
    with pytest.raises(AddressDataError):
        MlitAddressProvider(make(tmp_path))


def test_zip_input_and_server_refuses_bad_file(tmp_path, csv_path, capsys) -> None:
    z = tmp_path / "13000-19.0b.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.write(csv_path, "13000-19.0b/13_2025.csv")
    p = MlitAddressProvider(z)
    assert p.meta["edition"] == "19.0b" and p.meta["rows"] == len(ROWS)
    assert location_server.main(["--address-isj", str(tmp_path / "none.zip"), "--port", "0"]) == 3
    assert "35." not in capsys.readouterr().err


# 7: an address failure keeps elevation and hazards --------------------------------------------------
class Boom:
    id = "mlit_address"

    def lookup(self, lat, lon):
        raise RuntimeError("csv row 12 broken /secret/path")


class FixedElevation:
    id = "elevation-api"

    def lookup(self, lat, lon):
        return {"provider": self.id, "synthetic": False, "status": "available",
                "result": {"elevation_m": 3.0, "unit": "m"}, "source": {"source_id": "x"}}


def test_address_failure_keeps_other_sections() -> None:
    doc = api_with(Boom(), elevation=FixedElevation()).handle("GET", PATH, "lat=35.68&lon=139.76").json()
    assert doc["address"]["status"] == "error" and "secret" not in json.dumps(doc)
    assert doc["elevation"]["status"] == "available" and doc["elevation"]["result"]["elevation_m"] == 3.0
    assert all(h["status"] == "not_available" for h in doc["hazards"].values())


# 8: together with the Elevation provider through the real server ------------------------------------
def test_server_with_address_and_elevation(monkeypatch, csv_path) -> None:
    monkeypatch.setattr(socket.socket, "connect",
                        lambda self, a: _REAL_CONNECT(self, a) if a[0] == "127.0.0.1" else (_ for _ in ()).throw(AssertionError))

    def create_connection(address, timeout=None, *args, **kw):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(address)
        return sock
    monkeypatch.setattr(socket, "create_connection", create_connection)

    class Elev(BaseHTTPRequestHandler):
        def log_message(self, *a):
            return

        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            body = json.dumps({"hazard": "elevation", "location": req, "status": "success", "result": {"elevation_m": 4.5},
                               "dataset": {"id": "dem-x", "publication_version": "v1", "source": {"provider": "p"},
                                           "published_at": "2026-10-01T00:00:00.000Z",
                                           "attribution": {"text": "t", "license": "l"}},
                               "error": None, "evaluated_at": "x"}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    elev = ThreadingHTTPServer(("127.0.0.1", 0), Elev)
    threading.Thread(target=elev.serve_forever, daemon=True).start()
    httpd = location_server.build_server("127.0.0.1", 0, elevation_api=f"http://127.0.0.1:{elev.server_address[1]}",
                                         address_isj=csv_path)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with socket.create_connection(("127.0.0.1", httpd.server_address[1]), 5) as sock:
            sock.sendall(f"GET {PATH}?lat=35.6812&lon=139.7671 HTTP/1.1\r\nHost: x\r\n\r\n".encode())
            data = b""
            while chunk := sock.recv(65536):
                data += chunk
        doc = json.loads(data.partition(b"\r\n\r\n")[2])
        assert doc["mode"] == "local"
        assert doc["address"]["result"]["display_name"] == "東京都テスト区見本町一丁目付近"
        assert doc["elevation"]["result"]["elevation_m"] == 4.5
        assert all(h["status"] == "not_available" for h in doc["hazards"].values())
    finally:
        for s in (httpd, elev):
            s.shutdown()
            s.server_close()


# 1: real data (only when the official Tokyo ZIP is available locally) ------------------------------
REAL = os.environ.get("HERERISK_ISJ_DATA")


@pytest.mark.skipif(not REAL, reason="HERERISK_ISJ_DATA not set (official data is kept outside Git)")
def test_real_tokyo_data() -> None:
    p = MlitAddressProvider(Path(REAL))
    s = p.lookup(35.681236, 139.767125)   # Tokyo Station
    assert s["status"] == "available" and s["result"]["display_name"] == "東京都千代田区丸の内一丁目付近"
    assert s["result"]["distance_m"] < 100
    assert p.lookup(35.5313, 139.6969)["status"] == "not_available"   # Kawasaki Station (Kanagawa)
    assert p.lookup(34.7025, 135.4959)["status"] == "not_available"   # Osaka
    assert not math.isnan(s["result"]["distance_m"])
