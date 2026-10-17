"""The only outbound network code in HereRisk: one HTTPS GET to GSI per call.

Used by the Phase 1-D.1 PoC and by the production GSI transport (1-D.3).

Rules enforced here:
  * HTTPS to the single allowed host on port 443 only; certificate and host
    name verification via ``ssl.create_default_context()``; no TLS opt-out
  * environment proxies are not used (``http.client`` does not read them)
  * the connected peer must be a public address (no loopback / private /
    link-local / reserved), checked before the request is sent
  * no redirect following: any status other than 200 is an error
  * Content-Type must be image/png; Content-Encoding must be absent/identity
  * connect / per-read timeouts and an overall deadline
  * the body is streamed to the caller's sink with a hard size limit; a
    declared Content-Length must match the bytes received
  * no retries, no parallelism

Errors are raised as ``PipelineError`` with the existing contract codes;
nothing here turns a failure into an empty or no-data result.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass
from typing import Callable, Protocol

from hererisk.common.result import PipelineError
from hererisk.elevation.net.gsi_limits import (
    ALLOWED_HOST,
    CHUNK,
    CONNECT_TIMEOUT_S,
    MAX_BODY_BYTES,
    PORT,
    READ_TIMEOUT_S,
    TOTAL_DEADLINE_S,
    USER_AGENT,
)


@dataclass(frozen=True)
class FetchResponse:
    http_status: int
    content_type: str
    content_length: int | None
    size_bytes: int


class Connection(Protocol):
    sock: object

    def connect(self) -> None: ...
    def request(self, method: str, url: str, headers: dict[str, str]) -> None: ...
    def getresponse(self): ...
    def close(self) -> None: ...


def default_connection_factory(host: str) -> Connection:
    return http.client.HTTPSConnection(
        host, PORT, timeout=CONNECT_TIMEOUT_S, context=ssl.create_default_context())


def _status_error(status: int) -> str:
    if 300 <= status < 400:
        return "REDIRECT_REJECTED"
    if status == 404:
        return "HTTP_404"
    if status == 403:
        return "HTTP_403"
    if status == 429:
        return "HTTP_429"
    if 500 <= status < 600:
        return "HTTP_5XX"
    return "HTTP_UNEXPECTED"


def _check_peer(conn: Connection) -> None:
    try:
        address = conn.sock.getpeername()[0]  # type: ignore[attr-defined]
        ip = ipaddress.ip_address(address)
    except (AttributeError, OSError, ValueError, IndexError) as exc:
        raise PipelineError("TRANSFER_INTERRUPTED", "peer address unknown") from exc
    if not ip.is_global:
        raise PipelineError("TRANSFER_INTERRUPTED", "peer is not a public address")


def fetch_png(
    host: str,
    path: str,
    sink: Callable[[bytes], None],
    *,
    connection_factory: Callable[[str], Connection] = default_connection_factory,
    monotonic: Callable[[], float] = time.monotonic,
) -> FetchResponse:
    """GET ``https://<host><path>`` and stream the PNG body into ``sink``."""
    if host != ALLOWED_HOST:
        raise PipelineError("INVALID_CONFIGURATION", "host not allowed")
    deadline = monotonic() + TOTAL_DEADLINE_S
    conn = connection_factory(host)
    try:
        try:
            conn.connect()
            _check_peer(conn)
            if hasattr(conn.sock, "settimeout"):
                conn.sock.settimeout(READ_TIMEOUT_S)  # type: ignore[attr-defined]
            conn.request("GET", path, headers={
                "Host": host, "User-Agent": USER_AGENT, "Accept": "image/png",
                "Accept-Encoding": "identity", "Connection": "close"})
            response = conn.getresponse()
        except ssl.SSLError as exc:
            raise PipelineError("TLS_FAILED") from exc
        except (socket.timeout, TimeoutError) as exc:
            raise PipelineError("TIMEOUT") from exc
        except (OSError, http.client.HTTPException) as exc:
            raise PipelineError("TRANSFER_INTERRUPTED", "connection failed") from exc

        if response.status != 200:
            raise PipelineError(_status_error(response.status), "HTTP status")
        media = (response.getheader("Content-Type") or "").split(";")[0].strip().lower()
        if media != "image/png":
            raise PipelineError("CONTENT_TYPE_INVALID")
        encoding = (response.getheader("Content-Encoding") or "identity").strip().lower()
        if encoding != "identity":
            raise PipelineError("CONTENT_TYPE_INVALID", "content encoding not allowed")
        declared = response.getheader("Content-Length")
        length = None
        if declared is not None:
            try:
                length = int(declared)
            except ValueError as exc:
                raise PipelineError("SIZE_INVALID", "bad Content-Length") from exc
            if length < 0 or length > MAX_BODY_BYTES:
                raise PipelineError("SIZE_INVALID", "declared length over limit")

        size = 0
        while True:
            if monotonic() > deadline:
                raise PipelineError("TIMEOUT", "overall deadline")
            try:
                chunk = response.read(min(CHUNK, MAX_BODY_BYTES + 1 - size))
            except (socket.timeout, TimeoutError) as exc:
                raise PipelineError("TIMEOUT") from exc
            except ssl.SSLError as exc:
                raise PipelineError("TLS_FAILED") from exc
            except (OSError, http.client.HTTPException) as exc:
                raise PipelineError("TRANSFER_INTERRUPTED", "read failed") from exc
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BODY_BYTES:
                raise PipelineError("SIZE_INVALID", "body over limit")
            sink(chunk)
        if size == 0:
            raise PipelineError("SIZE_INVALID", "empty body")
        if length is not None and length != size:
            raise PipelineError("TRANSFER_INTERRUPTED", "length mismatch")
        return FetchResponse(http_status=200, content_type=media,
                             content_length=length, size_bytes=size)
    finally:
        conn.close()
