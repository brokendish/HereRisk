"""Pure point lookup: (latitude, longitude, zoom) -> XYZ pixel -> stored value.

Coordinates use the Web Mercator / XYZ (slippy map) tiling of the elevation API
contract section 6.2, with N = 256 * 2^z global pixels per axis:

    u = N * (lon + 180) / 360
    v = N * (1 - ln(tan(phi) + 1 / cos(phi)) / pi) / 2      (phi in radians)
    ix = floor(u); iy = floor(v)
    tile = i // 256; pixel = i % 256; index = pixel_y * 256 + pixel_x

x grows east, y grows south, origin north-west. Pixels are half-open: a
boundary belongs to the east / south pixel. Accordingly the accepted domain is
half-open as well, never clamped, wrapped or normalised:

    -180 <= longitude < 180,   -LAT_MAX < latitude <= LAT_MAX,   0 <= zoom <= 30
    LAT_MAX = degrees(atan(sinh(pi)))  (~85.0511287798066)

(longitude 180 and latitude -LAT_MAX are the east / south edges of the world
and belong to no pixel.) Only floating-point rounding of an *accepted* input
can land exactly on the outer edge (u or v == N); such a value is the last
pixel, whose half-open interval contains the exact result.

``lookup_elevation`` returns the stored ``values_cm`` entry unchanged (integer
cm or None for no-data). It does not interpolate, round, convert units or fill
gaps, and says nothing about safety or accuracy at that location. Whether a
tile exists is the job of the later data access layer; full candidate
validation is Validate's job.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from hererisk.common.result import PipelineError
from hererisk.elevation.download.download import TILE_HEIGHT, TILE_WIDTH
from hererisk.elevation.normalize.convert import FORMAT, PIXELS

TILE_SIZE = TILE_WIDTH  # 256; tiles are square
MIN_ZOOM = 0
MAX_ZOOM = 30
LAT_MAX = math.degrees(math.atan(math.sinh(math.pi)))
LON_MIN = -180.0
LON_MAX = 180.0  # exclusive


def _invalid(reason: str) -> PipelineError:
    return PipelineError("INVALID_INPUT", reason)


def _check_number(value: Any, name: str) -> float:
    # Exact types only: bool (an int subclass), str, Decimal, numpy scalars... are refused.
    if type(value) not in (int, float):
        raise _invalid(f"{name} must be an int or float")
    if not math.isfinite(value):
        raise _invalid(f"{name} must be finite")
    return float(value)


@dataclass(frozen=True)
class PixelLocation:
    z: int
    tile_x: int
    tile_y: int
    pixel_x: int
    pixel_y: int
    index: int

    def __post_init__(self) -> None:
        values = (self.z, self.tile_x, self.tile_y, self.pixel_x, self.pixel_y, self.index)
        if any(type(v) is not int for v in values):
            raise _invalid("location fields must be integers")
        if not MIN_ZOOM <= self.z <= MAX_ZOOM:
            raise _invalid("zoom out of range")
        tiles = 1 << self.z
        if not (0 <= self.tile_x < tiles and 0 <= self.tile_y < tiles):
            raise _invalid("tile out of range")
        if not (0 <= self.pixel_x < TILE_SIZE and 0 <= self.pixel_y < TILE_HEIGHT):
            raise _invalid("pixel out of range")
        if self.index != self.pixel_y * TILE_SIZE + self.pixel_x:
            raise _invalid("index inconsistent with pixel")


def locate_pixel(latitude: float, longitude: float, zoom: int) -> PixelLocation:
    """XYZ tile and pixel containing (latitude, longitude) at ``zoom``."""
    lat = _check_number(latitude, "latitude")
    lon = _check_number(longitude, "longitude")
    if type(zoom) is not int or not MIN_ZOOM <= zoom <= MAX_ZOOM:
        raise _invalid("zoom must be an integer 0..30")
    if not LON_MIN <= lon < LON_MAX:
        raise _invalid("longitude outside [-180, 180)")
    if not -LAT_MAX < lat <= LAT_MAX:
        raise _invalid("latitude outside the Web Mercator range")

    world = TILE_SIZE << zoom  # N, exactly representable (<= 2^38)
    phi = math.radians(lat)
    u = world * ((lon + 180.0) / 360.0)
    v = world * ((1.0 - math.asinh(math.tan(phi)) / math.pi) / 2.0)
    ix = math.floor(u)
    iy = math.floor(v)
    # Only rounding of an accepted input can reach the outer edges.
    ix = min(max(ix, 0), world - 1)
    iy = min(max(iy, 0), world - 1)
    pixel_x = ix % TILE_SIZE
    pixel_y = iy % TILE_SIZE
    return PixelLocation(
        z=zoom,
        tile_x=ix // TILE_SIZE,
        tile_y=iy // TILE_SIZE,
        pixel_x=pixel_x,
        pixel_y=pixel_y,
        index=pixel_y * TILE_SIZE + pixel_x,
    )


def lookup_elevation(candidate: Mapping[str, Any], location: PixelLocation) -> int | None:
    """Stored value (integer cm or None) of ``location``'s pixel in a validated candidate.

    Boundary checks only (format, tile identity, array length, element type);
    the candidate's full validation belongs to Validate. Nothing is modified.
    """
    if not isinstance(location, PixelLocation):
        raise _invalid("location must be a PixelLocation")
    if not isinstance(candidate, Mapping) or candidate.get("format") != FORMAT:
        raise _invalid("not a hererisk-elevation-cm-json-v0.1 candidate")
    tile = candidate.get("tile")
    expected = (location.z, location.tile_x, location.tile_y)
    if not isinstance(tile, Mapping) or set(tile) != {"z", "x", "y"} \
            or any(type(tile[k]) is not int for k in ("z", "x", "y")) \
            or (tile["z"], tile["x"], tile["y"]) != expected:
        raise _invalid("candidate tile does not match the location")
    values = candidate.get("values_cm")
    if type(values) is not list or len(values) != PIXELS:
        raise _invalid("values_cm must be a 65536-element array")
    value = values[location.index]
    if value is not None and type(value) is not int:
        raise _invalid("stored value is neither integer nor null")
    return value
