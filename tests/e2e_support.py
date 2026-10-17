"""Test-only support for the production-format pipeline and the public API.

!!! Everything here is TEST-ONLY. !!!
* ``TestOnlyProductionAuthorizer`` is a test double of the authorization layer.
  It exists only under tests/; production code can never create a production
  authorization (``ProductionAuthorizer`` always BLOCKS). Its refs say
  "test-only-not-an-approval".
* ``test_source_repo`` writes a temporary *copy* of the Source Definition in
  which the GSI candidate is filled with ``test-only-*`` values. The real
  ``api/elevation/conf/sources.json`` is never modified.
* GSI HTTP is a fake connection; no real network is used.
"""

from __future__ import annotations

import json
import math
import shutil
import struct
import zlib
from pathlib import Path
from typing import Any

import fixture_builder as fb
from hererisk.common.authorization import Authorization, ExecutionContext
from hererisk.common.config import ConfigurationManager, freeze
from hererisk.common.logging import ListSink, StructuredLogger
from hererisk.common.orchestrator import DownloadRequest, Orchestrator
from hererisk.common.result import PipelineError
from hererisk.elevation.api.handler import ElevationApi, PATH, Settings
from hererisk.elevation.api.published import PublishedSet
from hererisk.elevation.download.download import ElevationDownload
from hererisk.elevation.download.gsi_transport import GsiHttpTransport
from hererisk.elevation.normalize.stage import NormalizeStage
from hererisk.elevation.publish.stage import PublishStage
from hererisk.elevation.validate.stage import ValidateStage
from test_gsi_fetch_poc import FakeHTTP

REPO = fb.REPO_ROOT
SOURCE = "gsi-dem10b-candidate"
TOKYO_TILES = [(14552, 6451), (14553, 6451)]  # Tokyo Station tile and its east neighbour
TEST_POLICY = {"policy_id": "test-only-policy", "version": "0.1", "max_tile_bytes": 1048576,
               "max_tiles_per_request": 16, "max_pending_acquisitions": 8}
TEST_TERMS = {"license": "test-only licence (NOT a GSI licence or redistribution approval)",
              "attribution_url": "https://example.invalid/test-only-terms"}


class TestOnlyProductionAuthorizer:
    """TEST DOUBLE. Grants every operation in the production context for tests."""

    __test__ = False  # not a pytest class
    context = ExecutionContext.PRODUCTION

    def __init__(self, *, refuse: set[str] = frozenset()) -> None:
        self.refuse = set(refuse)

    def authorize(self, *, api_id, operation, source_ref, region_codes, definition):
        if operation in self.refuse:
            raise PipelineError("APPROVAL_REQUIRED", "test double refuses")
        policy = TEST_POLICY if operation == "download" else (
            TEST_TERMS if operation == "publish" else {})
        return Authorization(
            authorization_ref=f"test-only-not-an-approval-{operation}",
            context=ExecutionContext.PRODUCTION, api_id=api_id, operation=operation,
            source_ref=source_ref, region_codes=tuple(region_codes), policy=freeze(dict(policy)))


def test_source_repo(root: Path, tiles=TOKYO_TILES, approval_ref="test-only-not-an-approval") -> Path:
    """Temporary definition root whose GSI candidate carries test-only values."""
    conf = root / "api" / "elevation" / "conf"
    conf.mkdir(parents=True)
    shutil.copy(REPO / "api/elevation/conf/sources.schema.json", conf)
    doc = json.loads((REPO / "api/elevation/conf/sources.json").read_text(encoding="utf-8"))
    src = doc["sources"][SOURCE]
    src["acquisition"]["tiles"] = [{"x": x, "y": y} for x, y in tiles]
    src["vertical_reference"] = "test-only-unconfirmed"
    src["usage"]["attribution_text"] = "test-only attribution (not GSI attribution text)"
    src["usage"]["review_ref"] = "test-only-review"
    src["pipeline"] = {"id": "elevation-download", "version": "0.1"}
    src["approval_ref"] = approval_ref
    doc["definition_revision"] = "test-only-1"
    (conf / "sources.json").write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                                       encoding="utf-8")
    return root


TEST_APPROVAL_ID = "apr-test-only-e2e"
TEST_ATTRIBUTION = "test-only attribution (not GSI attribution text)"


def approval_record(definition_sha256: str, *, approval_id=TEST_APPROVAL_ID, tiles=TOKYO_TILES,
                    operations=("download", "normalize", "validate", "publish"),
                    regions=("13",), **overrides) -> dict[str, Any]:
    """A TEST-ONLY production-format approval record (never a real approval)."""
    from hererisk.common.approval_store import RECORD_SCHEMA_ID, record_digest

    record: dict[str, Any] = {
        "schema": RECORD_SCHEMA_ID, "approval_id": approval_id, "execution_context": "production",
        "api_id": "elevation", "source_ref": SOURCE, "operations": list(operations),
        "region_codes": list(regions), "tiles": [{"z": 14, "x": x, "y": y} for x, y in tiles],
        "definition": {"revision": "test-only-1", "raw_sha256": definition_sha256},
        "valid_from": "2020-01-01T00:00:00Z", "expires_at": "2099-01-01T00:00:00Z",
        "approved_by": "test-only (not an approver)",
        "approval_basis_ref": "test-only (not an approval basis)",
    }
    if "download" in operations:
        record["acquisition"] = {"allowed_host": "cyberjapandata.gsi.go.jp",
                                 "max_tiles_per_run": 16, "max_tile_bytes": 1048576,
                                 "max_pending_acquisitions": 8}
    if "publish" in operations:
        record["publication"] = {"license": TEST_TERMS["license"],
                                 "attribution_url": TEST_TERMS["attribution_url"],
                                 "attribution_text": TEST_ATTRIBUTION,
                                 "eligibility_status": "approved",
                                 "eligibility_ref": "test-only (no publication eligibility)"}
    record.update(overrides)
    record["record_sha256"] = record_digest(record)
    return record


def write_store(root: Path, records, revoked=()) -> Path:
    """Write a TEST-ONLY approval store under ``root`` (a temp dir outside the repo)."""
    from hererisk.common.approval_store import REVOCATIONS_SCHEMA_ID

    (root / "approvals").mkdir(parents=True, exist_ok=True)
    for record in records:
        (root / "approvals" / f"{record['approval_id']}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "revocations.json").write_text(json.dumps({
        "schema": REVOCATIONS_SCHEMA_ID,
        "revoked": [{"approval_id": i, "revoked_at": "2026-01-01T00:00:00Z",
                     "reason_ref": "test-only"} for i in revoked]}), encoding="utf-8")
    return root


class GsiFake:
    """Fake GSI: serves a PNG per tile path; records every request."""

    def __init__(self, bodies: dict[tuple[int, int], bytes], **kwargs) -> None:
        self.bodies, self.kwargs, self.fakes = bodies, kwargs, []

    def __call__(self, host):
        fake_self = self

        class Lazy:
            def __init__(self):
                self.inner = None
                self.sock = None

            def connect(self):
                pass

            def request(self, method, path, headers):
                # path = /xyz/dem_png/<z>/<x>/<y>.png
                parts = path.split("/")
                key = (int(parts[4]), int(parts[5].split(".")[0]))
                fake = FakeHTTP(body=fake_self.bodies[key], **fake_self.kwargs)
                fake_self.fakes.append((path, fake))
                self.inner = fake(host)
                self.inner.connect()
                self.sock = self.inner.sock
                self.inner.request(method, path, headers)

            def getresponse(self):
                return self.inner.getresponse()

            def close(self):
                if self.inner:
                    self.inner.close()

        conn = Lazy()
        # The client checks the peer before sending: provide a public peer.
        from test_gsi_fetch_poc import FakeSock
        conn.sock = FakeSock("133.13.1.1")
        return conn

    @property
    def requested_paths(self) -> list[str]:
        return [p for p, _ in self.fakes]


def png_with(values: dict[tuple[int, int], tuple[int, int, int]], default=(0, 0, 100)) -> bytes:
    rows = bytearray()
    for y in range(256):
        rows.append(0)
        for x in range(256):
            rows += bytes(values.get((x, y), default))
    ihdr = struct.pack(">IIBBBBB", 256, 256, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + fb._chunk(b"IHDR", ihdr)
            + fb._chunk(b"IDAT", zlib.compress(bytes(rows))) + fb._chunk(b"IEND", b""))


def centre(tx, ty, px, py, z=14) -> tuple[float, float]:
    n = 256 * 2**z
    lon = (tx * 256 + px + 0.5) / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ty * 256 + py + 0.5) / n))))
    return lat, lon


class World:
    """One production-format data root, its pipeline and its API."""

    __test__ = False

    def __init__(self, tmp: Path, bodies: dict[tuple[int, int], bytes], *,
                 tiles=None, authorizer=None, stages=None, area_factory=None,
                 approval_ref="test-only-not-an-approval") -> None:
        self.tmp = tmp
        self.repo = test_source_repo(tmp / "repo", tiles or list(bodies), approval_ref)
        self.data_root = tmp / "data"
        self.data_root.mkdir(exist_ok=True)
        self.gsi = GsiFake(bodies)
        self.sink = ListSink()
        self.authorizer = authorizer or TestOnlyProductionAuthorizer()
        self.definition_sha256 = ConfigurationManager(self.repo, REPO).load(
            "api", "elevation", "sources").raw_sha256
        self.stages = stages or (NormalizeStage(), ValidateStage(), PublishStage())
        kwargs = {"area_factory": area_factory} if area_factory else {}
        self.orchestrator = Orchestrator(
            config_manager=ConfigurationManager(self.repo, REPO),
            authorizer=self.authorizer,
            modules={"elevation": ElevationDownload(GsiHttpTransport(connection_factory=self.gsi))},
            data_root=self.data_root,
            logger=StructuredLogger(self.sink),
            stages={"elevation": self.stages},
            **kwargs,
        )

    def use_store(self, records=None, revoked=(), **authorizer_kwargs):
        """Switch to the REAL ProductionAuthorizer over a TEST-ONLY store in tmp."""
        from hererisk.common.authorization import ProductionAuthorizer

        if records is None:
            records = [approval_record(self.definition_sha256)]
        self.store = write_store(self.tmp / "approval-store", records, revoked)
        self.authorizer = ProductionAuthorizer(self.store, protected_roots=(REPO,),
                                               **authorizer_kwargs)
        self.orchestrator._authorizer = self.authorizer
        return self.store

    def run(self, resume=None):
        return self.orchestrator.run_pipeline(
            DownloadRequest("elevation", ("13",), SOURCE, resume_run_id=resume),
            context=ExecutionContext.PRODUCTION)

    def api(self, sink=None, **kwargs) -> ElevationApi:
        published = PublishedSet.load(self.data_root)
        return ElevationApi(published, Settings(1024, 3000), StructuredLogger(sink or ListSink()),
                            **kwargs)


def post(api: ElevationApi, body: Any, *, raw: bytes | None = None, headers=None, query="",
         method="POST", path=PATH):
    data = raw if raw is not None else json.dumps(body).encode()
    return api.handle(method, path, query, {"Content-Type": "application/json"} if headers is None else headers, data)
