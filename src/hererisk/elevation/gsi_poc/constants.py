"""Network-free constants shared by the GSI PoC fetcher and the PoC reader."""

from __future__ import annotations

from hererisk.elevation.net.gsi_limits import ALLOWED_HOST, MAX_BODY_BYTES  # noqa: F401

MAX_EVIDENCE_BYTES = 64 * 1024
SOURCE_REF = "gsi-dem10b-candidate"
EVIDENCE_SCHEMA = "hererisk-gsi-poc-evidence-v0.1"
POC_MARKER = ".hererisk-gsi-poc-dir"
POC_MARKER_CONTENT = b"hererisk gsi dem10b acquisition poc v1\n"


def tile_basename(z: int, x: int, y: int) -> str:
    return f"dem_png_{z}_{x}_{y}"


def tile_url(z: int, x: int, y: int) -> str:
    return f"https://{ALLOWED_HOST}/xyz/dem_png/{z}/{x}/{y}.png"
