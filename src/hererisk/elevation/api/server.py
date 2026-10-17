"""HTTP adapter for the public elevation API (standard library ``http.server``).

    python -m hererisk.elevation.api.server --data-root <published data root> \
        [--host 127.0.0.1] [--port 8000]

* inbound HTTP only; no outbound connections are made by the API process
* the published snapshot is loaded and verified at startup; failure -> exit 3,
  the service never answers with unverified data
* fixture data roots are refused unless ``--fixture-demo`` is given, which is
  only allowed on a loopback address (local development demo)
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

from hererisk.common.config import ConfigurationError, ConfigurationManager
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
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or self.headers.get("Transfer-Encoding"):
                body = b""
                headers = dict(self.headers.items())
                headers["Content-Type"] = "invalid/unsupported"  # unsupported framing -> 415
            else:
                body = self.rfile.read(min(length, max_body + 1)) if length else b""
                headers = dict(self.headers.items())
            response = api.handle(self.command, parts.path, parts.query, headers, body)
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


def build_server(data_root: Path, host: str, port: int, *, fixture_demo: bool = False,
                 logger: StructuredLogger | None = None) -> ThreadingHTTPServer:
    if fixture_demo and not ipaddress.ip_address(host).is_loopback:
        raise StartupError("--fixture-demo is only allowed on a loopback address")
    settings = load_settings()
    published = PublishedSet.load(data_root, allow_fixture_root=fixture_demo)
    api = ElevationApi(published, settings, logger or StructuredLogger())
    server = ThreadingHTTPServer((host, port), make_handler(api, settings.request_body_max_bytes))
    server.daemon_threads = True
    return server


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hererisk-elevation-api")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--fixture-demo", action="store_true",
                        help="serve a fixture data root (loopback only, local demo)")
    args = parser.parse_args(argv)
    logger = StructuredLogger()
    try:
        server = build_server(args.data_root, args.host, args.port,
                              fixture_demo=args.fixture_demo, logger=logger)
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
