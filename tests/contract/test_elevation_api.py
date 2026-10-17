"""Contract tests: Phase 1-E POST /api/v1/elevation (docs/api/elevation-contract-v0.1.md).

The published data comes from the mocked production-format pipeline with
TEST-ONLY grants (tests/e2e_support.py); no real GSI data, no real network.
The loopback test opens a socket to 127.0.0.1 only.
"""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import threading

import pytest

from e2e_support import REPO, TOKYO_TILES, World, centre, png_with, post
from hererisk.common.logging import ListSink, StructuredLogger
from hererisk.elevation.api import handler as handler_mod
from hererisk.elevation.api import server
from hererisk.elevation.api.handler import ERRORS, PATH
from hererisk.elevation.api.published import StartupError
from hererisk.elevation.publish import registry as reg
from hererisk.elevation.validate.core import CandidateRejected

_REAL_CONNECT = socket.socket.connect  # saved before the autouse network guard
A, B = TOKYO_TILES
KEYS = {"hazard", "location", "status", "result", "dataset", "error", "evaluated_at"}
BODY_A = png_with({(10, 20): (0, 4, 210),        # 1234 cm
                   (11, 20): (0, 0, 0),          # 0 cm
                   (12, 20): (255, 255, 136),    # -120 cm
                   (13, 20): (128, 0, 0)})       # no-data
BODY_B = png_with({}, default=(0, 1, 0))         # 256 cm everywhere


@pytest.fixture
def world(tmp_path):
    (tmp_path / "w").mkdir()
    w = World(tmp_path / "w", {A: BODY_A, B: BODY_B})
    results = w.run()
    assert results[-1].module == "publish" and results[-1].status.value == "SUCCESS"
    return w


@pytest.fixture
def api(world):
    return world.api()


def at(tile, px, py):
    lat, lon = centre(*tile, px, py)
    return {"lat": lat, "lon": lon}


def check_shape(doc):
    assert set(doc) == KEYS and doc["hazard"] == "elevation"
    if doc["status"] == "success":
        assert doc["error"] is None and set(doc["result"]) == {"elevation_m"}
    else:
        assert doc["result"] is None and set(doc["error"]) == {"code", "message"}
        assert doc["error"]["message"] == ERRORS[doc["error"]["code"]][2]
    if doc["status"] == "invalid_request":
        assert doc["location"] is None and doc["evaluated_at"] is None and doc["dataset"] is None
    else:
        assert doc["evaluated_at"].endswith("Z") and len(doc["evaluated_at"]) == 24


# -- success / no_data -----------------------------------------------------------------------------
@pytest.mark.parametrize("tile,px,expected", [(A, 10, 12.34), (A, 11, 0.0), (A, 12, -1.2),
                                              (A, 0, 1.0), (B, 7, 2.56)])
def test_success_values(api, tile, px, expected) -> None:
    body = at(tile, px, 20)
    resp = post(api, body)
    doc = resp.json()
    check_shape(doc)
    assert resp.status == 200 and doc["status"] == "success"
    assert doc["result"] == {"elevation_m": expected} and doc["location"] == body
    assert resp.headers["Content-Type"] == "application/json"
    assert resp.headers["Cache-Control"] == "no-store"


def test_dataset_block_is_public_information_only(api, world) -> None:
    doc = post(api, at(A, 10, 20)).json()
    ds = doc["dataset"]
    assert set(ds) == {"id", "publication_version", "source", "published_at",
                       "data_reference_date", "attribution"}
    assert ds["id"] == f"gsi-dem10b-candidate-z14-{A[0]}-{A[1]}"
    assert ds["publication_version"].startswith("pub-") and ds["data_reference_date"] is None
    assert set(ds["source"]) == {"provider", "page_url"}
    assert set(ds["attribution"]) == {"text", "license", "url"}
    assert ds["published_at"].endswith(".000Z")
    text = json.dumps(doc)
    for internal in (str(world.data_root), "versions/", "sha256", "work/", "records", "rev-"):
        assert internal not in text


def test_elevation_nodata_and_no_coverage(api) -> None:
    nodata = post(api, at(A, 13, 20)).json()
    check_shape(nodata)
    assert nodata["status"] == "no_data" and nodata["error"]["code"] == "elevation_nodata"
    assert nodata["dataset"] is not None
    far = post(api, {"lat": 43.06, "lon": 141.35}).json()  # Sapporo: not published
    check_shape(far)
    assert far["error"]["code"] == "no_coverage" and far["dataset"] is None
    assert far["location"] == {"lat": 43.06, "lon": 141.35}


@pytest.mark.parametrize("body", [{"lat": 90, "lon": 0}, {"lat": -90, "lon": 0},
                                  {"lat": 0, "lon": 180}, {"lat": 0, "lon": -180},
                                  {"lat": 85.06, "lon": 139.0}])
def test_contract_bounds_are_valid_but_uncovered(api, body) -> None:
    doc = post(api, body).json()
    check_shape(doc)
    assert doc["status"] == "no_data" and doc["error"]["code"] == "no_coverage"
    assert doc["location"] == body  # never clamped / wrapped


# -- input contract -----------------------------------------------------------------------------
@pytest.mark.parametrize("raw", [
    b'{"lat": 35.68, "lon": 139.76, "x": 1}', b'{"lat": 35.68}', b'{}', b'[]', b'',
    b'{"lat": 35.68, "lat": 35.69, "lon": 139.76}',
    b'{"lat": 35.68, "l\\u0061t": 35.69, "lon": 139.76}',
    b'{"lat": NaN, "lon": 139.76}', b'{"lat": Infinity, "lon": 139.76}',
    b'{"lat": 1e309, "lon": 139.76}', b'{"lat": true, "lon": 139.76}',
    b'{"lat": "35.68", "lon": 139.76}', b'{"lat": null, "lon": 139.76}',
    b'{"lat": 90.0000001, "lon": 0}', b'{"lat": -91, "lon": 0}', b'{"lat": 0, "lon": 180.5}',
    b'{"lat": [35], "lon": 139.76}', b'\xef\xbb\xbf{"lat": 1, "lon": 2}', b'{"lat": 1, "lon": 2',
    b'"text"', b'{"lat": 1, "lon": 2} x',
], ids=lambda r: r.decode("utf-8", "replace")[:40] or "empty")
def test_invalid_input(api, raw) -> None:
    resp = post(api, None, raw=raw)
    doc = resp.json()
    check_shape(doc)
    assert resp.status == 400 and doc["error"]["code"] == "invalid_input"


def test_integer_and_float_are_both_numbers(api) -> None:
    lat, lon = centre(*A, 10, 20)
    assert post(api, None, raw=json.dumps({"lon": lon, "lat": lat}).encode()).json()["status"] \
        == "success"  # key order does not matter
    assert post(api, {"lat": 35, "lon": 139}).status == 200


def test_method_media_size_query_and_path(api) -> None:
    body = at(A, 10, 20)
    get = post(api, body, method="GET")
    assert get.status == 405 and get.headers["Allow"] == "POST"
    assert get.json()["error"]["code"] == "method_not_allowed"
    for headers in ({}, {"Content-Type": "text/plain"}, {"Content-Type": "application/json; charset=latin-1"},
                    {"Content-Type": "application/json", "Content-Encoding": "gzip"},
                    {"Content-Type": "application/json; boundary=x"}):
        resp = post(api, body, headers=headers)
        assert resp.status == 415 and resp.json()["error"]["code"] == "unsupported_media_type"
    ok = post(api, body, headers={"content-type": "Application/JSON; charset=UTF-8"})
    assert ok.status == 200
    big = post(api, None, raw=b'{"lat": 1, "lon": 2' + b" " * 1100 + b"}")
    assert big.status == 413 and big.json()["error"]["code"] == "request_too_large"
    query = post(api, body, query="lat=1&lon=2")
    assert query.status == 400 and query.json()["error"]["code"] == "invalid_input"
    missing = post(api, body, path="/api/v1/flood")
    assert missing.status == 404 and missing.json()["error"]["code"] == "not_found"
    for resp in (get, big, query, missing):
        check_shape(resp.json())


def test_check_order_path_then_method_then_media(api) -> None:
    assert post(api, None, raw=b"x" * 5000, method="GET", path="/x").status == 404
    assert post(api, None, raw=b"x" * 5000, method="GET", headers={}).status == 405
    assert post(api, None, raw=b"x" * 5000, headers={}).status == 415
    assert post(api, None, raw=b"x" * 5000, query="a=1").status == 413


# -- request-time failures --------------------------------------------------------------------
def entity_path(world, tile):
    doc_dir = world.data_root / "elevation/rel/versions"
    return next(p for p in doc_dir.rglob("*.json") if p.name.endswith(f"-{tile[0]}-{tile[1]}.json"))


def test_entity_missing_at_request_time(world, api) -> None:
    entity_path(world, A).unlink()
    resp = post(api, at(A, 10, 20))
    doc = resp.json()
    check_shape(doc)
    assert resp.status == 500 and doc["error"]["code"] == "published_data_missing"
    assert doc["dataset"] is None and doc["status"] == "indeterminate"
    assert post(api, at(B, 7, 20)).json()["status"] == "success"  # other datasets unaffected


def test_entity_changed_at_request_time(world, api) -> None:
    path = entity_path(world, A)
    data = path.read_bytes()
    path.unlink()
    path.write_bytes(data.replace(b"1234", b"1235", 1))
    resp = post(api, at(A, 10, 20))
    assert resp.status == 500 and resp.json()["error"]["code"] == "dataset_integrity_error"
    assert resp.json()["dataset"] is None


def test_entity_unreadable_is_retrieval_failure(world, api, monkeypatch) -> None:
    def broken(*a, **k):
        raise reg.RegistryError("unavailable", "io")

    monkeypatch.setattr(api._published, "read_entity", broken)
    resp = post(api, at(A, 10, 20))
    doc = resp.json()
    check_shape(doc)
    assert resp.status == 503 and doc["status"] == "retrieval_failed"
    assert doc["error"]["code"] == "data_unavailable" and doc["dataset"] is not None


def test_quality_failure(world, api, monkeypatch) -> None:
    def reject(*a, **k):
        raise CandidateRejected("bad")

    monkeypatch.setattr(handler_mod, "validate_candidate", reject)
    resp = post(api, at(A, 10, 20))
    assert resp.status == 500 and resp.json()["error"]["code"] == "data_quality_error"


def test_evaluation_timeout(world) -> None:
    ticks = iter([0.0, 10.0])
    api = world.api(monotonic=lambda: next(ticks))
    resp = post(api, at(A, 10, 20))
    assert resp.status == 503 and resp.json()["error"]["code"] == "data_unavailable"


def test_internal_error_never_leaks(world, api, monkeypatch) -> None:
    def explode(*a, **k):
        raise RuntimeError(f"secret {world.data_root}")

    monkeypatch.setattr(api._published, "covering", explode)
    resp = post(api, at(A, 10, 20))
    doc = resp.json()
    check_shape(doc)
    assert resp.status == 500 and doc["error"]["code"] == "internal_error"
    assert str(world.data_root) not in resp.body.decode() and "secret" not in resp.body.decode()


def test_ambiguous_dataset(world) -> None:
    """Two registries publishing the same tile: never pick one silently."""
    ptr = json.loads((world.data_root / "elevation/rel/registry/13/current.json").read_bytes())
    regdir = world.data_root / "elevation/rel/registry"
    doc = json.loads((regdir / f"13/revisions/{ptr['registry_revision']}.json").read_bytes())
    dataset = json.loads(json.dumps(doc["datasets"][0]))
    old_entity = world.data_root / "elevation/rel" / dataset["publication"]["path"]
    dataset["id"] = "other-copy-" + dataset["id"]
    dataset["coverage"]["prefectures"] = ["11"]
    pub = dataset["publication"]
    pub["filename"] = f"{dataset['id']}.json"
    pub["path"] = f"versions/{pub['version']}/{pub['filename']}"
    (world.data_root / "elevation/rel" / pub["path"]).write_bytes(old_entity.read_bytes())
    other = {"schema_version": "0.1", "prefecture_code": "11", "registry_revision": "rev-other",
             "datasets": [dataset]}
    data = reg.to_bytes(other)
    (regdir / "11/revisions").mkdir(parents=True)
    (regdir / "11/revisions/rev-other.json").write_bytes(data)
    (regdir / "11/current.json").write_bytes(reg.to_bytes(
        {"schema_version": "0.1", "prefecture_code": "11", "registry_revision": "rev-other",
         "registry_sha256": hashlib.sha256(data).hexdigest(), "previous_revision": None}))
    api = world.api()
    resp = post(api, centre_body := at(A, 10, 20))
    doc = resp.json()
    check_shape(doc)
    assert resp.status == 500 and doc["error"]["code"] == "ambiguous_dataset"
    assert doc["dataset"] is None and doc["location"] == centre_body
    assert post(api, at(B, 7, 20)).json()["status"] == "success"


# -- logging ----------------------------------------------------------------------------------
def test_logs_carry_request_id_but_never_position(world) -> None:
    sink = ListSink()
    api = world.api(sink=sink)
    bodies = [at(A, 10, 20), {"lat": 43.06123, "lon": 141.35456}, {"lat": 99.123, "lon": 0}]
    for body in bodies:
        post(api, body)
    assert len(sink.entries) == 3
    ids = {e["request_id"] for e in sink.entries}
    assert len(ids) == 3 and all(len(i) == 32 for i in ids)
    text = json.dumps(sink.entries)
    for body in bodies:
        for value in body.values():
            if value:  # coordinate-like values (0 also appears in timestamps)
                assert repr(value) not in text and repr(value)[:6] not in text
    assert "lat" not in text and "lon" not in text and str(world.data_root) not in text
    assert [e["message"] for e in sink.entries] == ["request success", "request no_data",
                                                    "request invalid_request"]


# -- HTTP adapter over loopback ---------------------------------------------------------------------
def _loopback_only(monkeypatch):
    def connect(self, address):
        if address[0] != "127.0.0.1":
            raise AssertionError("only loopback allowed")
        return _REAL_CONNECT(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)


def _raw_http(port, request: bytes) -> tuple[int, dict[str, str], bytes]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        sock.connect(("127.0.0.1", port))
        sock.sendall(request)
        chunks = []
        while chunk := sock.recv(65536):
            chunks.append(chunk)
    head, _, body = b"".join(chunks).partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    headers = dict(line.split(": ", 1) for line in lines[1:])
    return int(lines[0].split()[1]), headers, body


def _request(body: bytes, *, method="POST", path=PATH, extra="") -> bytes:
    return (f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n{extra}\r\n").encode() + body


def test_loopback_http_server(world, monkeypatch) -> None:
    _loopback_only(monkeypatch)
    sink = ListSink()
    httpd = server.build_server(world.data_root, "127.0.0.1", 0, logger=StructuredLogger(sink))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        status, headers, body = _raw_http(port, _request(json.dumps(at(A, 10, 20)).encode()))
        assert status == 200 and json.loads(body)["result"] == {"elevation_m": 12.34}
        assert headers["Content-Type"] == "application/json"
        assert headers["Cache-Control"] == "no-store" and int(headers["Content-Length"]) == len(body)
        status, headers, body = _raw_http(port, _request(b"", method="GET"))
        assert status == 405 and headers["Allow"] == "POST"
        status, _, body = _raw_http(port, _request(b"{}" + b" " * 5000))
        assert status == 413
        chunked = (f"POST {PATH} HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                   "Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n").encode()
        assert _raw_http(port, chunked)[0] == 415
        bad_length = (f"POST {PATH} HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\n"
                      "Content-Length: -1\r\n\r\n").encode()
        assert _raw_http(port, bad_length)[0] == 415
        assert _raw_http(port, _request(b"{}", path=PATH + "?lat=1"))[0] == 400
    finally:
        httpd.shutdown()
        httpd.server_close()
    text = json.dumps(sink.entries)
    assert "35.6" not in text and "139.7" not in text and PATH not in text


def test_server_refuses_fixture_roots_and_non_loopback_demo(harness, world) -> None:
    with pytest.raises(StartupError):
        server.build_server(harness.data_root, "127.0.0.1", 0)
    with pytest.raises(StartupError):
        server.build_server(harness.data_root, "0.0.0.0", 0, fixture_demo=True)
    httpd = server.build_server(harness.data_root, "127.0.0.1", 0, fixture_demo=True)
    httpd.server_close()


def test_main_exits_3_on_unverifiable_data(tmp_path, capsys) -> None:
    (tmp_path / "elevation/rel/registry/13").mkdir(parents=True)
    (tmp_path / "elevation/rel/registry/13/current.json").write_bytes(b"{")
    assert server.main(["--data-root", str(tmp_path), "--port", "0"]) == 3
    err = capsys.readouterr().err
    assert str(tmp_path) not in err and "not serving" in err


def test_settings_come_from_api_configuration() -> None:
    settings = server.load_settings()
    conf = json.loads((REPO / "api/elevation/conf/api.json").read_text())
    assert settings.request_body_max_bytes == conf["request_body_max_bytes"] == 1024
    assert settings.evaluation_timeout_ms == conf["evaluation_timeout_ms"]


def test_api_process_loads_no_pipeline_or_network_modules() -> None:
    code = ("import sys; import hererisk.elevation.api.server; "
            "print('\\n'.join(sorted(m for m in sys.modules if m.startswith('hererisk'))))")
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                          check=True, timeout=60)
    loaded = proc.stdout.split()
    # download.png is the pure PNG parser used by the format code; the Download
    # operation itself (download.download / transports / records) must not load.
    forbidden = ("hererisk.elevation.download.download", "hererisk.elevation.download.transport",
                 "hererisk.elevation.download.gsi_transport", "hererisk.elevation.download.record",
                 "hererisk.elevation.normalize.stage",
                 "hererisk.elevation.validate.stage", "hererisk.elevation.publish.stage",
                 "hererisk.elevation.gsi_poc", "hererisk.elevation.net",
                 "hererisk.common.orchestrator", "hererisk.common.authorization",
                 "hererisk.common.approval_store")
    assert not [m for m in loaded if m.startswith(forbidden)], loaded
