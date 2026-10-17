"""Production transport for Download (Phase 1-D.3): GSI DEM PNG over HTTPS.

Context PRODUCTION. Reachable only through the Orchestrator after a production
authorization, which does not exist yet (``ProductionAuthorizer`` is always
BLOCKED), so no real request can be made by the pipeline today. The network
rules (single host, verified TLS, no proxies, public peer, no redirects,
image/png, timeouts, 1 MiB cap, no retries) are those of
``hererisk.elevation.net.gsi_http``; the body is buffered (bounded) and handed
to Download, which applies its own policy size / length / PNG checks.
"""

from __future__ import annotations

import re
from typing import Callable

from hererisk.common.authorization import ExecutionContext
from hererisk.common.result import PipelineError
from hererisk.elevation.download.transport import TransportResponse
from hererisk.elevation.net import gsi_http

_URL_RE = re.compile(
    r"^https://cyberjapandata\.gsi\.go\.jp(/xyz/dem_png/[0-9]{1,2}/[0-9]{1,9}/[0-9]{1,9}\.png)$")


class GsiHttpTransport:
    """Real-data transport for ``production`` (public) or ``private_experiment`` runs."""

    def __init__(self, *, connection_factory: Callable[[str], gsi_http.Connection]
                 = gsi_http.default_connection_factory,
                 context: ExecutionContext = ExecutionContext.PRODUCTION) -> None:
        if context not in (ExecutionContext.PRODUCTION, ExecutionContext.PRIVATE_EXPERIMENT):
            raise ValueError("GSI transport is for real-data contexts only")
        self.context = context
        self._connection_factory = connection_factory
        self.requested_urls: list[str] = []

    @staticmethod
    def accepts(url: str) -> bool:
        return _URL_RE.match(url) is not None

    def fetch(self, url: str) -> TransportResponse:
        match = _URL_RE.match(url)
        if match is None:
            raise PipelineError("INVALID_CONFIGURATION", "URL is not a GSI dem_png URL")
        self.requested_urls.append(url)
        body: list[bytes] = []
        response = gsi_http.fetch_png(gsi_http.ALLOWED_HOST, match.group(1), body.append,
                                      connection_factory=self._connection_factory)
        data = b"".join(body)
        return TransportResponse(effective_url=url, content_type=response.content_type,
                                 content_length=response.content_length, chunks=iter([data]))
