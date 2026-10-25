"""HTTP adapter for the Location API v0.1 (standard library ``http.server``).

    python -m hererisk.location.server [--host 127.0.0.1] [--port 8001] [--sample-data]

* loopback addresses only (Phase 3-A is a local service skeleton, not a public deployment)
* default: every provider is not connected and answers ``not_available``
* ``--sample-data``: synthetic sample providers for screen checks; every section is marked
  ``synthetic: true`` and the response ``mode`` is ``sample``
* no request line, path, query or position is logged (the stdlib access log is disabled)
* the request body is never read; the API only accepts GET
"""

from __future__ import annotations

import argparse
import ipaddress
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Sequence
from urllib.parse import urlsplit

from hererisk.location.api import LocationApi
from hererisk.location.orchestrator import Orchestrator
from hererisk.location.providers import default_providers, sample_providers

SOCKET_TIMEOUT_S = 10


def make_handler(api: LocationApi):
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
            response = api.handle(self.command, parts.path, parts.query)
            self.close_connection = True
            self.send_response(response.status)
            for name, value in response.headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(response.body)))
            self.send_header("Connection", "close")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(response.body)

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = _dispatch

    return Handler


def build_server(host: str, port: int, *, sample_data: bool = False) -> ThreadingHTTPServer:
    if not ipaddress.ip_address(host).is_loopback:
        raise ValueError("the Location API skeleton is only served on a loopback address")
    if sample_data:
        orchestrator = Orchestrator(sample_providers(), mode="sample", allow_synthetic=True)
    else:
        orchestrator = Orchestrator(default_providers(), mode="mock", allow_synthetic=False)
    server = ThreadingHTTPServer((host, port), make_handler(LocationApi(orchestrator)))
    server.daemon_threads = True
    return server


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hererisk-location-api")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--sample-data", action="store_true",
                        help="serve synthetic sample sections (development screen checks only)")
    args = parser.parse_args(argv)
    try:
        server = build_server(args.host, args.port, sample_data=args.sample_data)
    except (ValueError, OSError) as exc:
        sys.stderr.write(f"hererisk-location-api: not serving ({type(exc).__name__})\n")
        return 3
    sys.stderr.write(f"hererisk-location-api: serving on http://{args.host}:{server.server_address[1]}"
                     f"{' (sample data: synthetic)' if args.sample_data else ''}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
