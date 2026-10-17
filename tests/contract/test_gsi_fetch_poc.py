"""Contract tests: Phase 1-D.1 GSI DEM10B acquisition PoC — no real network.

All HTTP traffic goes to an in-memory fake connection; the autouse socket/DNS
guard (conftest) fails any real attempt. Expected values are literals or come
from the fixture PNG builder rule.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import fixture_builder as fb
from hererisk import cli
from hererisk.common.logging import ListSink, StructuredLogger
from hererisk.common.result import PipelineError
from hererisk.common.storage import init_fixture_data_root
from hererisk.elevation.gsi_poc import http_fetch, poc
from test_normalize_stage import _undecodable_png

REPO = fb.REPO_ROOT
TOKYO_STATION = (35.681236, 139.767125)  # z14 tile 14552/6451 (well-known)
GOOD_PNG = fb.make_png(1)
T0 = datetime(2026, 10, 17, 9, 0, 0, tzinfo=timezone.utc)


# -- fake HTTP -------------------------------------------------------------------------------
class FakeSock:
    def __init__(self, ip):
        self.ip = ip
        self.timeouts = []

    def getpeername(self):
        return (self.ip, 443)

    def settimeout(self, value):
        self.timeouts.append(value)


class FakeResponse:
    def __init__(self, status, headers, body, chunk, fail_with):
        self.status = status
        self._headers = {k.lower(): v for k, v in headers.items()}
        self._body = body
        self._chunk = chunk
        self._fail_with = fail_with

    def getheader(self, name, default=None):
        return self._headers.get(name.lower(), default)

    def read(self, amt):
        if not self._body:
            if self._fail_with is not None:
                exc, self._fail_with = self._fail_with, None
                raise exc
            return b""
        n = min(amt, self._chunk)
        out, self._body = self._body[:n], self._body[n:]
        return out


class FakeHTTP:
    """connection_factory recording every connection and request."""

    def __init__(self, status=200, body=GOOD_PNG, headers=None, *, ip="133.13.1.1",  # globally routable (TEST-NET ranges are rejected)
                 connect_exc=None, response_exc=None, fail_with=None, chunk=4096,
                 omit_length=False):
        self.status, self.body, self.ip = status, body, ip
        self.headers = {"Content-Type": "image/png"} if headers is None else headers
        if not omit_length and "Content-Length" not in self.headers and headers is None:
            self.headers["Content-Length"] = str(len(body))
        self.connect_exc, self.response_exc, self.fail_with = connect_exc, response_exc, fail_with
        self.chunk = chunk
        self.connections: list[dict] = []

    def __call__(self, host):
        record = {"host": host, "requests": [], "closed": False}
        self.connections.append(record)
        fake = self

        class Conn:
            sock = None

            def connect(self):
                if fake.connect_exc:
                    raise fake.connect_exc
                self.sock = FakeSock(fake.ip)

            def request(self, method, path, headers):
                record["requests"].append((method, path, dict(headers)))

            def getresponse(self):
                if fake.response_exc:
                    raise fake.response_exc
                return FakeResponse(fake.status, fake.headers, fake.body, fake.chunk,
                                    fake.fail_with)

            def close(self):
                record["closed"] = True

        return Conn()


# -- helpers ------------------------------------------------------------------------------------
def plan(lat=TOKYO_STATION[0], lon=TOKYO_STATION[1], zoom=14):
    return poc.plan_fetch(lat, lon, zoom, repo_root=REPO)


def fetch(output_dir, http, *, p=None, allow=True, protected=(REPO,)):
    ticks = iter([T0, T0 + timedelta(seconds=1)] * 10)
    return poc.run_fetch_poc(p or plan(), output_dir, allow_network=allow,
                             protected_roots=protected, connection_factory=http,
                             clock=lambda: next(ticks))


def listing(d: Path) -> set[str]:
    return {p.name for p in d.iterdir()}


@pytest.fixture
def out(tmp_path):
    d = tmp_path / "poc"
    d.mkdir()
    return d


# -- plan / URL -----------------------------------------------------------------------------------
def test_plan_uses_locate_pixel_and_official_url() -> None:
    p = plan()
    assert (p.z, p.x, p.y) == (14, 14552, 6451)
    assert p.url == "https://cyberjapandata.gsi.go.jp/xyz/dem_png/14/14552/6451.png"
    assert (p.host, p.path) == ("cyberjapandata.gsi.go.jp", "/xyz/dem_png/14/14552/6451.png")
    assert p.source["source_ref"] == "gsi-dem10b-candidate"
    assert p.source["approval_ref"] is None  # explicitly not approved
    # The neighbouring tile to the east: one tile width (360 / 2^14 degrees) further.
    east = plan(TOKYO_STATION[0], TOKYO_STATION[1] + 360 / 2**14)
    assert (east.x, east.y) == (14553, 6451)


@pytest.mark.parametrize("zoom", [13, 15, 0])
def test_only_source_zoom_allowed(zoom) -> None:
    with pytest.raises(PipelineError) as err:
        plan(zoom=zoom)
    assert err.value.error_code == "INVALID_INPUT"


@pytest.mark.parametrize("lat,lon", [(91.0, 0.0), (0.0, 180.0), (float("nan"), 0.0)])
def test_invalid_coordinates(lat, lon) -> None:
    with pytest.raises(PipelineError) as err:
        plan(lat, lon)
    assert err.value.error_code == "INVALID_INPUT"


@pytest.mark.parametrize(
    "template",
    ["https://evil.example/xyz/dem_png/{z}/{x}/{y}.png",
     "https://cyberjapandata.gsi.go.jp/xyz/std/{z}/{x}/{y}.png",
     "https://cyberjapandata.gsi.go.jp.evil.example/xyz/dem_png/{z}/{x}/{y}.png"],
)
def test_tampered_url_template_rejected(tmp_path, template) -> None:
    repo = tmp_path / "repo"
    conf = repo / "api/elevation/conf"
    conf.mkdir(parents=True)
    shutil.copy(REPO / "api/elevation/conf/sources.schema.json", conf)
    doc = json.loads((REPO / "api/elevation/conf/sources.json").read_text(encoding="utf-8"))
    doc["sources"]["gsi-dem10b-candidate"]["acquisition"]["url_template"] = template
    (conf / "sources.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(PipelineError) as err:
        poc.plan_fetch(*TOKYO_STATION, 14, repo_root=repo)
    assert err.value.error_code == "INVALID_CONFIGURATION"


def test_http_layer_refuses_other_hosts() -> None:
    http = FakeHTTP()
    with pytest.raises(PipelineError) as err:
        http_fetch.fetch_png("evil.example", "/x.png", lambda c: None, connection_factory=http)
    assert err.value.error_code == "INVALID_CONFIGURATION" and http.connections == []


def test_default_connection_verifies_tls_without_connecting() -> None:
    conn = http_fetch.default_connection_factory(http_fetch.ALLOWED_HOST)
    assert conn.port == 443 and conn.timeout == http_fetch.CONNECT_TIMEOUT_S
    assert conn._context.verify_mode == ssl.CERT_REQUIRED and conn._context.check_hostname
    assert conn.sock is None  # nothing connected
    conn.close()


# -- no network without the flag ---------------------------------------------------------------------
def test_plan_only_without_flag(out, no_network) -> None:
    http = FakeHTTP()
    result = fetch(out, http, allow=False)
    assert result["mode"] == "plan" and result["network_used"] is False
    assert result["evidence"] is None and result["url"].endswith("/14/14552/6451.png")
    assert http.connections == [] and no_network == []
    assert listing(out) == set()  # nothing written, not even the marker


@pytest.mark.parametrize("flag", [None, 1, "yes", False])
def test_only_literal_true_enables_network(out, flag) -> None:
    http = FakeHTTP()
    assert fetch(out, http, allow=flag)["mode"] == "plan" and http.connections == []


# -- success -------------------------------------------------------------------------------------------
def test_successful_fetch_saves_png_and_evidence(out) -> None:
    http = FakeHTTP(chunk=1000)
    result = fetch(out, http)
    assert result["mode"] == "fetch" and result["network_used"] is True
    assert len(http.connections) == 1
    ((method, path, headers),) = http.connections[0]["requests"]
    assert (method, path) == ("GET", "/xyz/dem_png/14/14552/6451.png")
    assert headers["Host"] == "cyberjapandata.gsi.go.jp" and headers["Accept-Encoding"] == "identity"
    assert http.connections[0]["closed"]
    assert listing(out) == {".hererisk-gsi-poc-dir", "dem_png_14_14552_6451.png",
                            "dem_png_14_14552_6451.json"}  # no temporary files left
    saved = (out / "dem_png_14_14552_6451.png").read_bytes()
    assert saved == GOOD_PNG
    evidence = json.loads((out / "dem_png_14_14552_6451.json").read_bytes())
    assert evidence == result["evidence"]
    assert evidence["sha256"] == hashlib.sha256(GOOD_PNG).hexdigest()
    assert evidence["size_bytes"] == len(GOOD_PNG) == evidence["content_length"]
    assert evidence["http_status"] == 200 and evidence["content_type"] == "image/png"
    assert evidence["tile"] == {"z": 14, "x": 14552, "y": 6451}
    assert evidence["url"] == "https://cyberjapandata.gsi.go.jp/xyz/dem_png/14/14552/6451.png"
    assert (evidence["requested_at"], evidence["acquired_at"]) == \
        ("2026-10-17T09:00:00Z", "2026-10-17T09:00:01Z")
    assert evidence["poc_only"] is True and "not for publication" in evidence["notice"]
    assert evidence["checks"] == {"png_container": "passed", "decode": "passed", "profile": "passed"}
    # fixture_builder.make_png(1): 663 no-data pixels (see Validate core tests).
    assert evidence["statistics"]["nodata_count"] == 663
    assert evidence["statistics"]["valid_count"] == 65536 - 663
    assert evidence["source_definition"]["approval_ref"] is None
    assert evidence["source_definition"]["vertical_reference"] is None
    assert "vertical_reference" in evidence["unconfirmed"]
    assert evidence["attribution"].startswith("出典：国土地理院")


def test_missing_content_length_is_recorded_as_null(out) -> None:
    http = FakeHTTP(headers={"Content-Type": "image/png; charset=binary"})
    evidence = fetch(out, http)["evidence"]
    assert evidence["content_length"] is None and evidence["size_bytes"] == len(GOOD_PNG)


def test_second_tile_is_a_separate_explicit_request(out) -> None:
    fetch(out, FakeHTTP())
    http = FakeHTTP()
    east = plan(TOKYO_STATION[0], TOKYO_STATION[1] + 360 / 2**14)
    fetch(out, http, p=east)
    assert len(http.connections) == 1
    assert {"dem_png_14_14552_6451.png", "dem_png_14_14553_6451.png"} <= listing(out)


# -- HTTP / transfer failures -------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"status": 404}, "HTTP_404"),
        ({"status": 403}, "HTTP_403"),
        ({"status": 429}, "HTTP_429"),
        ({"status": 500}, "HTTP_5XX"),
        ({"status": 204}, "HTTP_UNEXPECTED"),
        ({"status": 302, "headers": {"Location": "https://evil.example/x.png"}}, "REDIRECT_REJECTED"),
        ({"headers": {"Content-Type": "text/html"}}, "CONTENT_TYPE_INVALID"),
        ({"headers": {"Content-Type": "image/png", "Content-Encoding": "gzip"}}, "CONTENT_TYPE_INVALID"),
        ({"connect_exc": socket.timeout("t")}, "TIMEOUT"),
        ({"response_exc": TimeoutError()}, "TIMEOUT"),
        ({"connect_exc": ssl.SSLCertVerificationError("bad cert")}, "TLS_FAILED"),
        ({"connect_exc": ConnectionRefusedError()}, "TRANSFER_INTERRUPTED"),
        ({"fail_with": ConnectionResetError()}, "TRANSFER_INTERRUPTED"),
        ({"fail_with": socket.timeout("read")}, "TIMEOUT"),
        ({"headers": {"Content-Type": "image/png", "Content-Length": str(len(GOOD_PNG) + 5)}},
         "TRANSFER_INTERRUPTED"),
        ({"headers": {"Content-Type": "image/png", "Content-Length": "x"}}, "SIZE_INVALID"),
        ({"body": b""}, "SIZE_INVALID"),
        ({"ip": "127.0.0.1"}, "TRANSFER_INTERRUPTED"),
        ({"ip": "10.1.2.3"}, "TRANSFER_INTERRUPTED"),
        ({"ip": "192.168.0.1"}, "TRANSFER_INTERRUPTED"),
        ({"ip": "169.254.169.254"}, "TRANSFER_INTERRUPTED"),
        ({"ip": "203.0.113.10"}, "TRANSFER_INTERRUPTED"),
        ({"ip": "::1"}, "TRANSFER_INTERRUPTED"),
    ],
    ids=["404", "403", "429", "500", "204", "302", "html", "gzip", "connect-timeout",
         "response-timeout", "tls", "refused", "reset-mid-body", "read-timeout",
         "length-mismatch", "bad-length", "empty", "loopback", "private-10", "private-192",
         "link-local", "test-net", "ipv6-loopback"],
)
def test_failures_save_nothing(out, kwargs, code) -> None:
    http = FakeHTTP(**kwargs)
    with pytest.raises(PipelineError) as err:
        fetch(out, http)
    assert err.value.error_code == code
    assert len(http.connections) == 1 and http.connections[0]["closed"]  # no retry
    assert listing(out) <= {".hererisk-gsi-poc-dir"}  # no PNG, no evidence, no temp file
    if kwargs.get("ip"):
        assert http.connections[0]["requests"] == []  # refused before sending


def test_redirect_is_not_followed(out) -> None:
    http = FakeHTTP(status=301, headers={"Location": "https://cyberjapandata.gsi.go.jp/other.png"})
    with pytest.raises(PipelineError):
        fetch(out, http)
    assert len(http.connections) == 1 and len(http.connections[0]["requests"]) == 1


def test_declared_size_over_limit_refused_before_reading(out) -> None:
    http = FakeHTTP(headers={"Content-Type": "image/png",
                             "Content-Length": str(http_fetch.MAX_BODY_BYTES + 1)})
    with pytest.raises(PipelineError) as err:
        fetch(out, http)
    assert err.value.error_code == "SIZE_INVALID"


def test_streamed_size_over_limit_stops(out) -> None:
    http = FakeHTTP(body=b"\x89PNG" + b"0" * (http_fetch.MAX_BODY_BYTES + 10),
                    headers={"Content-Type": "image/png"})
    with pytest.raises(PipelineError) as err:
        fetch(out, http)
    assert err.value.error_code == "SIZE_INVALID"
    assert listing(out) <= {".hererisk-gsi-poc-dir"}


def test_overall_deadline(out) -> None:
    clock = iter([0.0, 0.0, http_fetch.TOTAL_DEADLINE_S + 1])
    with pytest.raises(PipelineError) as err:
        http_fetch.fetch_png(http_fetch.ALLOWED_HOST, "/xyz/dem_png/14/1/1.png", lambda c: None,
                             connection_factory=FakeHTTP(), monotonic=lambda: next(clock))
    assert err.value.error_code == "TIMEOUT"


@pytest.mark.parametrize(
    "body",
    [GOOD_PNG[:20] + bytes([GOOD_PNG[20] ^ 1]) + GOOD_PNG[21:], GOOD_PNG + b"x",
     _undecodable_png(), b"GIF89a" + GOOD_PNG[6:]],
    ids=["crc", "trailing", "undecodable", "not-png"],
)
def test_broken_png_saves_nothing(out, body) -> None:
    with pytest.raises(PipelineError) as err:
        fetch(out, FakeHTTP(body=body))
    assert err.value.error_code == "PNG_INVALID"
    assert listing(out) <= {".hererisk-gsi-poc-dir"}


# -- output directory -------------------------------------------------------------------------------------
def test_existing_files_are_never_overwritten(out) -> None:
    fetch(out, FakeHTTP())
    png = out / "dem_png_14_14552_6451.png"
    before = png.read_bytes()
    http = FakeHTTP(body=fb.make_png(2))
    with pytest.raises(PipelineError) as err:
        fetch(out, http)
    assert err.value.error_code == "STORAGE_INTEGRITY_FAILED"
    assert http.connections == []  # refused before any network use
    assert png.read_bytes() == before


def test_existing_evidence_alone_also_blocks(out) -> None:
    (out / poc.POC_MARKER).write_bytes(poc.POC_MARKER_CONTENT)
    (out / "dem_png_14_14552_6451.json").write_bytes(b"{}")
    http = FakeHTTP()
    with pytest.raises(PipelineError):
        fetch(out, http)
    assert http.connections == []


def _bad_dirs(tmp_path):
    missing = tmp_path / "missing"
    afile = tmp_path / "afile"
    afile.write_bytes(b"x")
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "other.txt").write_bytes(b"x")
    fixture = tmp_path / "fixture-root"
    fixture.mkdir()
    init_fixture_data_root(fixture)
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    bad_marker = tmp_path / "bad-marker"
    bad_marker.mkdir()
    (bad_marker / poc.POC_MARKER).write_bytes(b"something else\n")
    protected = tmp_path / "protected"
    (protected / "inner").mkdir(parents=True)
    return [(missing, ()), (afile, ()), (busy, ()), (fixture, ()), (link, ()),
            (bad_marker, ()), (protected / "inner", (protected,)), (Path("/data"), ())]


def test_unsafe_output_directories_rejected(tmp_path) -> None:
    for directory, protected in _bad_dirs(tmp_path):
        http = FakeHTTP()
        with pytest.raises(PipelineError) as err:
            fetch(directory, http, protected=protected)
        assert err.value.error_code == "INVALID_INPUT", directory
        assert http.connections == [], directory
    assert listing(tmp_path / "busy") == {"other.txt"}
    assert listing(tmp_path / "real") == set()
    assert listing(tmp_path / "protected" / "inner") == set()


def test_fixture_root_rejected_even_with_poc_marker(tmp_path) -> None:
    both = tmp_path / "both"
    both.mkdir()
    init_fixture_data_root(both)
    (both / poc.POC_MARKER).write_bytes(poc.POC_MARKER_CONTENT)
    http = FakeHTTP()
    with pytest.raises(PipelineError) as err:
        fetch(both, http)
    assert err.value.error_code == "INVALID_INPUT" and http.connections == []


def test_output_directory_inside_repository_rejected(tmp_path) -> None:
    http = FakeHTTP()
    with pytest.raises(PipelineError):
        fetch(REPO / "tests", http)  # non-empty and in the repository
    assert http.connections == []


# -- CLI ------------------------------------------------------------------------------------------------------
def run_cli(argv, http=None):
    args = cli.build_parser().parse_args(argv)
    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli._gsi_fetch_poc(args, StructuredLogger(ListSink()), connection_factory=http)
    lines = buf.getvalue().splitlines()
    assert len(lines) == 1
    return code, json.loads(lines[0])


def test_cli_plan_mode(out) -> None:
    http = FakeHTTP()
    code, doc = run_cli(["gsi-fetch-poc", "--lat", "35.681236", "--lon", "139.767125",
                         "--zoom", "14", "--output-dir", str(out)], http)
    assert code == 0 and doc["status"] == "SUCCESS" and doc["mode"] == "plan"
    assert doc["network_used"] is False and http.connections == []
    assert doc["url"] == "https://cyberjapandata.gsi.go.jp/xyz/dem_png/14/14552/6451.png"
    assert listing(out) == set()


def test_cli_fetch_mode(out) -> None:
    http = FakeHTTP()
    code, doc = run_cli(["gsi-fetch-poc", "--lat", "35.681236", "--lon", "139.767125",
                         "--zoom", "14", "--output-dir", str(out), "--allow-network"], http)
    assert code == 0 and doc["mode"] == "fetch" and doc["network_used"] is True
    assert doc["evidence"]["sha256"] == hashlib.sha256(GOOD_PNG).hexdigest()
    assert len(http.connections) == 1


@pytest.mark.parametrize(
    "argv,code,error",
    [
        (["--lat", "abc", "--lon", "139", "--zoom", "14"], 2, "INVALID_INPUT"),
        (["--lat", "35", "--lon", "139", "--zoom", "13"], 2, "INVALID_INPUT"),
        (["--lat", "35", "--lon", "139", "--zoom", "x"], 2, "INVALID_INPUT"),
    ],
)
def test_cli_invalid_input(out, argv, code, error) -> None:
    http = FakeHTTP()
    rc, doc = run_cli(["gsi-fetch-poc", *argv, "--output-dir", str(out), "--allow-network"], http)
    assert (rc, doc["error_code"], doc["status"]) == (code, error, "FAILED")
    assert http.connections == []


def test_cli_http_error_exit_code(out) -> None:
    rc, doc = run_cli(["gsi-fetch-poc", "--lat", "35.681236", "--lon", "139.767125", "--zoom",
                       "14", "--output-dir", str(out), "--allow-network"], FakeHTTP(status=404))
    assert (rc, doc["error_code"], doc["evidence"]) == (10, "HTTP_404", None)
    assert str(out) not in json.dumps(doc)


def test_cli_plan_mode_subprocess_makes_no_network_attempt(out) -> None:
    from test_cli import cli as run_child

    proc = run_child("gsi-fetch-poc", "--lat", "35.681236", "--lon", "139.767125",
                     "--zoom", "14", "--output-dir", str(out))
    assert proc.returncode == 0 and json.loads(proc.stdout)["mode"] == "plan"
    assert listing(out) == set()


# -- isolation -------------------------------------------------------------------------------------------------
def test_pipeline_modules_do_not_load_network_code() -> None:
    import subprocess
    import sys

    code = ("import sys\n"
            "import hererisk.common.orchestrator, hererisk.elevation.download.download\n"
            "import hererisk.elevation.normalize.stage, hererisk.elevation.validate.stage\n"
            "import hererisk.elevation.lookup.reader, hererisk.cli\n"
            "bad = [m for m in sys.modules if m.startswith('hererisk.elevation.gsi_poc')"
            " or m == 'http.client']\n"
            "print(bad)\n")
    env = dict(os.environ, PYTHONPATH=str(REPO / "src"))
    proc = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                          timeout=60, check=False)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "[]"  # the CLI loads the PoC lazily, only for its command
