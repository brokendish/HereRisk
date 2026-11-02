"""Contract tests: Phase 3-G Docker Compose (container bind rule + static checks of compose.yaml).

The real container run (build, start, address search, elevation through the Compose network,
Data Inventory page) is a manual check (README "Docker Compose"); these tests cover the
``--container`` code rule and the safety properties of the deployment files.
"""

from __future__ import annotations

import re

import pytest

from e2e_support import REPO
from hererisk.common.api_auth import write_new_token_file
from hererisk.data_inventory import web
from hererisk.data_inventory.__main__ import main as inventory_cli
from hererisk.location import server as location_server
from hererisk.location.elevation_provider import ElevationConfigError, ElevationProvider

COMPOSE = (REPO / "compose.yaml").read_text(encoding="utf-8")
APP = REPO / "deploy" / "app"


def _service(name: str) -> str:
    """The block of one service in compose.yaml (up to the next top-level service key)."""
    match = re.search(rf"^  {name}:\n(.*?)(?=^  [a-z][a-z-]*:\n|^\S)", COMPOSE, re.M | re.S)
    assert match, name
    return "\n".join(l for l in match.group(1).splitlines() if not l.lstrip().startswith("#")) + "\n"


class FakeServer:
    daemon_threads = False
    bound: list = []

    def __init__(self, address, handler):
        FakeServer.bound.append(address)

    def server_close(self):
        pass


@pytest.fixture
def no_bind(monkeypatch):
    FakeServer.bound = []
    monkeypatch.setattr(location_server, "ThreadingHTTPServer", FakeServer)
    monkeypatch.setattr(web, "ThreadingHTTPServer", FakeServer)
    return FakeServer.bound


# --container: non-loopback bind only when asked for ----------------------------------------------
def test_location_api_container_bind(no_bind) -> None:
    with pytest.raises(ValueError):
        location_server.build_server("0.0.0.0", 8001)
    assert no_bind == []
    location_server.build_server("0.0.0.0", 8001, container=True)
    assert no_bind == [("0.0.0.0", 8001)]


def test_elevation_service_name_only_in_container_mode(tmp_path) -> None:
    with pytest.raises(ElevationConfigError):
        ElevationProvider("http://elevation-api:8000")
    ElevationProvider("http://elevation-api:8000", container=True)
    ElevationProvider("http://127.0.0.1:8000", container=True)
    for url in ("http://localhost:8000", "http://10.0.0.1:8000", "http://elevation-api",
                "https://elevation-api:8000", "http://elevation-api:8000/api", "http://u:p@elevation-api:8000",
                "http://data-inventory:8090"):
        with pytest.raises(ElevationConfigError):
            ElevationProvider(url, container=True)
    token = tmp_path / "api-token"
    write_new_token_file(token)
    provider = ElevationProvider("http://elevation-api:8000", token_file=token, container=True)
    assert provider._host == "elevation-api" and provider._port == 8000


def test_location_main_passes_container_flag(monkeypatch) -> None:
    calls = []

    def fake_build(*args, **kw):
        calls.append(kw["container"])
        raise ValueError("stop here")
    monkeypatch.setattr(location_server, "build_server", fake_build)
    assert location_server.main(["--host", "0.0.0.0", "--container"]) == 3
    assert location_server.main(["--host", "0.0.0.0"]) == 3
    assert calls == [True, False]


def test_data_inventory_container_bind(no_bind, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(web, "build_inventory", lambda regions, ledger: {"items": []})
    web.build_server(tmp_path / "regions.json", tmp_path / "ledger.json", 8090)
    web.build_server(tmp_path / "regions.json", tmp_path / "ledger.json", 8090, container=True)
    assert no_bind == [("127.0.0.1", 8090), ("0.0.0.0", 8090)]
    assert inventory_cli(["--regions", str(tmp_path / "regions.json"), "--container"]) == 2   # needs --serve


# compose.yaml ---------------------------------------------------------------------------------
def test_host_ports_are_loopback_only() -> None:
    ports = re.findall(r'^\s+- "([^"]*:\d+:\d+)"$', COMPOSE, re.M)
    assert sorted(ports) == ["127.0.0.1:8000:8000", "127.0.0.1:8001:8001", "127.0.0.1:8090:8090"]
    for forbidden in ("network_mode: host", "privileged", "docker.sock", "/var/run/docker", "cap_add",
                      "pid: host", "ipc: host", "0.0.0.0:", "--private-experiment", "--production"):
        assert forbidden not in COMPOSE, forbidden


def test_hardening_and_read_only_data() -> None:
    for required in ("read_only: true", "cap_drop:", "no-new-privileges:true", 'user: "10001:10001"'):
        assert required in COMPOSE, required
    for name in ("location-api", "data-inventory"):
        assert "${HERERISK_DATA_DIR:-${HOME}/hererisk-data}:/data:ro" in _service(name)
        assert "/data/regions.json" in _service(name)
    assert "elevation-data:/var/lib/hererisk:ro" in _service("elevation-api")
    assert "http://elevation-api:8000" in _service("location-api")
    assert "--elevation-fixture" in _service("location-api")          # fixture stays synthetic: true
    assert "--fixture-demo" in _service("elevation-api")


def test_data_inventory_is_admin_only_and_isolated() -> None:
    inv = _service("data-inventory")
    assert 'profiles: ["admin"]' in inv
    assert re.search(r"networks:\n\s+- admin\n", inv) and "public" not in inv
    assert "secrets:" not in inv                                      # no token for the page
    for name in ("location-api", "elevation-api"):
        svc = _service(name)
        assert "profiles:" not in svc and re.search(r"networks:\n\s+- public\n", svc) and "admin" not in svc
    assert "--serve" in inv and "--container" in inv


def test_healthchecks_use_existing_endpoints() -> None:
    assert "/api/v1/elevation" in _service("elevation-api")
    assert "/api/v1/location?" in _service("location-api")
    assert "/inventory.json" in _service("data-inventory")
    assert "/health" not in COMPOSE


def test_secret_and_data_defaults_outside_repository() -> None:
    defaults = re.findall(r"\$\{HERERISK_(?:SECRET|DATA)_DIR:-(\$\{HOME\}/[^}]+)\}", COMPOSE)
    assert sorted(set(defaults)) == ["${HOME}/.hererisk-local/secrets", "${HOME}/hererisk-data"]
    assert len(defaults) == COMPOSE.count("${HERERISK_SECRET_DIR:-") + COMPOSE.count("${HERERISK_DATA_DIR:-")


def test_image_contains_code_only() -> None:
    ignore = (APP / "Dockerfile.dockerignore").read_text().splitlines()
    assert ignore[0] == "*"   # allowlist: nothing enters the image unless listed
    assert {l for l in ignore if l.startswith("!")} == {
        "!src/hererisk", "!api/elevation/conf", "!docs/data-sources/official-source-ledger.json",
        "!tests/fixtures/elevation-fixture", "!deploy/app/requirements.txt", "!deploy/fixture-vps/init-fixture.sh"}
    dockerfile = (APP / "Dockerfile").read_text()
    assert "USER 10001:10001" in dockerfile and "ARG" not in dockerfile
    instructions = "\n".join(l for l in dockerfile.splitlines() if not l.lstrip().startswith("#"))
    assert "secret" not in instructions.lower() and "token" not in instructions.lower()
    for text in (COMPOSE, dockerfile):
        assert not re.search(r"[A-Za-z0-9_-]{43,}", text.replace("hererisk", "")) and "Bearer ey" not in text


def test_requirements_pinned_binary() -> None:
    reqs = dict(line.split("==") for line in (APP / "requirements.txt").read_text().split())
    assert reqs["pypng"] == "0.20220715.0" and reqs["jsonschema"].startswith("4.")
    assert reqs["shapely"].startswith("2.") and "numpy" in reqs
    fixture_reqs = dict(line.split("==") for line in
                        (REPO / "deploy" / "fixture-vps" / "requirements.txt").read_text().split())
    assert all(reqs[k] == v for k, v in fixture_reqs.items())   # same versions as Phase 1-I
    assert "--only-binary=:all:" in (APP / "Dockerfile").read_text()
