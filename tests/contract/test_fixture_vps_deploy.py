"""Contract tests: Phase 1-I fixture deployment (container bind rule + static checks).

The real container run (build, init, 200/401, restart) is an OWNER / manual
acceptance step (docs/operations/elevation-fixture-vps-runbook-v0.1.md); these
tests cover the code rule and the safety properties of the deployment files.
"""

from __future__ import annotations

import re

import pytest

from e2e_support import REPO
from hererisk.common.api_auth import write_new_token_file
from hererisk.elevation.api import server
from hererisk.elevation.api.published import StartupError

DEPLOY = REPO / "deploy" / "fixture-vps"


@pytest.fixture
def published_fixture(harness):
    from hererisk.common.orchestrator import DownloadRequest
    from hererisk.elevation.normalize.stage import NormalizeStage
    from hererisk.elevation.publish.stage import PublishStage
    from hererisk.elevation.validate.stage import ValidateStage

    orch = harness.orchestrator(stages={"elevation": (NormalizeStage(), ValidateStage(),
                                                      PublishStage())})
    results = orch.run_fixture_pipeline(DownloadRequest("elevation", ("13",),
                                                        "fixture-dem-png-tokyo"))
    assert results[-1].status.value == "SUCCESS"
    return harness.data_root


@pytest.fixture
def no_bind(monkeypatch):
    bound = []

    class FakeServer:
        daemon_threads = False

        def __init__(self, address, handler):
            bound.append(address)

        def server_close(self):
            pass

    monkeypatch.setattr(server, "ThreadingHTTPServer", FakeServer)
    return bound


def test_container_bind_needs_fixture_demo_and_token(published_fixture, tmp_path, no_bind) -> None:
    token = tmp_path / "api-token"
    write_new_token_file(token)
    root = published_fixture
    with pytest.raises(StartupError):  # non-loopback demo without --container
        server.build_server(root, "0.0.0.0", 8000, fixture_demo=True, auth_token_file=token)
    with pytest.raises(StartupError):  # --container without a token
        server.build_server(root, "0.0.0.0", 8000, fixture_demo=True, container=True)
    with pytest.raises(StartupError):  # --container is fixture only
        server.build_server(root, "0.0.0.0", 8000, container=True, auth_token_file=token)
    with pytest.raises(StartupError):
        server.build_server(root, "0.0.0.0", 8000, private_experiment=True, container=True,
                            auth_token_file=token)
    assert no_bind == []
    httpd = server.build_server(root, "0.0.0.0", 8000, fixture_demo=True, container=True,
                                auth_token_file=token)
    assert no_bind == [("0.0.0.0", 8000)]
    httpd.server_close()


def test_container_mode_requires_valid_token_file(published_fixture, tmp_path, no_bind) -> None:
    import os

    token = tmp_path / "api-token"
    write_new_token_file(token)
    os.chmod(token, 0o644)
    with pytest.raises(StartupError):
        server.build_server(published_fixture, "0.0.0.0", 8000, fixture_demo=True,
                            container=True, auth_token_file=token)
    assert no_bind == []


def test_main_container_flag_exit_codes(published_fixture) -> None:
    assert server.main(["--data-root", str(published_fixture), "--host", "0.0.0.0",
                        "--port", "0", "--fixture-demo", "--container"]) == 3


# -- static checks of the deployment files -------------------------------------------------------
def _text(name):
    return (DEPLOY / name).read_text(encoding="utf-8")


def test_compose_isolation_and_hardening() -> None:
    compose = _text("compose.yaml")
    assert re.search(r"^name: hererisk-fixture$", compose, re.M)
    assert '"127.0.0.1:18080:8000"' in compose
    assert len(re.findall(r"^\s+- \"?[0-9.]*:?\d+:\d+\"?$", compose, re.M)) == 1  # one port
    for forbidden in ("network_mode: host", "privileged", "docker.sock", "/var/run/docker",
                      "8000:8000", "0.0.0.0:18080", "cap_add", "pid: host", "ipc: host"):
        assert forbidden not in compose, forbidden
    assert compose.count("network_mode: none") == 2  # init / token: no network at all
    for required in ("read_only: true", "cap_drop:", "no-new-privileges:true",
                     'user: "10001:10001"', "mem_limit: 256m", "restart: unless-stopped",
                     "data:/var/lib/hererisk:ro", "container_name: hererisk-fixture-api",
                     "name: hererisk-fixture-data", "--fixture-demo", "--auth-token-file"):
        assert required in compose, required
    assert "--private-experiment" not in compose and "--production" not in compose
    names = re.findall(r"container_name: (\S+)", compose) + re.findall(r"^\s+name: (\S+)$",
                                                                       compose, re.M)
    assert all(n.startswith("hererisk-fixture") for n in names), names


def test_no_secret_or_real_data_in_deployment_files() -> None:
    for name in ("compose.yaml", "Dockerfile", "init-fixture.sh", "Dockerfile.dockerignore",
                 "requirements.txt"):
        text = _text(name)
        assert not re.search(r"[A-Za-z0-9_-]{43,}", text.replace("hererisk", "")), name
        assert "Bearer " not in text and "gsi-dem10b" not in text, name
        assert "cyberjapandata" not in text, name
    dockerfile = _text("Dockerfile")
    assert "USER 10001:10001" in dockerfile and "ARG" not in dockerfile
    instructions = "\n".join(l for l in dockerfile.splitlines() if not l.lstrip().startswith("#"))
    assert "secret" not in instructions.lower() and "token" not in instructions.lower()
    ignore = _text("Dockerfile.dockerignore").splitlines()
    assert ignore[0] == "*"  # allowlist: nothing enters the image unless listed
    assert set(l for l in ignore if l.startswith("!")) == {
        "!src/hererisk", "!api/elevation/conf", "!tests/fixtures/elevation-fixture",
        "!deploy/fixture-vps/requirements.txt", "!deploy/fixture-vps/init-fixture.sh"}


def test_secret_location_defaults_outside_repository() -> None:
    compose = _text("compose.yaml")
    defaults = re.findall(r"\$\{HERERISK_FIXTURE_SECRET_DIR:-([^}]+)\}", compose)
    assert defaults and all(d == "/srv/hererisk-fixture/secrets" for d in defaults)


def test_init_script_never_deletes() -> None:
    script = _text("init-fixture.sh")
    for forbidden in ("rm ", "rm\t", "--replace", "truncate", "> \"$root", "mv "):
        assert forbidden not in script, forbidden
    assert "already initialised; nothing changed" in script
    assert "fixture-dem-png-tokyo" in script and "--fixture /app/fixtures/elevation-fixture" in script


def test_requirements_match_pyproject_pins() -> None:
    reqs = dict(line.split("==") for line in _text("requirements.txt").split())
    assert reqs["pypng"] == "0.20220715.0"
    major = int(reqs["jsonschema"].split(".")[0])
    assert major == 4
