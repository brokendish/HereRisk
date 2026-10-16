"""PNG container check for transferred tiles (contract 7: 転送検査).

Checks signature, IHDR first with expected dimensions / bit depth / colour type,
chunk boundaries and CRCs, IEND last and no trailing bytes. Elevation value
quality and coverage are Validate's responsibility, not checked here.
"""

from __future__ import annotations

import struct
import zlib

from hererisk.common.result import PipelineError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def check_png(data: bytes, *, width: int, height: int, bit_depth: int, color_type: int) -> None:
    def invalid(reason: str) -> PipelineError:
        return PipelineError("PNG_INVALID", reason)

    if not data.startswith(PNG_SIGNATURE):
        raise invalid("signature")
    pos = len(PNG_SIGNATURE)
    first = True
    seen_idat = False
    while True:
        if pos + 8 > len(data):
            raise invalid("truncated chunk header")
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        ctype = data[pos + 4 : pos + 8]
        body_end = pos + 8 + length
        if length > 0x7FFFFFFF or body_end + 4 > len(data):
            raise invalid("chunk exceeds data")
        body = data[pos + 8 : body_end]
        (crc,) = struct.unpack(">I", data[body_end : body_end + 4])
        if zlib.crc32(ctype + body) & 0xFFFFFFFF != crc:
            raise invalid("crc")
        if first:
            if ctype != b"IHDR" or length != 13:
                raise invalid("IHDR not first")
            w, h, depth, ctype_png, _comp, _filt, _inter = struct.unpack(">IIBBBBB", body)
            if (w, h, depth, ctype_png) != (width, height, bit_depth, color_type):
                raise invalid("unexpected image format")
            first = False
        elif ctype == b"IDAT":
            seen_idat = True
        pos = body_end + 4
        if ctype == b"IEND":
            break
    if not seen_idat:
        raise invalid("no IDAT")
    if pos != len(data):
        raise invalid("trailing data")
