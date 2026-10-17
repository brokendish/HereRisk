"""Unit tests: elevation Normalize core (PNG -> integer cm / null).

The PNG encoder below is test-only and independent of the decoder under test
(pypng is used only for decoding). Expected values are fixed literals taken
from the contract table / hand calculation, never computed with the code
under test.
"""

from __future__ import annotations

import hashlib
import struct
import zlib

import pytest

import fixture_builder as fb
from hererisk.common.result import PipelineError
from hererisk.elevation.normalize import convert
from hererisk.elevation.normalize.convert import FORMAT, normalize_tile

TILE = {"z": 14, "x": 14547, "y": 6463}
LIMIT = 1048576
NODATA = (128, 0, 0)

# Contract 4.2 table + boundaries: RGB -> cm (literals, not computed).
ENCODING_CASES = [
    ((0, 4, 210), 1234),
    ((0, 0, 0), 0),
    ((255, 255, 136), -120),
    ((128, 0, 0), None),
    ((127, 255, 255), 8388607),
    ((128, 0, 1), -8388607),
    ((0, 0, 1), 1),
    ((255, 255, 255), -1),
    ((127, 255, 254), 8388606),
    ((255, 255, 254), -2),
    ((0, 1, 0), 256),
    ((1, 0, 0), 65536),
]


# --- independent test-side PNG encoder -------------------------------------------------
def _chunk(ctype: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + ctype + body + struct.pack(
        ">I", zlib.crc32(ctype + body) & 0xFFFFFFFF)


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def _filter_row(ftype: int, row: bytes, prev: bytes) -> bytes:
    out = bytearray([ftype])
    for i, v in enumerate(row):
        a = row[i - 3] if i >= 3 else 0
        b = prev[i] if prev else 0
        c = prev[i - 3] if prev and i >= 3 else 0
        pred = (0, a, b, (a + b) // 2, _paeth(a, b, c))[ftype]
        out.append((v - pred) & 0xFF)
    return bytes(out)


def _scanlines(pixels, width, height, filters) -> bytes:
    data = bytearray()
    prev = b""
    for y in range(height):
        row = bytes(c for x in range(width) for c in pixels(x, y))
        data += _filter_row(filters(y), row, prev)
        prev = row
    return bytes(data)


ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
         (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))


def encode(pixels, *, width=256, height=256, filters=lambda y: 0, adam7=False,
           idat_split=None, extra=b"", ihdr=None, raw=None) -> bytes:
    """pixels(x, y) -> (r, g, b). Returns a PNG built without the decoder."""
    if raw is None:
        if adam7:
            raw = b""
            for x0, y0, dx, dy in ADAM7:
                cols = list(range(x0, width, dx))
                rows = list(range(y0, height, dy))
                if cols and rows:
                    raw += _scanlines(lambda i, j: pixels(cols[i], rows[j]),
                                      len(cols), len(rows), filters)
        else:
            raw = _scanlines(pixels, width, height, filters)
    stream = zlib.compress(raw, 9)
    parts = [stream] if not idat_split else [
        stream[i:i + idat_split] for i in range(0, len(stream), idat_split)]
    header = ihdr or struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 1 if adam7 else 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + extra
            + b"".join(_chunk(b"IDAT", p) for p in parts) + _chunk(b"IEND", b""))


def uniform(rgb):
    return lambda x, y: rgb


def norm(data: bytes, tile=TILE):
    return normalize_tile(data, tile, max_png_bytes=LIMIT)


def expect_error(data, code="PNG_INVALID", tile=TILE):
    with pytest.raises(PipelineError) as err:
        normalize_tile(data, tile, max_png_bytes=LIMIT)
    assert err.value.error_code == code
    return err


# --- conversion -------------------------------------------------------------------------
@pytest.mark.parametrize("rgb,cm", ENCODING_CASES, ids=[str(c) for _, c in ENCODING_CASES])
def test_uniform_tile_encoding(rgb, cm) -> None:
    out = norm(encode(uniform(rgb)))
    assert out["values_cm"] == [cm] * 65536


def test_mixed_values_and_structure() -> None:
    # Each pixel takes one of the encoding cases by (x + y) % 12.
    cases = ENCODING_CASES

    def px(x, y):
        return cases[(x + 7 * y) % len(cases)][0]

    out = norm(encode(px))
    assert set(out) == {"format", "tile", "width", "height", "values_cm"}
    assert out["format"] == FORMAT == "hererisk-elevation-cm-json-v0.1"
    assert out["tile"] == TILE and out["tile"] is not TILE
    assert (out["width"], out["height"]) == (256, 256)
    values = out["values_cm"]
    assert len(values) == 65536
    for (x, y) in [(0, 0), (1, 0), (255, 0), (0, 1), (13, 200), (255, 255)]:
        assert values[y * 256 + x] == cases[(x + 7 * y) % len(cases)][1]
    assert values.count(None) == sum(1 for y in range(256) for x in range(256)
                                     if (x + 7 * y) % 12 == 3)
    assert all(v is None or type(v) is int for v in values)
    assert 0 in values and -120 in values  # 0 and negatives are real values


def test_corners_and_row_boundaries_row_major() -> None:
    special = {
        (0, 0): ((0, 0, 1), 1),
        (255, 0): ((0, 0, 2), 2),
        (0, 1): ((0, 0, 3), 3),
        (255, 1): ((0, 0, 4), 4),
        (0, 255): ((255, 255, 255), -1),
        (255, 255): ((127, 255, 255), 8388607),
        (1, 0): ((0, 1, 0), 256),
        (0, 2): ((128, 0, 0), None),
    }
    base = (0, 0, 0)

    def px(x, y):
        return special.get((x, y), (base,))[0]

    values = norm(encode(px))["values_cm"]
    expected_index = {0: 1, 255: 2, 256: 3, 511: 4, 65280: -1, 65535: 8388607, 1: 256, 512: None}
    for index, cm in expected_index.items():
        assert values[index] == cm, index
    assert values[257] == 0 and values[65534] == 0
    assert sum(1 for v in values if v != 0) == len(special)


# --- equivalent encodings -----------------------------------------------------------------
def _pattern(x, y):
    q = (x * 4099 + y * 131 + 7) % (1 << 24)
    if (x * 31 + y) % 53 == 0:
        return NODATA
    return (q >> 16, (q >> 8) & 0xFF, q & 0xFF)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"filters": lambda y: 1},
        {"filters": lambda y: 2},
        {"filters": lambda y: 3},
        {"filters": lambda y: 4},
        {"filters": lambda y: y % 5},
        {"idat_split": 1000},
        {"idat_split": 13},
        {"adam7": True},
        {"adam7": True, "filters": lambda y: (y + 2) % 5, "idat_split": 777},
        {"extra": _chunk(b"PLTE", b"\xff\x00\x00" * 4)},  # RGB: palette ignored
        {"extra": _chunk(b"gAMA", struct.pack(">I", 22727))},  # no gamma correction
        {"extra": _chunk(b"tRNS", b"\x00\x80\x00\x00\x00\x00")},  # not used as no-data
        {"extra": _chunk(b"tEXt", b"k\x00v")},
    ],
    ids=["sub", "up", "average", "paeth", "mixed", "split-1000", "split-13", "adam7",
         "adam7-mixed-split", "plte", "gama", "trns", "text"],
)
def test_equivalent_encodings_give_identical_values(kwargs) -> None:
    reference = norm(encode(_pattern))["values_cm"]
    assert norm(encode(_pattern, **kwargs))["values_cm"] == reference
    # spot-check the reference itself against literals of the pattern
    assert reference[0] is None  # (0,0): (0*31+0) % 53 == 0 -> no-data
    assert reference[1] == 4099 + 7  # (1,0)
    assert reference[256] == 131 + 7  # (0,1)


def test_builder_fixture_png_decodes() -> None:
    values = norm(fb.make_png(1))["values_cm"]
    assert len(values) == 65536 and values[0] == 1000  # seed 1: (1*1000 + 0 + 0)
    assert values[96] is None  # (x + y + 1) % 97 == 0 at x=96, y=0


# --- rejection ----------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "ihdr",
    [
        struct.pack(">IIBBBBB", 255, 256, 8, 2, 0, 0, 0),
        struct.pack(">IIBBBBB", 256, 512, 8, 2, 0, 0, 0),
        struct.pack(">IIBBBBB", 256, 256, 16, 2, 0, 0, 0),
        struct.pack(">IIBBBBB", 256, 256, 8, 6, 0, 0, 0),
        struct.pack(">IIBBBBB", 256, 256, 8, 3, 0, 0, 0),
        struct.pack(">IIBBBBB", 256, 256, 8, 0, 0, 0, 0),
        struct.pack(">IIBBBBB", 0x7FFFFFFF, 0x7FFFFFFF, 8, 2, 0, 0, 0),  # huge IHDR
    ],
    ids=["w255", "h512", "16bit", "rgba", "indexed", "grey", "huge"],
)
def test_wrong_dimensions_or_format_rejected(ihdr) -> None:
    expect_error(encode(uniform((0, 0, 0)), ihdr=ihdr))


def _raw_rows(n_rows=256, row=b"\x00" + b"\x01\x02\x03" * 256):
    return row * n_rows


@pytest.mark.parametrize(
    "raw",
    [
        _raw_rows(255),  # pixels missing
        _raw_rows(257),  # pixels in excess (pypng alone accepts this)
        _raw_rows()[:-1],  # one byte short
        _raw_rows() + b"\x00",  # one byte long
        b"\x05" + _raw_rows()[1:],  # invalid filter type
        b"",  # empty image data
    ],
    ids=["rows-255", "rows-257", "short-1", "long-1", "bad-filter", "empty"],
)
def test_bad_image_data_rejected_not_nulled(raw) -> None:
    expect_error(encode(None, raw=raw))


def test_adam7_size_mismatch_rejected() -> None:
    good = encode(_pattern, adam7=True)
    norm(good)
    # Non-interlaced scanline data under an Adam7 IHDR has the wrong size.
    expect_error(encode(_pattern, raw=_scanlines(_pattern, 256, 256, lambda y: 0),
                        ihdr=struct.pack(">IIBBBBB", 256, 256, 8, 2, 0, 0, 1)))


def _with_idat(png_bytes: bytes, streams: list[bytes]) -> bytes:
    head = png_bytes[:33]
    return head + b"".join(_chunk(b"IDAT", s) for s in streams) + _chunk(b"IEND", b"")


def test_zlib_stream_violations_rejected() -> None:
    raw = _raw_rows()
    stream = zlib.compress(raw)
    base = encode(None, raw=raw)
    expect_error(_with_idat(base, [stream + b"junk"]))  # trailing bytes in same IDAT
    expect_error(_with_idat(base, [stream, b"more"]))  # extra IDAT after stream end
    expect_error(_with_idat(base, [stream[:-4]]))  # truncated (no adler32)
    expect_error(_with_idat(base, [b"\x78\x9c" + b"\xff" * 50]))  # garbage deflate
    corrupted = bytearray(stream)
    corrupted[len(corrupted) // 2] ^= 0xFF
    expect_error(_with_idat(base, [bytes(corrupted)]))


def test_decompression_bomb_is_bounded(monkeypatch) -> None:
    bomb = zlib.compress(b"\x00" * (64 * 1024 * 1024), 9)  # ~64 KiB -> 64 MiB
    data = _with_idat(encode(None, raw=_raw_rows()), [bomb])
    produced: list[int] = []
    real = zlib.decompressobj

    class Counting:
        def __init__(self):
            self._d = real()

        def decompress(self, buf, max_length=0):
            out = self._d.decompress(buf, max_length)
            produced.append(len(out))
            return out

        def __getattr__(self, name):
            return getattr(self._d, name)

    monkeypatch.setattr(convert.zlib, "decompressobj", Counting)
    expect_error(data)
    assert sum(produced) <= 196864 + 1


def test_container_violations_rejected() -> None:
    good = encode(uniform((0, 4, 210)))
    expect_error(good[:-1])  # truncated
    expect_error(good[:20] + bytes([good[20] ^ 1]) + good[21:])  # CRC broken
    expect_error(b"GIF89a" + good[6:])
    expect_error(good + b"\x00")


def test_size_limit_and_input_type() -> None:
    good = encode(uniform((0, 0, 0)))
    with pytest.raises(PipelineError) as err:
        normalize_tile(good, TILE, max_png_bytes=len(good) - 1)
    assert err.value.error_code == "SIZE_INVALID"
    for wrong in (bytearray(good), memoryview(good), good.decode("latin-1")):
        expect_error(wrong, code="INVALID_INPUT")


@pytest.mark.parametrize(
    "tile",
    [
        {"z": 14, "x": 14547},
        {"z": 14, "x": 14547, "y": 6463, "extra": 1},
        {"z": 14, "x": True, "y": 6463},
        {"z": 14, "x": 1.0, "y": 6463},
        {"z": 14, "x": "1", "y": 6463},
        {"z": 14, "x": -1, "y": 6463},
        {"z": 14, "x": 16384, "y": 0},
        {"z": 31, "x": 0, "y": 0},
        {"z": -1, "x": 0, "y": 0},
        [14, 14547, 6463],
    ],
)
def test_invalid_tile_rejected(tile) -> None:
    expect_error(encode(uniform((0, 0, 0))), code="INVALID_INPUT", tile=tile)


# --- invariants -------------------------------------------------------------------------------------
def test_original_bytes_unchanged() -> None:
    data = encode(_pattern, adam7=True)
    digest = hashlib.sha256(data).hexdigest()
    copy = bytes(data)
    norm(data)
    assert data == copy and hashlib.sha256(data).hexdigest() == digest


def test_failure_does_not_return_partial_or_null_output() -> None:
    raw = _raw_rows()
    bad = bytearray(raw)
    bad[769 * 100] = 9  # invalid filter type on row 100
    with pytest.raises(PipelineError):
        norm(encode(None, raw=bytes(bad)))


def test_module_is_pure() -> None:
    """No I/O, storage, orchestration, transport or later stages in the module."""
    import ast

    tree = ast.parse(open(convert.__file__, encoding="utf-8").read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert imported <= {
        "__future__", "struct", "zlib", "typing", "png",
        "hererisk.common.result", "hererisk.elevation.download.png",
        "hererisk.elevation.download.download",
    }, imported
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {"open", "ApiDataArea", "Orchestrator", "ElevationDownload"}
