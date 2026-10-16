"""Transport abstraction for Download and its only implementation, FixtureTransport.

There is deliberately no HTTP transport in Phase 1-A.1. The Download core only
sees :class:`Transport`, so an HTTP implementation can be added later after the
network policy (contract section 7) is approved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol

from hererisk.common.authorization import ExecutionContext
from hererisk.common.result import PipelineError

FIXTURE_HOST = "fixture.invalid"  # RFC 2606 reserved TLD: can never resolve.
_FIXTURE_URL_RE = re.compile(
    r"^https://fixture\.invalid/([a-z][a-z0-9_-]*)/([0-9]{1,2})/([0-9]{1,9})/([0-9]{1,9})\.png$"
)


@dataclass(frozen=True)
class TransportResponse:
    effective_url: str
    content_type: str | None
    content_length: int | None
    chunks: Iterator[bytes]


class Transport(Protocol):
    context: ExecutionContext

    def accepts(self, url: str) -> bool:
        """Whether this transport is allowed to request ``url`` at all."""

    def fetch(self, url: str) -> TransportResponse:
        """Return the response for ``url`` or raise ``PipelineError``."""


class UnavailableTransport:
    """Placeholder for the production context: no network transport exists yet."""

    context = ExecutionContext.PRODUCTION

    def accepts(self, url: str) -> bool:
        return False

    def fetch(self, url: str) -> TransportResponse:
        raise PipelineError("APPROVAL_REQUIRED", "no production transport implemented")


class FixtureTransport:
    """Serve local fixture files for ``https://fixture.invalid/<layer>/z/x/y.png``.

    Maps to ``<tiles_root>/<layer>/<z>/<x>/<y>.png``. Any other URL is rejected
    before touching the filesystem; no socket is ever opened.
    """

    context = ExecutionContext.FIXTURE

    def __init__(self, tiles_root: Path, chunk_size: int = 4096) -> None:
        self._root = Path(tiles_root).resolve()
        self._chunk_size = chunk_size
        self.requested_urls: list[str] = []

    @staticmethod
    def accepts(url: str) -> bool:
        return _FIXTURE_URL_RE.match(url) is not None

    def fetch(self, url: str) -> TransportResponse:
        self.requested_urls.append(url)
        match = _FIXTURE_URL_RE.match(url)
        if match is None:
            raise PipelineError("INVALID_CONFIGURATION", "URL is not a fixture URL")
        layer, z, x, y = match.groups()
        path = self._root / layer / z / x / f"{y}.png"
        if path.is_symlink() or not path.resolve().is_relative_to(self._root):
            raise PipelineError("HTTP_404", "fixture outside root")
        try:
            size = path.stat().st_size
            handle = path.open("rb")
        except FileNotFoundError as exc:
            # The fixture equivalent of "source object not found".
            raise PipelineError("HTTP_404", "fixture missing") from exc
        except OSError as exc:
            raise PipelineError("TRANSFER_INTERRUPTED", "fixture unreadable") from exc
        return TransportResponse(
            effective_url=url,
            content_type="image/png",
            content_length=size,
            chunks=self._read(handle),
        )

    def _read(self, handle) -> Iterator[bytes]:
        with handle:
            while True:
                try:
                    chunk = handle.read(self._chunk_size)
                except OSError as exc:
                    raise PipelineError("TRANSFER_INTERRUPTED", "fixture read failed") from exc
                if not chunk:
                    return
                yield chunk
