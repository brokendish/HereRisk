"""Phase 3-B: Location API ``elevation`` section from the existing Elevation API (loopback only).

The real Elevation API runs in-process on published TEST data (tests/e2e_support.py, no real GSI
data); a small stub server covers the Elevation API answers that are hard to produce for real.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from e2e_support import TOKYO_TILES, World, centre, png_with
from hererisk.elevation.api import server as elevation_server
from hererisk.location import server as location_server
from hererisk.location.api import PATH, LocationApi
from hererisk.location.elevation_provider import ElevationConfigError, ElevationProvider
from hererisk.location.orchestrator import Orchestrator
from hererisk.location.providers import default_providers

_REAL_CONNECT = socket.socket.connect
A, B = TOKYO_TILES
BODY_A = png_with({(10, 20): (0, 4, 210), (11, 20): (0, 0, 0), (12, 20): (255, 255, 136), (13, 20): (128, 0, 0)})
BODY_B = png_with({}, default=(0, 1, 0))


@pytest.fixture(autouse=True)
def loopback_only(monkeypatch):
    def connect(self, address):
        if address[0] != "127.0.0.1":
            raise AssertionError("only loopback allowed")
        return _REAL_CONNECT(self, address)
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "create_connection", _create_connection)


def _create_connection(address, timeout=None, source_address=None, **kw):
    host, port = address
    if host != "127.0.0.1":
        raise AssertionError("only loopback allowed")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if timeout is not None:
        sock.settimeout(timeout)
    sock.connect((host, port))
    return sock


def _serve(httpd):
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd.server_address[1]


@pytest.fixture
def token_file(tmp_path):
    p = tmp_path / "api-token"
    p.write_text(secrets.token_urlsafe(32) + "\n")
    os.chmod(p, 0o600)
    return p


@pytest.fixture
def elevation_api(tmp_path, token_file):
    (tmp_path / "w").mkdir()
    world = World(tmp_path / "w", {A: BODY_A, B: BODY_B})
    assert world.run()[-1].status.value == "SUCCESS"
    httpd = elevation_server.build_server(world.data_root, "127.0.0.1", 0, auth_token_file=token_file)
    port = _serve(httpd)
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    httpd.server_close()


def locate(provider, lat, lon, **kw):
    providers = default_providers()
    providers["elevation"] = provider
    api = LocationApi(Orchestrator(providers, mode="local", allow_synthetic=kw.get("allow_synthetic", False)))
    r = api.handle("GET", PATH, f"lat={lat!r}&lon={lon!r}")
    assert r.status == 200
    return r.json(), r.body


def at(tile, px, py):
    return centre(*tile, px, py)


# 1 + 2 + 7: success -> available, 0 m and negative kept, source mapped -----------------------------
@pytest.mark.parametrize("px,expected", [(10, 12.34), (11, 0.0), (12, -1.2)])
def test_success_is_available_with_value_and_source(elevation_api, token_file, px, expected) -> None:
    lat, lon = at(A, px, 20)
    doc, _ = locate(ElevationProvider(elevation_api, token_file=token_file), lat, lon)
    e = doc["elevation"]
    assert e["status"] == "available" and e["result"] == {"elevation_m": expected, "unit": "m"}
    assert e["synthetic"] is False
    src = e["source"]
    assert {"source_id", "organization", "data_version", "published_at", "attribution"} <= set(src)
    assert src["attribution"]["text"] and src["attribution"]["license"]
    assert "title" not in src                     # not provided by the Elevation API, not invented
    for name in ("address", "flood", "tsunami", "storm_surge", "landslide"):
        section = doc["address"] if name == "address" else doc["hazards"][name]
        assert section["status"] == "not_available", name


# 3: no_data never produces a value; the reason is kept --------------------------------------------
def test_no_data_is_not_available_without_value(elevation_api, token_file) -> None:
    p = ElevationProvider(elevation_api, token_file=token_file)
    lat, lon = at(A, 13, 20)
    nodata = locate(p, lat, lon)[0]["elevation"]
    assert nodata["status"] == "not_available" and nodata["result"] is None and nodata["reason"] == "elevation_nodata"
    outside = locate(p, 43.0621, 141.3544)[0]["elevation"]       # Sapporo: outside the test coverage
    assert outside["status"] == "not_available" and outside["result"] is None and outside["reason"] == "no_coverage"


# 8: the token never leaves; a wrong token is an error -----------------------------------------------
def test_token_is_never_exposed(elevation_api, token_file, tmp_path) -> None:
    token = token_file.read_text().strip()
    lat, lon = at(A, 10, 20)
    _, body = locate(ElevationProvider(elevation_api, token_file=token_file), lat, lon)
    assert token.encode() not in body
    wrong = tmp_path / "wrong-token"
    wrong.write_text(secrets.token_urlsafe(32) + "\n")
    os.chmod(wrong, 0o600)
    doc, body = locate(ElevationProvider(elevation_api, token_file=wrong), lat, lon)
    assert doc["elevation"]["status"] == "error" and doc["elevation"]["error"]["code"] == "upstream_rejected"
    assert wrong.read_text().strip().encode() not in body and token.encode() not in body
    loose = tmp_path / "loose-token"
    loose.write_text(secrets.token_urlsafe(32) + "\n")
    os.chmod(loose, 0o644)
    with pytest.raises(ElevationConfigError) as exc:
        ElevationProvider(elevation_api, token_file=loose)
    assert loose.read_text().strip() not in str(exc.value) and str(loose) not in str(exc.value)


# stub Elevation API ---------------------------------------------------------------------------
GOOD_DATASET = {"id": "dem-x", "publication_version": "v1", "source": {"provider": "国土地理院", "page_url": None},
                "published_at": "2026-10-01T00:00:00.000Z", "data_reference_date": None,
                "attribution": {"text": "出典: 国土地理院", "license": "GSI", "url": None}}


def stub(answer, delay=0.0):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            return

        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            time.sleep(delay)
            status, doc = answer(req)
            body = doc if isinstance(doc, bytes) else json.dumps(doc).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    return ThreadingHTTPServer(("127.0.0.1", 0), H)


def doc(req, status, result=None, dataset=GOOD_DATASET, code=None):
    return {"hazard": "elevation", "location": req, "status": status, "result": result, "dataset": dataset,
            "error": None if code is None else {"code": code, "message": "x"}, "evaluated_at": "2026-10-25T00:00:00.000Z"}


@pytest.fixture
def stubbed():
    servers = []

    def make(answer, delay=0.0):
        httpd = stub(answer, delay)
        servers.append(httpd)
        return ElevationProvider(f"http://127.0.0.1:{_serve(httpd)}", timeout_s=0.5)
    yield make
    for s in servers:
        s.shutdown()
        s.server_close()


# 4 + 5: retrieval_failed -> error, indeterminate -> unknown -----------------------------------------
def test_retrieval_failed_and_indeterminate(stubbed) -> None:
    e = locate(stubbed(lambda r: (503, doc(r, "retrieval_failed", code="data_unavailable"))), 35.7, 139.7)[0]["elevation"]
    assert e["status"] == "error" and e["error"]["code"] == "upstream_retrieval_failed" and e.get("result") is None
    e = locate(stubbed(lambda r: (500, doc(r, "indeterminate", dataset=None, code="dataset_integrity_error"))), 35.7, 139.7)[0]["elevation"]
    assert e["status"] == "unknown" and e["result"] is None and e["reason"] == "dataset_integrity_error"


@pytest.mark.parametrize("answer", [
    lambda r: (200, doc(r, "sucess", {"elevation_m": 1.0})),                                 # unknown status
    lambda r: (200, b"{not json"),                                                         # broken JSON
    lambda r: (200, doc(r, "success", {"elevation_m": "12"})),                             # not a number
    lambda r: (200, doc(r, "success", {"elevation_m": None})),                             # missing value
    lambda r: (200, doc(r, "success", {"elevation_m": 1.0}, dataset=None)),                # no source
    lambda r: (200, doc(r, "success", {"elevation_m": 1.0}, dataset={"id": "x"})),         # incomplete source
    lambda r: (200, doc({"lat": 1.0, "lon": 2.0}, "success", {"elevation_m": 1.0})),       # another location
    lambda r: (200, doc(r, "no_data", {"elevation_m": 0.0}, code="no_coverage")),          # no_data with a value
])
def test_broken_answers_never_become_available(stubbed, answer) -> None:
    e = locate(stubbed(answer), 35.7, 139.7)[0]["elevation"]
    assert e["status"] == "error" and e["error"]["code"] == "invalid_provider_result"
    assert "result" not in e or e["result"] is None


def test_fixture_dataset_is_synthetic_and_refused_unless_declared(stubbed) -> None:
    fixture = dict(GOOD_DATASET, id="fixture-dem-png-tokyo-z14-14550-6450")
    p = stubbed(lambda r: (200, doc(r, "success", {"elevation_m": 81.44}, dataset=fixture)))
    assert locate(p, 35.7, 139.7)[0]["elevation"]["error"]["code"] == "synthetic_not_allowed"
    e = locate(p, 35.7, 139.7, allow_synthetic=True)[0]["elevation"]
    assert e["status"] == "available" and e["synthetic"] is True and e["notice"].startswith("【合成データ】")


# 6: unreachable / timeout keep the other five sections ---------------------------------------------
def test_unreachable_and_timeout_keep_other_sections(stubbed) -> None:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free = s.getsockname()[1]
    doc_, _ = locate(ElevationProvider(f"http://127.0.0.1:{free}"), 35.7, 139.7)
    assert doc_["elevation"]["error"]["code"] == "upstream_unreachable"
    slow = stubbed(lambda r: (200, doc(r, "success", {"elevation_m": 1.0})), delay=1.5)
    doc_, _ = locate(slow, 35.7, 139.7)
    assert doc_["elevation"]["status"] == "error" and doc_["elevation"]["error"]["code"] == "timeout"
    for d in (doc_,):
        assert d["address"]["status"] == "not_available"
        assert all(d["hazards"][h]["status"] == "not_available" for h in d["hazards"])


# 9: the default mode never connects; only 127.0.0.1 is accepted -------------------------------------
def test_default_mode_has_no_elevation_connection() -> None:
    httpd = location_server.build_server("127.0.0.1", 0)
    try:
        port = _serve(httpd)
        with socket.create_connection(("127.0.0.1", port)) as sock:
            sock.sendall(f"GET {PATH}?lat=35.7&lon=139.7 HTTP/1.1\r\nHost: x\r\n\r\n".encode())
            data = b""
            while chunk := sock.recv(65536):
                data += chunk
        body = json.loads(data.partition(b"\r\n\r\n")[2])
        assert body["mode"] == "mock" and body["elevation"]["status"] == "not_available"
        assert body["elevation"]["provider"] == "elevation"
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert location_server.main(["--elevation-fixture"]) == 2


@pytest.mark.parametrize("url", ["http://localhost:8000", "http://10.0.0.1:8000", "https://127.0.0.1:8000",
                                 "http://127.0.0.1", "http://127.0.0.1:8000/api", "http://u:p@127.0.0.1:8000"])
def test_only_plain_loopback_url_is_accepted(url) -> None:
    with pytest.raises(ElevationConfigError):
        ElevationProvider(url)
