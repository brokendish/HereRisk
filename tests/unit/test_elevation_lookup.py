"""Unit tests: elevation point lookup core (lat/lon/zoom -> pixel -> stored value).

Expected values come from fixed literals or from an independent high-precision
reference below (exact rationals for longitude, 80-digit Decimal with Taylor
series for latitude), never from the code under test.
"""

from __future__ import annotations

import copy
import math
import random
from decimal import Decimal, getcontext
from fractions import Fraction

import pytest

import fixture_builder as fb
from hererisk.common.result import PipelineError
from hererisk.elevation.lookup.core import (
    LAT_MAX,
    PixelLocation,
    locate_pixel,
    lookup_elevation,
)
from hererisk.elevation.normalize.convert import normalize_tile

# -- independent reference ------------------------------------------------------------------
getcontext().prec = 80
_PI = Decimal("3.14159265358979323846264338327950288419716939937510582097494459230781640628620899")


def _sin_cos(x: Decimal) -> tuple[Decimal, Decimal]:
    eps = Decimal(10) ** -75
    s, t, k = x, x, 1
    while abs(t) > eps:
        t = -t * x * x / ((2 * k) * (2 * k + 1))
        s += t
        k += 1
    c, t, k = Decimal(1), Decimal(1), 1
    while abs(t) > eps:
        t = -t * x * x / ((2 * k - 1) * (2 * k))
        c += t
        k += 1
    return s, c


def reference(lat: float, lon: float, z: int) -> tuple[int, int]:
    """Exact-ish global pixel (ix, iy) by the contract formula."""
    n = 256 * 2**z
    u = Fraction(n) * (Fraction(lon) + 180) / 360
    s, c = _sin_cos(Decimal(lat) * _PI / 180)
    v = Decimal(n) * (1 - ((s / c) + (1 / c)).ln() / _PI) / 2
    return math.floor(u), math.floor(v)


def global_pixel(loc: PixelLocation) -> tuple[int, int]:
    return loc.tile_x * 256 + loc.pixel_x, loc.tile_y * 256 + loc.pixel_y


def up(x: float) -> float:
    return math.nextafter(x, math.inf)


def down(x: float) -> float:
    return math.nextafter(x, -math.inf)


# -- coordinate conversion ---------------------------------------------------------------------
def test_fixed_literals() -> None:
    assert locate_pixel(0.0, 0.0, 0) == PixelLocation(0, 0, 0, 128, 128, 128 * 256 + 128)
    # Equator / prime meridian at z=1 are tile boundaries: east / south tile, pixel 0.
    assert locate_pixel(0.0, 0.0, 1) == PixelLocation(1, 1, 1, 0, 0, 0)
    assert locate_pixel(0, 0, 1) == locate_pixel(0.0, 0.0, 1)  # ints accepted
    # Tokyo Station at z=14 (well-known slippy-map tile 14552/6451).
    loc = locate_pixel(35.681236, 139.767125, 14)
    assert (loc.z, loc.tile_x, loc.tile_y) == (14, 14552, 6451)


@pytest.mark.parametrize(
    "lat,lon",
    [(35.681236, 139.767125), (43.068661, 141.350755), (26.212401, 127.680932),
     (24.3448, 124.1572), (45.5228, 141.9364), (-33.8688, 151.2093), (51.4779, -0.0015),
     (-54.8019, -68.303), (64.1466, -21.9426), (0.0001, -0.0001)],
)
@pytest.mark.parametrize("z", [0, 1, 5, 10, 14, 18, 22, 26, 30])
def test_known_points_match_reference(lat, lon, z) -> None:
    loc = locate_pixel(lat, lon, z)
    assert global_pixel(loc) == reference(lat, lon, z)
    assert loc.index == loc.pixel_y * 256 + loc.pixel_x


def test_random_points_match_reference_at_high_zoom() -> None:
    rnd = random.Random(1017)
    for z in (14, 20, 30):
        for _ in range(400):
            lat, lon = rnd.uniform(-LAT_MAX, LAT_MAX), rnd.uniform(-180, 180)
            assert global_pixel(locate_pixel(lat, lon, z)) == reference(lat, lon, z), (lat, lon, z)


def test_longitude_tile_and_pixel_boundaries() -> None:
    # z=2: lon -90 is exactly u = 256 (tile boundary); -178.59375 is u = 4 (pixel boundary).
    assert global_pixel(locate_pixel(0.5, -90.0, 2))[0] == 256
    assert global_pixel(locate_pixel(0.5, down(-90.0), 2))[0] == 255
    loc = locate_pixel(0.5, -90.0, 2)
    assert (loc.tile_x, loc.pixel_x) == (1, 0)
    loc = locate_pixel(0.5, down(-90.0), 2)
    assert (loc.tile_x, loc.pixel_x) == (0, 255)
    assert locate_pixel(0.5, -178.59375, 2).pixel_x == 4
    assert locate_pixel(0.5, down(-178.59375), 2).pixel_x == 3


def test_latitude_boundaries_at_equator() -> None:
    north = locate_pixel(1e-9, 10.0, 1)  # ~0.1 mm north: 1.4e-9 px above the boundary
    south = locate_pixel(0.0, 10.0, 1)
    assert (north.tile_y, north.pixel_y) == (0, 255)
    assert (south.tile_y, south.pixel_y) == (1, 0)  # boundary belongs to the south
    assert locate_pixel(-1e-9, 10.0, 1).tile_y == 1
    assert global_pixel(north) == reference(1e-9, 10.0, 1)


def test_sub_resolution_offset_rounds_onto_the_boundary() -> None:
    """Documented limit: an offset far below double resolution (5e-324 deg, ~1e-321 px)
    cannot be represented in v and lands on the boundary, i.e. the south pixel.
    Mathematically the point lies in the northern neighbour (0, 255); resolving it
    would need ~324 significant digits (even the 80-digit reference cannot). The
    result is still a valid pixel, never an out-of-range index."""
    loc = locate_pixel(up(0.0), 10.0, 1)
    assert (loc.tile_y, loc.pixel_y) == (1, 0)


def test_latitude_tile_boundary_neighbours_match_reference() -> None:
    # z=2 tile row boundary v = 256 lies at lat = atan(sinh(pi/2)) degrees.
    boundary = math.degrees(math.atan(math.sinh(math.pi / 2)))
    for lat in (down(down(boundary)), down(boundary), boundary, up(boundary), up(up(boundary))):
        assert global_pixel(locate_pixel(lat, 0.0, 2)) == reference(lat, 0.0, 2), lat


@pytest.mark.parametrize("z", [0, 1, 14, 29, 30])
def test_world_corners(z) -> None:
    last = (1 << z) - 1
    nw = locate_pixel(LAT_MAX, -180.0, z)
    assert nw == PixelLocation(z, 0, 0, 0, 0, 0)
    se = locate_pixel(up(-LAT_MAX), down(180.0), z)
    assert se == PixelLocation(z, last, last, 255, 255, 65535)
    ne = locate_pixel(LAT_MAX, down(180.0), z)
    assert (ne.tile_x, ne.tile_y, ne.pixel_x, ne.pixel_y) == (last, 0, 255, 0)
    sw = locate_pixel(up(-LAT_MAX), -180.0, z)
    assert (sw.tile_x, sw.tile_y, sw.pixel_x, sw.pixel_y) == (0, last, 0, 255)


def test_tile_corners_inside_one_tile() -> None:
    # Pixel centres of tile (14, 14552, 6451) computed by the inverse formula.
    z, tx, ty = 14, 14552, 6451
    n = 256 * 2**z

    def centre(px, py):
        lon = (tx * 256 + px + 0.5) / n * 360 - 180
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ty * 256 + py + 0.5) / n))))
        return lat, lon

    for px, py in [(0, 0), (255, 0), (0, 255), (255, 255), (128, 7)]:
        loc = locate_pixel(*centre(px, py), z)
        assert (loc.tile_x, loc.tile_y, loc.pixel_x, loc.pixel_y) == (tx, ty, px, py)


@pytest.mark.parametrize(
    "lat,lon",
    [
        (up(LAT_MAX), 0.0), (-LAT_MAX, 0.0), (90.0, 0.0), (-90.0, 0.0), (91.0, 0.0),
        (0.0, 180.0), (0.0, down(-180.0)), (0.0, 360.0), (0.0, -540.0),
        (math.nan, 0.0), (0.0, math.nan), (math.inf, 0.0), (0.0, -math.inf),
        (True, 0.0), (0.0, False), ("35.0", 139.0), (None, 0.0), (Decimal("1"), 0.0),
        (1 + 0j, 0.0), ([35.0], 139.0),
    ],
)
def test_invalid_coordinates_rejected(lat, lon) -> None:
    with pytest.raises(PipelineError) as err:
        locate_pixel(lat, lon, 14)
    assert err.value.error_code == "INVALID_INPUT"


def test_latitude_limits_are_inclusive_north_exclusive_south() -> None:
    assert LAT_MAX == math.degrees(math.atan(math.sinh(math.pi)))
    assert 85.0511287798 < LAT_MAX < 85.0511287799
    locate_pixel(LAT_MAX, 0.0, 30)
    locate_pixel(up(-LAT_MAX), 0.0, 30)
    for lat in (up(LAT_MAX), -LAT_MAX, down(-LAT_MAX)):
        with pytest.raises(PipelineError):
            locate_pixel(lat, 0.0, 30)


@pytest.mark.parametrize("zoom", [-1, 31, 100, True, 14.0, "14", None])
def test_invalid_zoom_rejected(zoom) -> None:
    with pytest.raises(PipelineError):
        locate_pixel(35.0, 139.0, zoom)


def test_zoom_extremes() -> None:
    assert locate_pixel(35.0, 139.0, 0).tile_x == 0
    loc = locate_pixel(35.0, 139.0, 30)
    assert 0 <= loc.tile_x < 2**30 and global_pixel(loc) == reference(35.0, 139.0, 30)


@pytest.mark.parametrize(
    "fields",
    [(14, 0, 0, 0, 0, 1), (14, 0, 0, 256, 0, 256), (31, 0, 0, 0, 0, 0), (1, 2, 0, 0, 0, 0),
     (14, 0, 0, 0, -1, -256), (14, True, 0, 0, 0, 0), (14, 0, 0, 0.0, 0, 0)],
)
def test_inconsistent_pixel_location_rejected(fields) -> None:
    with pytest.raises(PipelineError):
        PixelLocation(*fields)


# -- value lookup ------------------------------------------------------------------------------------
TILE = {"z": 14, "x": 14552, "y": 6451}


def candidate(values=None, tile=None):
    if values is None:
        values = [i if i % 7 else None for i in range(65536)]
        values[1797] = -120
        values[1799] = 0
    return {"format": "hererisk-elevation-cm-json-v0.1", "tile": dict(tile or TILE),
            "width": 256, "height": 256, "values_cm": values}


def loc(px, py, tile=TILE):
    return PixelLocation(tile["z"], tile["x"], tile["y"], px, py, py * 256 + px)


def test_returns_stored_values_unchanged() -> None:
    cand = candidate()
    assert lookup_elevation(cand, loc(5, 7)) == -120  # index 7*256+5 = 1797
    assert lookup_elevation(cand, loc(7, 7)) == 0  # index 1799: zero is a value
    assert lookup_elevation(cand, loc(0, 0)) is None  # index 0 (0 % 7 == 0): no-data
    assert lookup_elevation(cand, loc(1, 0)) == 1
    assert lookup_elevation(cand, loc(255, 255)) == 65535
    value = lookup_elevation(cand, loc(3, 2))
    assert value == 515 and type(value) is int


def test_row_major_not_column_major() -> None:
    values = [0] * 65536
    values[10 * 256 + 3] = 111  # (x=3, y=10)
    values[3 * 256 + 10] = 222  # (x=10, y=3)
    cand = candidate(values)
    assert lookup_elevation(cand, loc(3, 10)) == 111
    assert lookup_elevation(cand, loc(10, 3)) == 222


@pytest.mark.parametrize(
    "tile",
    [{"z": 13, "x": 14552, "y": 6451}, {"z": 14, "x": 14553, "y": 6451},
     {"z": 14, "x": 14552, "y": 6450}],
)
def test_tile_mismatch_rejected(tile) -> None:
    with pytest.raises(PipelineError) as err:
        lookup_elevation(candidate(tile=tile), loc(0, 0))
    assert err.value.error_code == "INVALID_INPUT"


def test_bad_candidate_boundaries_rejected() -> None:
    good = candidate()
    cases = [
        dict(good, format="other"),
        dict(good, tile={"z": 14, "x": 14552.0, "y": 6451}),
        dict(good, tile={"z": 14, "x": 14552}),
        dict(good, values_cm=good["values_cm"][:-1]),
        dict(good, values_cm=tuple(good["values_cm"])),
        "not a mapping",
    ]
    for case in cases:
        with pytest.raises(PipelineError):
            lookup_elevation(case, loc(5, 7))
    for bad in (True, 1.5, "1"):
        values = [0] * 65536
        values[1797] = bad
        with pytest.raises(PipelineError):
            lookup_elevation(candidate(values), loc(5, 7))
    with pytest.raises(PipelineError):
        lookup_elevation(good, (14, 14552, 6451, 5, 7, 1797))


def test_inputs_not_modified() -> None:
    cand = candidate()
    snapshot = copy.deepcopy(cand)
    location = loc(5, 7)
    lookup_elevation(cand, location)
    assert cand == snapshot and location == loc(5, 7)


def test_end_to_end_with_normalize_output() -> None:
    """locate_pixel + lookup on a real Normalize candidate (expected from the PNG builder rule)."""
    z, tx, ty = 14, 14550, 6450
    cand = normalize_tile(fb.make_png(3), {"z": z, "x": tx, "y": ty}, max_png_bytes=1048576)
    n = 256 * 2**z
    for px, py in [(0, 0), (37, 200), (255, 255), (94, 0)]:
        lon = (tx * 256 + px + 0.5) / n * 360 - 180
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (ty * 256 + py + 0.5) / n))))
        location = locate_pixel(lat, lon, z)
        assert (location.pixel_x, location.pixel_y) == (px, py)
        # fixture_builder.make_png(seed=3): no-data where (x+y+3) % 97 == 0,
        # else (3*1000 + x*37 + y*11) % 400000 cm.
        expected = None if (px + py + 3) % 97 == 0 else (3000 + px * 37 + py * 11) % 400000
        assert lookup_elevation(cand, location) == expected
    assert (94 + 0 + 3) % 97 == 0  # the (94, 0) case above is a no-data pixel


def test_module_is_pure() -> None:
    import ast

    from hererisk.elevation.lookup import core

    tree = ast.parse(open(core.__file__, encoding="utf-8").read())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules |= {a.name for a in node.names}
    assert modules <= {"__future__", "math", "dataclasses", "typing", "hererisk.common.result",
                       "hererisk.elevation.tile_format",
                       "hererisk.elevation.normalize.convert"}, modules
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not names & {"open", "normalize_tile", "validate_candidate", "ApiDataArea"}
