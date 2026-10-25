"""HTTP adapter for the Location API v0.1 (standard library ``http.server``).

    python -m hererisk.location.server [--host 127.0.0.1] [--port 8001] [--sample-data]

* loopback addresses only (Phase 3-A is a local service skeleton, not a public deployment)
* default: every provider is not connected and answers ``not_available``
* ``--sample-data``: synthetic sample providers for screen checks; every section is marked
  ``synthetic: true`` and the response ``mode`` is ``sample``
* ``--elevation-api http://127.0.0.1:<port>`` (Phase 3-B): the ``elevation`` section comes from
  the existing Elevation API; the other providers stay not connected and ``mode`` is ``local``.
  ``--elevation-token-file`` is the Bearer token file of that API (outside Git, 0600).
  ``--elevation-fixture`` declares that the Elevation API serves fixture data: the section is then
  marked ``synthetic: true`` (fixture values are not real elevations). Without it a fixture dataset
  is refused (``synthetic_not_allowed``)
* ``--address-isj <ZIP or CSV>`` (Phase 3-C): the ``address`` section comes from MLIT
  大字・町丁目レベル位置参照情報, read once at startup (nearest representative point, an estimate).
  A missing or malformed file stops the start (exit 3). Can be combined with ``--elevation-api``
* ``--address-n03 <N03 ZIP>`` (Phase 3-D, with ``--address-isj``): decide the municipality with the
  国土数値情報 N03 行政区域 polygons first, then search only that municipality's points.
  Needs shapely (``pip install -e '.[address]'``)
* no request line, path, query or position is logged (the stdlib access log is disabled)
* the request body is never read; the API only accepts GET
"""

from __future__ import annotations

import argparse
import ipaddress
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Sequence
from urllib.parse import urlsplit

from hererisk.location.address_provider import AddressDataError, MlitAddressProvider
from hererisk.location.api import LocationApi
from hererisk.location.elevation_provider import ElevationProvider
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


def build_server(host: str, port: int, *, sample_data: bool = False, elevation_api: str | None = None,
                 elevation_token_file: Path | None = None, elevation_fixture: bool = False,
                 address_isj: Path | None = None, address_n03: Path | None = None) -> ThreadingHTTPServer:
    if not ipaddress.ip_address(host).is_loopback:
        raise ValueError("the Location API skeleton is only served on a loopback address")
    if address_n03 and not address_isj:
        raise ValueError("--address-n03 needs --address-isj")
    if sample_data and (elevation_api or address_isj):
        raise ValueError("--sample-data cannot be combined with connected providers")
    if sample_data:
        orchestrator = Orchestrator(sample_providers(), mode="sample", allow_synthetic=True)
    elif elevation_api or address_isj:
        providers = default_providers()
        if elevation_api:
            providers["elevation"] = ElevationProvider(elevation_api, token_file=elevation_token_file,
                                                       fixture=elevation_fixture)
        if address_isj:
            municipalities = None
            if address_n03:
                from hererisk.location.n03_municipality import N03Municipalities   # needs shapely
                municipalities = N03Municipalities(address_n03)
            providers["address"] = MlitAddressProvider(address_isj, municipalities)
        orchestrator = Orchestrator(providers, mode="local", allow_synthetic=elevation_fixture)
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
    parser.add_argument("--elevation-api", metavar="URL",
                        help="connect the elevation section to the Elevation API at http://127.0.0.1:<port>")
    parser.add_argument("--elevation-token-file", type=Path,
                        help="Bearer token file of that Elevation API (outside Git, 0600)")
    parser.add_argument("--elevation-fixture", action="store_true",
                        help="the Elevation API serves fixture data: mark the section synthetic")
    parser.add_argument("--address-isj", type=Path, metavar="ZIP_OR_CSV",
                        help="MLIT 大字・町丁目レベル位置参照情報 (official ZIP or its Shift-JIS CSV)")
    parser.add_argument("--address-n03", type=Path, metavar="N03_ZIP",
                        help="国土数値情報 N03 行政区域 ZIP: municipality by polygon (needs --address-isj)")
    args = parser.parse_args(argv)
    if args.address_n03 and not args.address_isj:
        sys.stderr.write("hererisk-location-api: --address-n03 needs --address-isj\n")
        return 2
    if (args.elevation_token_file or args.elevation_fixture) and not args.elevation_api:
        sys.stderr.write("hererisk-location-api: --elevation-token-file / --elevation-fixture need --elevation-api\n")
        return 2
    try:
        server = build_server(args.host, args.port, sample_data=args.sample_data, elevation_api=args.elevation_api,
                              elevation_token_file=args.elevation_token_file,
                              elevation_fixture=args.elevation_fixture, address_isj=args.address_isj,
                              address_n03=args.address_n03)
    except ImportError:
        sys.stderr.write("hererisk-location-api: --address-n03 needs shapely (pip install -e '.[address]')\n")
        return 3
    except AddressDataError as exc:
        sys.stderr.write(f"hererisk-location-api: address data rejected ({exc}); not serving\n")
        return 3
    except (ValueError, OSError) as exc:
        sys.stderr.write(f"hererisk-location-api: not serving ({type(exc).__name__})\n")
        return 3
    sys.stderr.write(f"hererisk-location-api: serving on http://{args.host}:{server.server_address[1]}"
                     f"{' (sample data: synthetic)' if args.sample_data else ''}"
                     f"{' (elevation: connected)' if args.elevation_api else ''}"
                     f"{' (address: connected)' if args.address_isj else ''}"
                     f"{' (municipality: N03 polygons)' if args.address_n03 else ''}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
