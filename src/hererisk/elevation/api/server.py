"""HTTP adapter for the public elevation API (standard library ``http.server``).

    python -m hererisk.elevation.api.server --data-root <published data root> \
        [--host 127.0.0.1] [--port 8000]

* inbound HTTP only; no outbound connections are made by the API process
* the published snapshot is loaded and verified at startup; failure -> exit 3,
  the service never answers with unverified data
* fixture data roots are refused unless ``--fixture-demo`` is given, which is
  only allowed on a loopback address (local development demo)
* ``--private-experiment`` (Phase 1-G) serves only a private experiment data
  root (``init-private-root``), only on a loopback address, and only with
  ``--auth-token-file`` (shared Bearer token, ``hererisk.common.api_auth``);
  without the flag, private roots are refused. A TLS-terminating reverse proxy
  (Caddy) on the same host forwards authenticated requests to the loopback port
* ``--container`` (Phase 1-I, fixture demo only): inside a container the API
  must bind a non-loopback address to be reachable through the published
  port, so ``--fixture-demo --container`` allows that, and only together with
  ``--auth-token-file``. Host exposure is then decided by the container port
  mapping (``127.0.0.1:<port>`` in the HereRisk Compose file). Private and
  public modes are unchanged (private stays loopback only)
* ``--auth-token-file`` may also be given in the other modes; then every
  request needs the token. Unauthenticated requests get 401 before the body is
  read and before any published data is touched
* the request body is read bounded (max + 1 bytes); no request line, path,
  query, body or position is logged (the stdlib access log is disabled)
* settings come from ``api/elevation/conf/api.json`` via the Configuration Manager
"""

from __future__ import annotations

import argparse
import ipaddress
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Sequence
from urllib.parse import urlsplit

from hererisk.common.api_auth import BearerAuth, TokenFileError
from hererisk.common.config import ConfigurationError, ConfigurationManager
from hererisk.common.storage import is_within
from hererisk.common.logging import StructuredLogger
from hererisk.elevation.api.handler import ElevationApi, Settings
from hererisk.elevation.api.published import PublishedSet, StartupError

REPO_ROOT = Path(__file__).resolve().parents[4]
SOCKET_TIMEOUT_S = 10


def load_settings(repo_root: Path = REPO_ROOT) -> Settings:
    data = ConfigurationManager(repo_root, repo_root).load("api", "elevation", "api").data
    return Settings(request_body_max_bytes=data["request_body_max_bytes"],
                    evaluation_timeout_ms=data["evaluation_timeout_ms"])


def make_handler(api: ElevationApi, max_body: int):
    class Handler(BaseHTTPRequestHandler):
        server_version = "HereRisk"
        sys_version = ""
        timeout = SOCKET_TIMEOUT_S

        def log_message(self, format, *args):  # noqa: A002 - would log path / query
            return

        def log_error(self, format, *args):  # noqa: A002
            return

        def _dispatch(self) -> None:
            parts = urlsplit(self.path)
            headers = dict(self.headers.items())
            if len(self.headers.get_all("Authorization") or []) > 1:
                headers["Authorization"] = ""  # ambiguous credentials are never accepted
            if not api.authenticated(headers):
                # 401 without reading the body (nothing of the request is used).
                self._send(api.handle(self.command, parts.path, parts.query, headers, b""))
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or self.headers.get("Transfer-Encoding"):
                body = b""
                headers["Content-Type"] = "invalid/unsupported"  # unsupported framing -> 415
            else:
                body = self.rfile.read(min(length, max_body + 1)) if length else b""
            self._send(api.handle(self.command, parts.path, parts.query, headers, body))

        def _send(self, response) -> None:
            self.close_connection = True
            self.send_response(response.status)
            for name, value in response.headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(response.body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(response.body)

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = _dispatch

    return Handler


def load_auth(token_file: Path | None, *, required: bool) -> BearerAuth | None:
    if token_file is None:
        if required:
            raise StartupError("a Bearer token file is required in this mode")
        return None
    if is_within(Path(token_file), REPO_ROOT):
        raise StartupError("the token file must be outside the repository")
    try:
        return BearerAuth.from_file(Path(token_file))
    except TokenFileError as exc:
        raise StartupError("token file rejected") from exc


def build_server(data_root: Path, host: str, port: int, *, fixture_demo: bool = False,
                 private_experiment: bool = False, auth_token_file: Path | None = None,
                 container: bool = False,
                 logger: StructuredLogger | None = None) -> ThreadingHTTPServer:
    if fixture_demo and private_experiment:
        raise StartupError("--fixture-demo and --private-experiment are exclusive")
    if container and (not fixture_demo or auth_token_file is None):
        raise StartupError("--container is only for --fixture-demo with --auth-token-file")
    loopback = ipaddress.ip_address(host).is_loopback
    if private_experiment and not loopback:
        raise StartupError("the private mode is only allowed on a loopback address")
    if fixture_demo and not loopback and not container:
        raise StartupError("the fixture demo is only allowed on a loopback address")
    auth = load_auth(auth_token_file, required=private_experiment or container)
    settings = load_settings()
    published = PublishedSet.load(data_root, allow_fixture_root=fixture_demo,
                                  private_experiment=private_experiment)
    api = ElevationApi(published, settings, logger or StructuredLogger(), auth=auth)
    server = ThreadingHTTPServer((host, port), make_handler(api, settings.request_body_max_bytes))
    server.daemon_threads = True
    return server


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hererisk-elevation-api")
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--private-base", type=Path,
                        help="with --private-experiment: OWNER private base "
                             "(data root and token file are derived from it)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--fixture-demo", action="store_true",
                        help="serve a fixture data root (loopback only, local demo)")
    parser.add_argument("--private-experiment", action="store_true",
                        help="serve a private experiment data root (loopback only; "
                             "requires --auth-token-file)")
    parser.add_argument("--container", action="store_true",
                        help="fixture demo inside a container: allow a non-loopback bind "
                             "(requires --auth-token-file; expose only via 127.0.0.1 port mapping)")
    parser.add_argument("--auth-token-file", type=Path,
                        help="shared Bearer token file (outside Git, 0600)")
    args = parser.parse_args(argv)
    logger = StructuredLogger()
    if args.private_base is not None:
        if not args.private_experiment or args.data_root is not None \
                or args.auth_token_file is not None:
            sys.stderr.write("hererisk-elevation-api: --private-base needs --private-experiment "
                             "and replaces --data-root / --auth-token-file\n")
            return 2
        args.data_root = args.private_base / "data"
        args.auth_token_file = args.private_base / "secrets" / "api-token"
    if args.data_root is None:
        sys.stderr.write("hererisk-elevation-api: --data-root or --private-base is required\n")
        return 2
    try:
        server = build_server(args.data_root, args.host, args.port,
                              fixture_demo=args.fixture_demo,
                              private_experiment=args.private_experiment,
                              auth_token_file=args.auth_token_file, container=args.container,
                              logger=logger)
    except (StartupError, ConfigurationError, ValueError, OSError):
        sys.stderr.write("hererisk-elevation-api: published data or settings invalid; not serving\n")
        return 3
    logger.bind(module="elevation-api", api_id="elevation").info("serving")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
