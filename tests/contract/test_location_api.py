"""Location API v0.1 (Phase 3-A) minimal tests: docs/api/location-api-v0.1.md."""

from __future__ import annotations

import json
import socket
import threading
import time

import pytest

from hererisk.location import server
from hererisk.location.api import PATH, LocationApi
from hererisk.location.model import HAZARDS
from hererisk.location.orchestrator import Orchestrator
from hererisk.location.providers import default_providers, sample_providers

_REAL_CONNECT = socket.socket.connect
TOKYO = "lat=35.681236&lon=139.767125"


def mock_api(**overrides) -> LocationApi:
    providers = default_providers()
    providers.update(overrides)
    return LocationApi(Orchestrator(providers, mode="mock", allow_synthetic=False, timeout_s=0.5))


def sections(doc):
    return {"address": doc["address"], "elevation": doc["elevation"], **doc["hazards"]}


class Fixed:
    def __init__(self, pid, section):
        self.id, self._section = pid, section

    def lookup(self, lat, lon):
        return {"provider": self.id, "synthetic": False, **self._section}


class Boom:
    id = "flood"

    def lookup(self, lat, lon):
        raise RuntimeError("/secret/path/token=abc")


class Slow:
    id = "tsunami"

    def lookup(self, lat, lon):
        time.sleep(2)
        return {"status": "no_match"}


# 1. valid point --------------------------------------------------------------------------------
def test_valid_point_returns_all_sections() -> None:
    r = mock_api().handle("GET", PATH, TOKYO)
    doc = r.json()
    assert r.status == 200 and r.headers["Cache-Control"] == "no-store"
    assert doc["location"] == {"lat": 35.681236, "lon": 139.767125}   # named axes, never swapped
    assert set(doc) >= {"schema_version", "mode", "location", "address", "elevation", "hazards"}
    assert set(doc["hazards"]) == set(HAZARDS)


# 2. invalid input -------------------------------------------------------------------------------
@pytest.mark.parametrize("query", [
    "", "lat=35", "lon=139", "lat=91&lon=0", "lat=0&lon=181", "lat=-90.1&lon=0", "lat=abc&lon=1",
    "lat=nan&lon=1", "lat=inf&lon=1", "lat=1e1&lon=1", "lat=&lon=1", "lat=1&lat=2&lon=3",
    "lat=1&lon=2&x=3", "lat=+1&lon=2", "lat=0x1&lon=2", "lat=1,2&lon=3"])
def test_invalid_input_is_422(query) -> None:
    r = mock_api().handle("GET", PATH, query)
    assert r.status == 422 and r.json()["error"]["code"] == "invalid_input"


def test_bounds_are_accepted_and_path_method_checked() -> None:
    api = mock_api()
    assert api.handle("GET", PATH, "lat=-90&lon=180").status == 200
    assert api.handle("GET", PATH, "lat=90.0&lon=-180.0").status == 200
    assert api.handle("GET", "/api/v1/other", TOKYO).status == 404
    r = api.handle("POST", PATH, TOKYO)
    assert r.status == 405 and r.headers["Allow"] == "GET"


# 3 + 4. every section has a state; not connected -> not_available ------------------------------
def test_unconnected_providers_are_not_available() -> None:
    doc = mock_api().handle("GET", PATH, TOKYO).json()
    assert doc["mode"] == "mock"
    for name, s in sections(doc).items():
        assert s["status"] == "not_available", name
        assert "results" not in s or s["results"] is None   # never an empty list that reads as "nothing"
        assert "安全" in s["notice"]
    assert doc["elevation"].get("result") is None          # not 0 m


# 5. one provider failing does not remove the others ---------------------------------------------
def test_single_provider_failure_keeps_other_sections() -> None:
    ok = Fixed("tsunami", {"status": "no_match", "results": [], "searched_sources": [{"source_id": "s"}]})
    r = mock_api(flood=Boom(), tsunami=ok)
    doc = r.handle("GET", PATH, TOKYO).json()
    assert doc["hazards"]["flood"]["status"] == "error"
    assert doc["hazards"]["flood"]["error"]["code"] == "provider_failed"
    assert doc["hazards"]["tsunami"]["status"] == "no_match"
    assert doc["address"]["status"] == "not_available"
    text = json.dumps(doc)
    assert "secret" not in text and "token" not in text and "RuntimeError" not in text


def test_timeout_is_an_error_section() -> None:
    started = time.monotonic()
    doc = mock_api(tsunami=Slow()).handle("GET", PATH, TOKYO).json()
    assert time.monotonic() - started < 1.5
    assert doc["hazards"]["tsunami"]["error"]["code"] == "timeout"
    assert doc["hazards"]["flood"]["status"] == "not_available"


# 6. several official results are kept as an array ------------------------------------------------
def test_multiple_official_results_are_kept_separately() -> None:
    results = [{"source": {"source_id": "a"}, "feature_ref": "f1", "original_class": {"code": "3", "label": "3.0～5.0m未満"}},
               {"source": {"source_id": "b"}, "feature_ref": "f2", "original_class": {"code": "2", "label": "0.5～3.0m未満"}}]
    doc = mock_api(flood=Fixed("flood", {"status": "available", "results": results})).handle("GET", PATH, TOKYO).json()
    flood = doc["hazards"]["flood"]
    assert flood["status"] == "available" and flood["results"] == results   # unchanged, no max / representative
    assert not {"max", "maximum", "representative", "level", "risk"} & set(flood)


# 7. unknown / no_match are never shown as safe; broken shapes become error ---------------------
@pytest.mark.parametrize("section", [
    {"status": "no_match", "results": []},                        # no_match without the searched data
    {"status": "available", "results": []},                       # "available" with nothing in it
    {"status": "unknown", "results": []},                         # unknown disguised as an empty list
    {"status": "safe", "results": []},                            # not a contract state
    {"status": "not_available", "results": []},
])
def test_ambiguous_or_safe_looking_sections_become_error(section) -> None:
    doc = mock_api(flood=Fixed("flood", section)).handle("GET", PATH, TOKYO).json()
    assert doc["hazards"]["flood"]["status"] == "error"
    assert doc["hazards"]["flood"]["error"]["code"] == "invalid_provider_result"


def test_no_match_and_unknown_carry_not_safe_notices() -> None:
    nm = Fixed("tsunami", {"status": "no_match", "results": [], "searched_sources": [{"source_id": "s"}]})
    un = Fixed("storm_surge", {"status": "unknown", "results": None})
    doc = mock_api(tsunami=nm, storm_surge=un).handle("GET", PATH, TOKYO).json()
    assert "安全であることを意味しません" in doc["hazards"]["tsunami"]["notice"]
    assert doc["hazards"]["storm_surge"]["results"] is None
    assert "確定できません" in doc["hazards"]["storm_surge"]["notice"]


def test_elevation_zero_is_a_value_and_missing_is_not_zero() -> None:
    zero = Fixed("elevation", {"status": "available", "result": {"elevation_m": 0, "unit": "m"}})
    doc = mock_api(elevation=zero).handle("GET", PATH, TOKYO).json()
    assert doc["elevation"]["status"] == "available" and doc["elevation"]["result"]["elevation_m"] == 0
    missing = Fixed("elevation", {"status": "available", "result": {"elevation_m": None, "unit": "m"}})
    assert mock_api(elevation=missing).handle("GET", PATH, TOKYO).json()["elevation"]["status"] == "error"


# 8. synthetic sample data stays marked and cannot leak into the default mode -------------------
def test_sample_mode_marks_everything_synthetic() -> None:
    api = LocationApi(Orchestrator(sample_providers(), mode="sample", allow_synthetic=True))
    doc = api.handle("GET", PATH, TOKYO).json()
    assert doc["mode"] == "sample"
    states = {name: s["status"] for name, s in sections(doc).items()}
    assert set(states.values()) == {"available", "no_match", "unknown", "not_available"}
    for name, s in sections(doc).items():
        if s["status"] != "not_available":
            assert s["synthetic"] is True and "合成データ" in s["sample_note"], name
            assert s["notice"].startswith("【合成データ】"), name
    assert len(doc["hazards"]["flood"]["results"]) == 2


def test_synthetic_section_is_refused_outside_sample_mode() -> None:
    providers = sample_providers()
    doc = LocationApi(Orchestrator(providers, mode="mock", allow_synthetic=False)).handle("GET", PATH, TOKYO).json()
    for name, s in sections(doc).items():
        assert s["status"] in ("error", "not_available"), name
        assert s.get("synthetic") is not True


# HTTP server ----------------------------------------------------------------------------------
def _get(port, target, method="GET"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        sock.connect(("127.0.0.1", port))
        sock.sendall(f"{method} {target} HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n".encode())
        data = b""
        while chunk := sock.recv(65536):
            data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    return int(head.split()[1]), body


def test_loopback_http_server(monkeypatch) -> None:
    monkeypatch.setattr(socket.socket, "connect",
                        lambda self, addr: _REAL_CONNECT(self, addr) if addr[0] == "127.0.0.1" else (_ for _ in ()).throw(AssertionError))
    httpd = server.build_server("127.0.0.1", 0)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        status, body = _get(port, f"{PATH}?{TOKYO}")
        assert status == 200 and json.loads(body)["hazards"]["flood"]["status"] == "not_available"
        assert _get(port, f"{PATH}?lat=999&lon=0")[0] == 422
    finally:
        httpd.shutdown()
        httpd.server_close()
    with pytest.raises(ValueError):
        server.build_server("0.0.0.0", 0)
