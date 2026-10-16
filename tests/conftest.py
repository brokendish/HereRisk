"""Shared test setup.

* Network guard (autouse): any socket connect / DNS lookup fails the test.
* Every test gets its own temp fixture tree and temp data root; nothing is
  written to /data or to the repository.
"""

from __future__ import annotations

import hashlib
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pytest

import fixture_builder as fb
from hererisk.common.authorization import FixtureAuthorizer
from hererisk.common.config import ConfigurationManager
from hererisk.common.logging import ListSink, StructuredLogger
from hererisk.common.orchestrator import DownloadRequest, Orchestrator
from hererisk.common.storage import FIXTURE_ROOT_MARKER, ApiDataArea, init_fixture_data_root
from hererisk.elevation.download.download import ElevationDownload
from hererisk.elevation.download.transport import FixtureTransport

REPO_ROOT = fb.REPO_ROOT


class NetworkAccessAttempted(AssertionError):
    pass


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    attempts: list[Any] = []

    def deny(*args: Any, **kwargs: Any) -> Any:
        attempts.append(args)
        raise NetworkAccessAttempted("network access attempted in test")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket.socket, "connect_ex", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)
    return attempts


@dataclass
class Harness:
    fixture_root: Path
    data_root: Path
    sink: ListSink
    transport: FixtureTransport
    area_factory: Callable[[Path, str], ApiDataArea] = ApiDataArea
    sources: dict[str, dict[str, Any]] = field(default_factory=lambda: dict(fb.FIXTURE_SOURCES))
    run_ids: list[str] = field(default_factory=list)

    @property
    def api_root(self) -> Path:
        return self.data_root / "elevation"

    def orchestrator(self, authorizer: Any = None, module: Any = None) -> Orchestrator:
        return Orchestrator(
            config_manager=ConfigurationManager(self.fixture_root, REPO_ROOT),
            authorizer=authorizer
            or FixtureAuthorizer(
                self.fixture_root / "authorization" / "download.json", REPO_ROOT
            ),
            modules={"elevation": module or ElevationDownload(self.transport)},
            data_root=self.data_root,
            logger=StructuredLogger(self.sink),
            area_factory=self.area_factory,
        )

    def run(self, regions=("13",), source="fixture-dem-png-tokyo", resume=None, **kw):
        result = self.orchestrator(**kw).run_download(
            DownloadRequest("elevation", tuple(regions), source, resume_run_id=resume)
        )
        self.run_ids.append(result.run_id)
        return result

    def rebuild(self, sources: dict[str, dict[str, Any]] | None = None, **kw: Any) -> None:
        if sources is not None:
            self.sources = sources
        fb.build_tree(self.fixture_root, self.sources, **kw)

    def files(self) -> dict[str, str]:
        """Relative path -> sha256 of every file under the data root."""
        out: dict[str, str] = {}
        for path in sorted(self.data_root.rglob("*")):
            if path.is_file() and path.name != FIXTURE_ROOT_MARKER:
                out[path.relative_to(self.data_root).as_posix()] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
        return out


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    fixture_root = fb.build_tree(tmp_path / "fixture")
    data_root = tmp_path / "data"
    data_root.mkdir()
    init_fixture_data_root(data_root)
    return Harness(
        fixture_root=fixture_root,
        data_root=data_root,
        sink=ListSink(),
        transport=FixtureTransport(fixture_root / "tiles"),
    )
