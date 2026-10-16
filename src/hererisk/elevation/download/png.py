"""PNG container check for transferred tiles (contract 7: 転送検査).

Container rules only; no decompression or pixel decoding:
  * signature, then IHDR first (exactly once, length 13) with the expected
    dimensions / bit depth / colour type and compression=0, filter=0,
    interlace in {0, 1}
  * chunk boundaries and CRCs; chunk types are four ASCII letters
  * unknown *critical* chunks rejected; PLTE (optional for RGB) before IDAT
  * at least one IDAT, all IDAT chunks consecutive
  * IEND last, length 0, no trailing bytes
Elevation value quality and coverage are Validate's responsibility.
"""

from __future__ import annotations

import struct
import zlib

from hererisk.common.result import PipelineError

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_KNOWN_CRITICAL = {b"IHDR", b"PLTE", b"IDAT", b"IEND"}


def check_png(data: bytes, *, width: int, height: int, bit_depth: int, color_type: int) -> None:
    def invalid(reason: str) -> PipelineError:
        return PipelineError("PNG_INVALID", reason)

    if not data.startswith(PNG_SIGNATURE):
        raise invalid("signature")
    pos = len(PNG_SIGNATURE)
    index = 0
    seen: set[bytes] = set()
    idat_state = "before"  # before -> inside -> after
    while True:
        if pos + 8 > len(data):
            raise invalid("truncated chunk header")
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        ctype = data[pos + 4 : pos + 8]
        body_end = pos + 8 + length
        if length > 0x7FFFFFFF or body_end + 4 > len(data):
            raise invalid("chunk exceeds data")
        if not ctype.isalpha() or not ctype.isascii():
            raise invalid("chunk type")
        body = data[pos + 8 : body_end]
        (crc,) = struct.unpack(">I", data[body_end : body_end + 4])
        if zlib.crc32(ctype + body) & 0xFFFFFFFF != crc:
            raise invalid("crc")

        critical = ctype[0:1].isupper()
        if index == 0:
            if ctype != b"IHDR" or length != 13:
                raise invalid("IHDR not first")
            w, h, depth, ctype_png, comp, filt, inter = struct.unpack(">IIBBBBB", body)
            if (w, h, depth, ctype_png) != (width, height, bit_depth, color_type):
                raise invalid("unexpected image format")
            if comp != 0 or filt != 0 or inter not in (0, 1):
                raise invalid("unsupported IHDR method")
        elif ctype == b"IHDR":
            raise invalid("duplicate IHDR")
        elif critical and ctype not in _KNOWN_CRITICAL:
            raise invalid("unknown critical chunk")
        elif ctype == b"PLTE":
            if b"PLTE" in seen or idat_state != "before":
                raise invalid("PLTE order")
        elif ctype == b"IDAT":
            if idat_state == "after":
                raise invalid("IDAT not consecutive")
            idat_state = "inside"
        elif ctype == b"IEND":
            if length != 0:
                raise invalid("IEND length")
        elif idat_state == "inside":
            idat_state = "after"

        seen.add(ctype)
        index += 1
        pos = body_end + 4
        if ctype == b"IEND":
            break
    if b"IDAT" not in seen:
        raise invalid("no IDAT")
    if pos != len(data):
        raise invalid("trailing data")
