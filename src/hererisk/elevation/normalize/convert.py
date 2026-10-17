"""Pure conversion of one GSI elevation PNG tile to integer cm / null values.

Input: the PNG bytes of one tile and the tile coordinates supplied by the caller
(never derived from the PNG). Output: the candidate structure of contract
section 4.2 (``hererisk-elevation-cm-json-v0.1``) as a plain dict. No I/O, no
storage, no orchestration, no Validate.

Steps:
  1. container check: reuse Download's ``check_png`` (signature, CRC, chunk
     order, IHDR = 256x256 / 8-bit / RGB, PLTE rules, IEND, trailing bytes)
  2. bounded strict inflate of the concatenated IDAT data: the output must be
     exactly the scanline size implied by IHDR (non-interlaced 196864 bytes,
     Adam7 197088 bytes), the zlib stream must end exactly, with nothing after
     it; inflation stops at that size + 1 (no decompression bomb)
  3. un-filtering / de-interlacing via pypng (raw 8-bit samples; no gamma,
     ICC, palette or transparency processing)
  4. encoding rule (GSI demtile spec): q = 65536*R + 256*G + B;
     q < 2^23 -> q cm, q == 2^23 -> null (no data), q > 2^23 -> q - 2^24 cm
Pixels are row-major from the north-west corner: index = y * 256 + x.
Any decoding failure raises PNG_INVALID; it is never turned into no-data.
"""

from __future__ import annotations

import struct
import zlib
from typing import Any, Iterator, Mapping

import png  # pypng

from hererisk.common.result import PipelineError
from hererisk.elevation.tile_format import (
    TILE_BIT_DEPTH,
    TILE_COLOR_TYPE,
    TILE_HEIGHT,
    TILE_WIDTH,
)
from hererisk.elevation.download.png import PNG_SIGNATURE, check_png

FORMAT = "hererisk-elevation-cm-json-v0.1"
PIXELS = TILE_WIDTH * TILE_HEIGHT
CHANNELS = 3  # RGB
NODATA_Q = 1 << 23  # 8388608 == RGB (128, 0, 0)
_WRAP = 1 << 24
_MAX_ZOOM = 30  # same bound as the Source Definition schema

# Adam7 passes: (x0, y0, dx, dy)
_ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
          (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))


def rgb_to_cm(r: int, g: int, b: int) -> int | None:
    """GSI elevation PNG encoding -> integer cm, or None for no-data."""
    q = (r << 16) | (g << 8) | b
    if q < NODATA_Q:
        return q
    if q == NODATA_Q:
        return None
    return q - _WRAP


def _scanline_bytes(width: int, height: int, interlace: int) -> int:
    """Exact inflated IDAT size (filter byte + samples per scanline)."""
    row = lambda cols: 1 + cols * CHANNELS  # noqa: E731
    if interlace == 0:
        return height * row(width)
    total = 0
    for x0, y0, dx, dy in _ADAM7:
        cols = (width - x0 + dx - 1) // dx if width > x0 else 0
        rows = (height - y0 + dy - 1) // dy if height > y0 else 0
        if cols and rows:
            total += rows * row(cols)
    return total


def _chunks(data: bytes) -> Iterator[tuple[bytes, bytes]]:
    """(type, body) of each chunk; structure already verified by check_png."""
    pos = len(PNG_SIGNATURE)
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        yield data[pos + 4 : pos + 8], data[pos + 8 : pos + 8 + length]
        pos += 12 + length


def _inflate_exact(parts: list[bytes], expected: int) -> None:
    """Inflate IDAT data, bounded, requiring exactly ``expected`` bytes and a clean end."""
    d = zlib.decompressobj()
    produced = 0
    try:
        for index, part in enumerate(parts):
            buf = part
            while buf and not d.eof:
                produced += len(d.decompress(buf, expected + 1 - produced))
                if produced > expected:
                    raise PipelineError("PNG_INVALID", "inflated data too large")
                buf = d.unconsumed_tail
            if d.eof and (buf or d.unused_data or any(parts[index + 1 :])):
                raise PipelineError("PNG_INVALID", "data after zlib stream")
    except zlib.error as exc:
        raise PipelineError("PNG_INVALID", "zlib stream invalid") from exc
    if not d.eof or produced != expected:
        raise PipelineError("PNG_INVALID", "inflated size mismatch")


def decode_rgb_rows(png_bytes: bytes) -> list[bytes]:
    """Return the 256 rows of raw 8-bit RGB samples (768 bytes each)."""
    check_png(
        png_bytes,
        width=TILE_WIDTH,
        height=TILE_HEIGHT,
        bit_depth=TILE_BIT_DEPTH,
        color_type=TILE_COLOR_TYPE,
    )
    chunks = list(_chunks(png_bytes))
    interlace = chunks[0][1][12]  # IHDR last byte; check_png allowed only 0 or 1
    _inflate_exact([body for ctype, body in chunks if ctype == b"IDAT"],
                   _scanline_bytes(TILE_WIDTH, TILE_HEIGHT, interlace))
    try:
        width, height, rows, info = png.Reader(bytes=png_bytes).read()
        if (width, height) != (TILE_WIDTH, TILE_HEIGHT) or info.get("planes") != CHANNELS \
                or info.get("bitdepth") != TILE_BIT_DEPTH or info.get("alpha"):
            raise PipelineError("PNG_INVALID", "decoder reported unexpected format")
        out = [bytes(row) for row in rows]
    except (png.Error, zlib.error, ValueError, IndexError, struct.error) as exc:
        raise PipelineError("PNG_INVALID", "pixel decoding failed") from exc
    if len(out) != TILE_HEIGHT or any(len(row) != TILE_WIDTH * CHANNELS for row in out):
        raise PipelineError("PNG_INVALID", "decoded pixel count mismatch")
    return out


def _check_tile(tile: Mapping[str, Any]) -> dict[str, int]:
    if not isinstance(tile, Mapping) or set(tile) != {"z", "x", "y"}:
        raise PipelineError("INVALID_INPUT", "tile must have exactly z, x, y")
    values = {k: tile[k] for k in ("z", "x", "y")}
    if any(type(v) is not int for v in values.values()):  # rejects bool too
        raise PipelineError("INVALID_INPUT", "tile coordinates must be integers")
    z, x, y = values["z"], values["x"], values["y"]
    if not 0 <= z <= _MAX_ZOOM or not (0 <= x < (1 << z) and 0 <= y < (1 << z)):
        raise PipelineError("INVALID_INPUT", "tile coordinates out of range")
    return values


def normalize_tile(png_bytes: bytes, tile: Mapping[str, Any], *, max_png_bytes: int) -> dict[str, Any]:
    """Convert one tile PNG to the ``hererisk-elevation-cm-json-v0.1`` structure.

    ``png_bytes`` must be immutable ``bytes``; it is never modified.
    ``max_png_bytes`` is the caller's policy limit (e.g. ``max_tile_bytes``).
    """
    if type(png_bytes) is not bytes:
        raise PipelineError("INVALID_INPUT", "PNG must be bytes")
    checked_tile = _check_tile(tile)
    if len(png_bytes) > max_png_bytes:
        raise PipelineError("SIZE_INVALID", "PNG over size limit")
    values: list[int | None] = []
    for row in decode_rgb_rows(png_bytes):
        for i in range(0, len(row), CHANNELS):
            values.append(rgb_to_cm(row[i], row[i + 1], row[i + 2]))
    if len(values) != PIXELS:
        raise PipelineError("PNG_INVALID", "pixel count mismatch")
    return {
        "format": FORMAT,
        "tile": checked_tile,
        "width": TILE_WIDTH,
        "height": TILE_HEIGHT,
        "values_cm": values,
    }
