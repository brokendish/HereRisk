"""Contract tests: shared Bearer token authentication (Phase 1-G).

Tokens are generated into temporary files by the tests; none is a real secret.
The HTTP test opens loopback sockets only; GSI is never contacted.
"""

from __future__ import annotations

import json
import os
import socket
import threading

import pytest

from e2e_support import PRIVATE_APPROVAL_ID, REPO, TOKYO_TILES, World, centre, png_with, post
from hererisk.common.api_auth import (
    BearerAuth,
    TokenFileError,
    read_token_file,
    remove_token,
    write_new_token_file,
)
from hererisk.common.authorization import ExecutionContext
from hererisk.common.logging import ListSink, StructuredLogger
from hererisk.elevation.api import server
from hererisk.elevation.api.handler import ERRORS, PATH
from hererisk.elevation.api.published import StartupError

_REAL_CONNECT = socket.socket.connect  # saved before the autouse network guard
A = TOKYO_TILES[0]
BODIES = {A: png_with({(10, 20): (0, 4, 210)})}
KEYS = {"hazard", "location", "status", "result", "dataset", "error", "evaluated_at"}


def token_file(tmp_path, name="api-token"):
    path = tmp_path / name
    write_new_token_file(path)
    return path, read_token_file(path)[0]


def auth_headers(token, **extra):
    return {"Content-Type": "application/json", "Authorization": f"Bearer {token}", **extra}


@pytest.fixture
def private(tmp_path):
    (tmp_path / "w").mkdir()
    world = World(tmp_path / "w", BODIES, approval_ref=PRIVATE_APPROVAL_ID,
                  context=ExecutionContext.PRIVATE_EXPERIMENT)
    world.use_store()
    assert world.run()[-1].status.value == "SUCCESS"
    return world


# -- token file ----------------------------------------------------------------------------------
def test_generated_token_file(tmp_path) -> None:
    path, token = token_file(tmp_path)
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert len(token) >= 43 and path.read_text() == token + "\n"
    with pytest.raises(FileExistsError):
        write_new_token_file(path)  # never overwritten


def test_rotation_add_then_retire(tmp_path) -> None:
    path, old = token_file(tmp_path)
    write_new_token_file(path, append=True)
    old_again, new = read_token_file(path)
    assert old_again == old and new != old
    assert os.stat(path).st_mode & 0o777 == 0o600
    both = BearerAuth.from_file(path)
    assert both.check({"Authorization": f"Bearer {old}"})
    assert both.check({"Authorization": f"Bearer {new}"})
    with pytest.raises(TokenFileError):
        write_new_token_file(path, append=True)  # never three tokens
    remove_token(path, keep="newest")
    assert read_token_file(path) == [new]
    only_new = BearerAuth.from_file(path)
    assert not only_new.check({"Authorization": f"Bearer {old}"})
    assert only_new.check({"Authorization": f"Bearer {new}"})
    assert not list(tmp_path.glob(".api-token.tmp-*"))


@pytest.mark.parametrize("damage", [
    lambda p: p.unlink(),
    lambda p: os.chmod(p, 0o644),
    lambda p: os.chmod(p, 0o640),
    lambda p: os.chmod(p, 0o604),
    lambda p: os.link(p, p.with_name("alias")),
    lambda p: p.write_text(""),
    lambda p: p.write_text("short\n"),
    lambda p: p.write_text("a" * 43 + "\n" + "a" * 43 + "\n"),        # duplicate
    lambda p: p.write_text("\n".join(["a" * 43, "b" * 43, "c" * 43]) + "\n"),  # three
    lambda p: p.write_text("a" * 43 + " \n"),                        # trailing space
    lambda p: p.write_bytes(("é" * 43).encode()),
    lambda p: p.write_text("a" * 5000),
], ids=["missing", "0644", "0640", "0604", "hardlink", "empty", "short", "duplicate",
        "three", "space", "non-ascii", "too-large"])
def test_untrusted_or_malformed_token_file(tmp_path, damage) -> None:
    path, _ = token_file(tmp_path)
    damage(path)
    with pytest.raises(TokenFileError):
        BearerAuth.from_file(path)


def test_symlinked_token_file_is_refused(tmp_path) -> None:
    real, _ = token_file(tmp_path, "real")
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(TokenFileError):
        BearerAuth.from_file(link)


def test_read_only_0400_is_accepted(tmp_path) -> None:
    path, token = token_file(tmp_path)
    os.chmod(path, 0o400)
    assert BearerAuth.from_file(path).check({"Authorization": f"Bearer {token}"})


# -- header check ------------------------------------------------------------------------------
@pytest.mark.parametrize("headers,ok", [
    (lambda t: {"Authorization": f"Bearer {t}"}, True),
    (lambda t: {"authorization": f"bearer {t}"}, True),
    (lambda t: {}, False),
    (lambda t: {"Authorization": ""}, False),
    (lambda t: {"Authorization": "Bearer"}, False),
    (lambda t: {"Authorization": f"Bearer  {t}"}, False),
    (lambda t: {"Authorization": f"Bearer {t} "}, False),
    (lambda t: {"Authorization": f"Basic {t}"}, False),
    (lambda t: {"Authorization": f"Bearer {t[:-1]}x"}, False),
    (lambda t: {"Authorization": f"Bearer {t}", "authorization": f"Bearer {t}"}, False),
    (lambda t: {"X-Api-Key": t}, False),
])
def test_bearer_header_rules(tmp_path, headers, ok) -> None:
    path, token = token_file(tmp_path)
    assert BearerAuth.from_file(path).check(headers(token)) is ok


# -- handler -----------------------------------------------------------------------------------
def test_authenticated_request_succeeds(private) -> None:
    path, token = token_file(private.tmp)
    api = private.api(auth=BearerAuth.from_file(path))
    lat, lon = centre(*A, 10, 20)
    resp = post(api, {"lat": lat, "lon": lon}, headers=auth_headers(token))
    assert resp.status == 200 and resp.json()["result"] == {"elevation_m": 12.34}


@pytest.mark.parametrize("method,path_", [("POST", PATH), ("GET", PATH), ("POST", "/x")])
def test_unauthenticated_is_401_before_anything_else(private, monkeypatch, method, path_) -> None:
    path, token = token_file(private.tmp)
    sink = ListSink()
    api = private.api(sink=sink, auth=BearerAuth.from_file(path))

    def must_not_run(*a, **k):
        raise AssertionError("published data touched before authentication")

    monkeypatch.setattr(api._published, "covering", must_not_run)
    monkeypatch.setattr(api._published, "read_entity", must_not_run)
    lat, lon = centre(*A, 10, 20)
    for headers in ({"Content-Type": "application/json"},
                    auth_headers("x" * 43), auth_headers(token[:-2])):
        resp = post(api, None, raw=json.dumps({"lat": lat, "lon": lon}).encode() + b" " * 5000,
                    headers=headers, method=method, path=path_)
        doc = resp.json()
        assert resp.status == 401 and set(doc) == KEYS
        assert doc["status"] == "invalid_request" and doc["error"] == {
            "code": "unauthorized", "message": ERRORS["unauthorized"][2]}
        assert doc["location"] is None and doc["evaluated_at"] is None and doc["dataset"] is None
        assert resp.headers["WWW-Authenticate"] == "Bearer"
        assert resp.headers["Cache-Control"] == "no-store"
    text = json.dumps(sink.entries)
    assert token not in text and "Bearer" not in text and "Authorization" not in text
    assert repr(lat)[:6] not in text and repr(lon)[:6] not in text
    assert {e["error_code"] for e in sink.entries} == {"unauthorized"}


def test_logs_never_contain_token_on_success(private) -> None:
    path, token = token_file(private.tmp)
    sink = ListSink()
    api = private.api(sink=sink, auth=BearerAuth.from_file(path))
    lat, lon = centre(*A, 10, 20)
    post(api, {"lat": lat, "lon": lon}, headers=auth_headers(token))
    text = json.dumps(sink.entries)
    assert token not in text and "Bearer" not in text and repr(lat)[:6] not in text


def test_without_auth_configured_behaviour_is_unchanged(private) -> None:
    api = private.api()  # handler without auth (fixture demo / existing public mode)
    lat, lon = centre(*A, 10, 20)
    assert post(api, {"lat": lat, "lon": lon}).status == 200


# -- server ------------------------------------------------------------------------------------
def test_private_server_requires_a_valid_token_file(private, capsys) -> None:
    with pytest.raises(StartupError):
        server.build_server(private.data_root, "127.0.0.1", 0, private_experiment=True)
    path, token = token_file(private.tmp)
    os.chmod(path, 0o644)
    with pytest.raises(StartupError):
        server.build_server(private.data_root, "127.0.0.1", 0, private_experiment=True,
                            auth_token_file=path)
    with pytest.raises(StartupError):  # never from inside the repository
        server.build_server(private.data_root, "127.0.0.1", 0, private_experiment=True,
                            auth_token_file=REPO / "README.md")
    assert server.main(["--data-root", str(private.data_root), "--port", "0",
                        "--private-experiment"]) == 3
    assert server.main(["--data-root", str(private.data_root), "--port", "0",
                        "--private-experiment", "--auth-token-file", str(path)]) == 3
    captured = capsys.readouterr()
    assert token not in captured.err + captured.out and str(path) not in captured.err


def _loopback_only(monkeypatch):
    def connect(self, address):
        if address[0] != "127.0.0.1":
            raise AssertionError("only loopback allowed")
        return _REAL_CONNECT(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)


def _raw(port, request: bytes):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(5)
        sock.connect(("127.0.0.1", port))
        sock.sendall(request)
        chunks = []
        while chunk := sock.recv(65536):
            chunks.append(chunk)
    head, _, body = b"".join(chunks).partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    return int(lines[0].split()[1]), dict(line.split(": ", 1) for line in lines[1:]), body


def _req(body: bytes, *auth_lines: str) -> bytes:
    extra = "".join(f"Authorization: {a}\r\n" for a in auth_lines)
    return (f"POST {PATH} HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n{extra}\r\n").encode() + body


def test_private_server_over_loopback(private, monkeypatch) -> None:
    _loopback_only(monkeypatch)
    path, token = token_file(private.tmp)
    sink = ListSink()
    httpd = server.build_server(private.data_root, "127.0.0.1", 0, private_experiment=True,
                                auth_token_file=path, logger=StructuredLogger(sink))
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    lat, lon = centre(*A, 10, 20)
    body = json.dumps({"lat": lat, "lon": lon}).encode()
    try:
        status, headers, out = _raw(port, _req(body, f"Bearer {token}"))
        assert status == 200 and json.loads(out)["result"] == {"elevation_m": 12.34}
        for auth in ((), ("Bearer " + "y" * 43,), (f"Bearer {token}", f"Bearer {token}"),
                     (f"Basic {token}",)):
            status, headers, out = _raw(port, _req(body, *auth))
            assert status == 401 and headers["WWW-Authenticate"] == "Bearer", auth
            assert json.loads(out)["error"]["code"] == "unauthorized"
            assert token.encode() not in out
    finally:
        httpd.shutdown()
        httpd.server_close()
    text = json.dumps(sink.entries)
    assert token not in text and "Bearer" not in text and repr(lat)[:6] not in text


def test_public_and_fixture_modes_accept_an_optional_token(harness, tmp_path) -> None:
    path, _ = token_file(tmp_path)
    httpd = server.build_server(harness.data_root, "127.0.0.1", 0, fixture_demo=True,
                                auth_token_file=path)
    httpd.server_close()
    httpd = server.build_server(harness.data_root, "127.0.0.1", 0, fixture_demo=True)
    httpd.server_close()  # fixture demo without a token: unchanged


# -- CLI ----------------------------------------------------------------------------------------
def test_cli_token_commands(tmp_path) -> None:
    from test_cli import cli

    path = tmp_path / "api-token"
    proc = cli("api-token-generate", "--output", str(path))
    assert proc.returncode == 0 and os.stat(path).st_mode & 0o777 == 0o600
    token = read_token_file(path)[0]
    assert token not in proc.stdout + proc.stderr
    assert cli("api-token-generate", "--output", str(path)).returncode == 2  # exists
    rotate = cli("api-token-generate", "--output", str(path), "--append")
    assert rotate.returncode == 0 and len(read_token_file(path)) == 2
    assert all(t not in rotate.stdout for t in read_token_file(path))
    assert cli("api-token-retire", "--file", str(path), "--keep", "newest").returncode == 0
    assert read_token_file(path) != [token] and len(read_token_file(path)) == 1
    assert cli("api-token-generate", "--output", str(REPO / "api-token")).returncode == 2
    assert not (REPO / "api-token").exists()


def test_valid_token_file_inside_repository_is_refused(private, monkeypatch) -> None:
    fake_repo = private.tmp / "fake-repo"
    fake_repo.mkdir()
    path, _ = token_file(fake_repo)  # valid 0600 token file, but "inside the repository"
    monkeypatch.setattr(server, "REPO_ROOT", fake_repo)
    with pytest.raises(StartupError):
        server.load_auth(path, required=True)
    monkeypatch.undo()
    assert server.load_auth(path, required=True) is not None  # same file outside: accepted
