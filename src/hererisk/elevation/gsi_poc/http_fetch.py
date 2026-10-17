"""Compatibility alias: the GSI HTTPS client now lives in ``hererisk.elevation.net.gsi_http``."""

from hererisk.elevation.net.gsi_http import *  # noqa: F401,F403
from hererisk.elevation.net.gsi_http import (  # noqa: F401
    ALLOWED_HOST,
    CHUNK,
    CONNECT_TIMEOUT_S,
    MAX_BODY_BYTES,
    READ_TIMEOUT_S,
    TOTAL_DEADLINE_S,
    Connection,
    FetchResponse,
    default_connection_factory,
    fetch_png,
)
