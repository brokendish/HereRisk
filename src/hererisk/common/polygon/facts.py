"""Geometric facts of one point against the rings of one component (Phase 4-K).

The rings are given piece by piece (``RayCounter.add``: a ring index and consecutive vertices, any
number of pieces per ring, each piece sharing its end vertex with the next). Nothing is held but one
piece, the per-ring counters and the nearest boundary distance, so memory does not grow with the
polygon. ``facts_from_rings`` is the in-memory convenience for whole rings.

Facts (contract v0.2, ``analysis_state.far_reading`` and Phase 4-J):

* ``raw_winding_per_ring``  signed crossings of one ray from the point (the shortest way out of the
  component's bounding box: east / west / north / south), per ring, in the stored direction. A ring
  the ray does not meet is 0. Same half-open rule and arithmetic as the Phase 4-D diagnosis index
* ``area_sign_per_ring``, ``ring_role`` (``shell`` / ``hole``): given by the caller (the index stores them)
* ``winding_normalised`` = sum(role sign x area sign x raw), ``parity_inside`` = odd total crossings
* ``h_winding_parity``: normalised winding in {0, 1} and the parity agrees
* ``h2_per_ring_unit``: H and every ring's area sign x raw in {0, 1}; a ring of zero signed area has raw 0
* ``on_boundary`` (unrounded nearest distance < ``ON_BOUNDARY_M``), ``boundary_distance_m`` (the
  nearest distance among the pieces within ``boundary_search_m`` of the point, unrounded; ``None``
  when no piece is that close: it is NOT the distance to the whole polygon)

Scope of H2 (Phase 4-J.1 audit, counterexample B1): H2 guarantees only that the even-odd reading and
the normalised nonzero reading of these rings agree at the point. It does not mean that every repair or
interpretation agrees (a ring traversing an edge forwards and backwards cancels to raw 0 under H2,
while a linework repair reads the point inside), it is not an official inside / outside, and it says
nothing about the intent of the data's author. On the boundary the ray readings are not defined and
are returned as ``None``. Distances: local plane at the point's latitude (111,320 m per degree, the
longitude scaled by cos(lat)); coordinates are lon / lat as stored, not transformed.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import numpy as np

METHOD = "ray-crossing-per-ring-v1"
ON_BOUNDARY_M = 0.001          # unchanged from the diagnosis (Phase 4-C); strict "<" on the unrounded value
M_PER_DEG = 111320.0
H2_SCOPE = ("even-odd and normalised nonzero agree at the point; not every interpretation, not an "
            "official relation, not the author's intent")


def scale(lat: float) -> tuple[float, float]:
    return M_PER_DEG * math.cos(math.radians(lat)), M_PER_DEG


def ray_direction(bbox: tuple[float, float, float, float], lat: float, lon: float) -> tuple[str, tuple]:
    """The shortest way out of the bounding box (minx, miny, maxx, maxy) and the ray's box."""
    minx, miny, maxx, maxy = bbox
    kx, ky = scale(lat)
    ways = {"east": (maxx - lon) * kx, "west": (lon - minx) * kx, "north": (maxy - lat) * ky, "south": (lat - miny) * ky}
    way = min(ways, key=ways.get)
    box = {"east": (lon, lat, maxx, lat), "west": (minx, lat, lon, lat),
           "north": (lon, lat, lon, maxy), "south": (lon, miny, lon, lat)}[way]
    return way, box


class RayCounter:
    """Accumulates the facts of one point over ring pieces, one piece at a time."""

    def __init__(self, lat: float, lon: float, way: str, ring_count: int, *, boundary_search_m: float = 1.0) -> None:
        self.lat, self.lon, self.way = lat, lon, way
        self.kx, self.ky = scale(lat)
        self.raw = np.zeros(ring_count, dtype=np.int64)
        self.crossings = 0
        self.boundary_search_m = boundary_search_m
        self.nearest_m: float | None = None
        self.pieces = 0
        self.segments = 0

    def _rotated(self, x1, y1, x2, y2):
        lon, lat = self.lon, self.lat
        return {"east": (x1, y1, x2, y2, lon, lat), "west": (-x1, -y1, -x2, -y2, -lon, -lat),
                "north": (y1, -x1, y2, -x2, lat, -lon), "south": (-y1, x1, -y2, x2, -lat, lon)}[self.way]

    def add_ray_piece(self, ring: int, vertices: np.ndarray) -> None:
        """Count the crossings of the ray with the segments of one piece (consecutive vertices of a ring)."""
        if not 0 <= ring < len(self.raw):
            raise ValueError("ring index out of range")
        v = np.asarray(vertices, dtype=np.float64)
        if len(v) < 2:
            return
        u1, v1, u2, v2, u0, v0 = self._rotated(v[:-1, 0], v[:-1, 1], v[1:, 0], v[1:, 1])
        up = (v1 <= v0) & (v2 > v0)
        dn = (v2 <= v0) & (v1 > v0)
        i = np.nonzero(up | dn)[0]
        if len(i):
            ui = u1[i] + (v0 - v1[i]) * (u2[i] - u1[i]) / (v2[i] - v1[i])
            right = ui > u0
            self.raw[ring] += int(np.sum(np.where(up[i][right], 1, -1)))
            self.crossings += int(right.sum())
        self.pieces += 1
        self.segments += len(v) - 1

    def add_boundary_piece(self, vertices: np.ndarray) -> None:
        """Update the nearest distance (m, unrounded) with the segments of one piece."""
        v = np.asarray(vertices, dtype=np.float64)
        if len(v) < 2:
            return
        ax, ay = (v[:-1, 0] - self.lon) * self.kx, (v[:-1, 1] - self.lat) * self.ky
        bx, by = (v[1:, 0] - self.lon) * self.kx, (v[1:, 1] - self.lat) * self.ky
        dx, dy = bx - ax, by - ay
        den = dx * dx + dy * dy
        t = np.clip(np.divide(-(ax * dx + ay * dy), den, out=np.zeros_like(den), where=den > 0), 0.0, 1.0)
        d = float(np.min(np.hypot(ax + t * dx, ay + t * dy)))
        if d <= self.boundary_search_m and (self.nearest_m is None or d < self.nearest_m):
            self.nearest_m = d

    def result(self, area_sign: Iterable[int], holes: Iterable[bool]) -> dict[str, Any]:
        area_sign = [int(a) for a in area_sign]
        holes = [bool(h) for h in holes]
        if len(area_sign) != len(self.raw) or len(holes) != len(self.raw):
            raise ValueError("ring metadata does not match the ring count")
        on = self.nearest_m is not None and self.nearest_m < ON_BOUNDARY_M
        raw = [int(r) for r in self.raw]
        out: dict[str, Any] = {
            "method": METHOD, "ray": self.way, "ring_role": ["hole" if h else "shell" for h in holes],
            "area_sign_per_ring": area_sign, "on_boundary": on, "boundary_distance_m": self.nearest_m,
            "boundary_search_m": self.boundary_search_m, "h2_scope": H2_SCOPE,
            "ray_read": {"pieces": self.pieces, "segments": self.segments},
        }
        if on:      # the ray readings are not defined on a ring
            return {**out, "raw_winding_per_ring": None, "winding_normalised": None, "parity_inside": None,
                    "h_winding_parity": None, "h2_per_ring_unit": None, "zero_area_ring_around_point": None}
        w = sum(r * a * (-1 if h else 1) for r, a, h in zip(raw, area_sign, holes))
        parity = bool(self.crossings % 2)
        h = w in (0, 1) and parity == (w == 1)
        unit = all((r == 0) if a == 0 else (r * a in (0, 1)) for r, a in zip(raw, area_sign))
        return {**out, "raw_winding_per_ring": raw, "winding_normalised": int(w), "parity_inside": parity,
                "h_winding_parity": h, "h2_per_ring_unit": bool(h and unit),
                "zero_area_ring_around_point": any(a == 0 and r != 0 for r, a in zip(raw, area_sign))}


def signed_area_sign(ring: np.ndarray) -> int:
    c = np.asarray(ring, dtype=np.float64)
    a = 0.5 * float(np.sum(c[:-1, 0] * c[1:, 1] - c[1:, 0] * c[:-1, 1]))
    return (a > 0) - (a < 0)


def facts_from_rings(rings: list[Any], lat: float, lon: float, *, holes: list[bool] | None = None,
                     boundary_search_m: float = 1.0) -> dict[str, Any]:
    """Facts for whole closed rings (lon / lat vertex arrays; the first is the shell unless ``holes``)."""
    arrays = [np.asarray(r, dtype=np.float64) for r in rings]
    if not arrays or any(len(a) < 4 or not np.array_equal(a[0], a[-1]) for a in arrays):
        raise ValueError("rings must be closed with at least 4 positions")
    holes = holes if holes is not None else [k > 0 for k in range(len(arrays))]
    allv = np.concatenate(arrays)
    bbox = (float(allv[:, 0].min()), float(allv[:, 1].min()), float(allv[:, 0].max()), float(allv[:, 1].max()))
    way, _ = ray_direction(bbox, lat, lon)
    c = RayCounter(lat, lon, way, len(arrays), boundary_search_m=boundary_search_m)
    for k, a in enumerate(arrays):
        c.add_ray_piece(k, a)
        c.add_boundary_piece(a)
    return {"status": "complete", "complete": True, **c.result([signed_area_sign(a) for a in arrays], holes)}
