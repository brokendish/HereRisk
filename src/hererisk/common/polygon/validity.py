"""Validity of the component polygons of one feature (Phase 4-L).

Same rules as the flood index build (``flood.index.classify`` and ``flood.a31a.check_coordinates``),
without any hazard attribute or error code:

* ``polygons_of(geometry)``  a GeoJSON-like ``Polygon`` / ``MultiPolygon`` -> its component polygons
  (lists of rings), structure checked
* ``check_coordinates(polygons)``  finite 2-D lon/lat, -180 < lon < 180, -90 <= lat <= 90, closed rings
  of 4+ positions, no edge longer than 180 degrees of longitude. A failure raises ``GeometryInputError``
  (the input is refused, never classified)
* ``classify_components(polygons)``  per component, in order:

  ``valid``                      GEOS ``is_valid`` and not involved in a feature-level invalidity
  ``invalid_geometry``           GEOS ``is_valid`` is false (self-intersection, self-touch, too few
                                 points, hole outside the shell ...; ``detail`` is GEOS's reason)
  ``feature_invalid_component``  valid alone, but its interior overlaps, or an edge is shared with,
                                 another valid component of the same feature
  ``unverified``                 the check did not finish (GEOS raised, or the involved components of a
                                 feature-level invalidity cannot be identified). Never read as valid

Nothing is repaired (no ``make_valid``, ``buffer(0)``, vertex removal or ring rebuild) and nothing is
merged: a component is reported as it is. Only components of the same feature are compared; overlaps
between features are not this module's business (they can be meaningful, e.g. nested hazard zones).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

import shapely
from shapely.geometry import MultiPolygon, Polygon

VALID = "valid"
INVALID_GEOMETRY = "invalid_geometry"
FEATURE_INVALID_COMPONENT = "feature_invalid_component"
UNVERIFIED = "unverified"
VALIDITIES = (VALID, INVALID_GEOMETRY, FEATURE_INVALID_COMPONENT, UNVERIFIED)
VALIDATOR = f"GEOS {shapely.geos_version_string} is_valid"
OVERLAP, SHARED_EDGE = "interiors_overlap", "shared_edge"
_REASON = re.compile(r"\s*(?P<text>[^\[]*?)\s*(\[.*\])?\s*\Z")


class GeometryInputError(ValueError):
    """The geometry is refused before any classification. Fixed messages, no coordinates."""


@dataclass(frozen=True)
class Component:
    polygon_index: int
    geometry: Polygon
    validity: str
    detail: str | None = None          # GEOS reason (invalid_geometry) or a fixed text
    kind: str | None = None            # GEOS reason without location, or the feature-level kinds
    related: tuple[int, ...] = ()      # feature_invalid_component: the other components involved

    @property
    def usable(self) -> bool:
        """Only a ``valid`` component may be evaluated officially (``relation``)."""
        return self.validity == VALID

    def state(self) -> dict[str, Any]:
        out: dict[str, Any] = {"validity": self.validity, "validator": VALIDATOR}
        if self.detail is not None:
            out["detail"] = self.detail
        if self.kind is not None:
            out["kind"] = self.kind
        if self.related:
            out["related_components"] = list(self.related)
        return out


def polygons_of(geometry: Any) -> list[Any]:
    """Component polygons (each a list of rings) of a GeoJSON-like Polygon / MultiPolygon."""
    if not isinstance(geometry, dict) or geometry.get("type") not in ("Polygon", "MultiPolygon") \
            or not isinstance(geometry.get("coordinates"), list):
        raise GeometryInputError("geometry is not a Polygon / MultiPolygon")
    polys = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    if not polys:
        raise GeometryInputError("a MultiPolygon without components")
    return polys


def check_coordinates(polygons: list[Any]) -> None:
    for rings in polygons:
        if not isinstance(rings, list) or not rings:
            raise GeometryInputError("a polygon without rings")
        for ring in rings:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                raise GeometryInputError("a ring is not closed or too short")
            prev = None
            for pos in ring:
                if not isinstance(pos, list) or len(pos) != 2 or not all(type(v) in (int, float) for v in pos):
                    raise GeometryInputError("a position is not a 2-D number pair")
                x, y = pos
                if not (math.isfinite(x) and math.isfinite(y)):
                    raise GeometryInputError("a position is not finite")
                if not (-180 < x < 180 and -90 <= y <= 90):
                    raise GeometryInputError("a position is outside the coordinate range")
                if prev is not None and abs(x - prev) > 180:
                    raise GeometryInputError("an edge crosses the antimeridian")
                prev = x


def _reason_kind(reason: str) -> str:
    m = _REASON.match(reason)
    return re.sub(r"[^a-z0-9]+", "_", (m["text"] if m else reason).lower()).strip("_")


def classify_components(polygons: list[Any]) -> list[Component]:
    """Classify the components of one feature (coordinates checked first by the caller or here)."""
    check_coordinates(polygons)
    comps = []
    for rings in polygons:
        try:
            comps.append(Polygon(rings[0], rings[1:]))
        except (ValueError, TypeError, shapely.errors.GEOSException) as exc:
            raise GeometryInputError("a component polygon cannot be built") from exc
    valid: list[bool | None] = []
    for c in comps:
        try:
            valid.append(bool(c.is_valid))
        except shapely.errors.GEOSException:
            valid.append(None)
    involved: dict[int, tuple[set[str], set[int]]] = {}
    feature_checked = True
    if len(comps) > 1:
        try:
            feature_checked = _feature_level(comps, valid, involved)
        except shapely.errors.GEOSException:
            feature_checked = False
    out = []
    for i, c in enumerate(comps):
        if valid[i] is None:
            out.append(Component(i, c, UNVERIFIED, "the validity check did not finish", "validator_error"))
        elif not valid[i]:
            reason = shapely.is_valid_reason(c)
            out.append(Component(i, c, INVALID_GEOMETRY, reason, _reason_kind(reason)))
        elif i in involved:
            kinds, others = involved[i]
            out.append(Component(i, c, FEATURE_INVALID_COMPONENT, "interiors overlap or an edge is shared",
                                 "+".join(k for k in (OVERLAP, SHARED_EDGE) if k in kinds), tuple(sorted(others))))
        elif not feature_checked:
            out.append(Component(i, c, UNVERIFIED, "the feature-level check did not identify the components",
                                 "feature_level_unresolved"))
        else:
            out.append(Component(i, c, VALID))
    return out


def _feature_level(comps: list[Polygon], valid: list[bool | None],
                   involved: dict[int, tuple[set[str], set[int]]]) -> bool:
    """Pairs of valid components whose interiors overlap or that share an edge (flood.index.classify).
    False when the MultiPolygon stays invalid without them (the involved ones cannot be identified)."""
    if MultiPolygon(comps).is_valid:
        return True
    ok = [i for i, v in enumerate(valid) if v]
    tree = shapely.STRtree([comps[i] for i in ok])
    for i in ok:
        for b_pos in tree.query(comps[i]):
            j = ok[int(b_pos)]
            if j <= i:
                continue
            kinds = {k for k, pattern in ((OVERLAP, "T********"), (SHARED_EDGE, "****1****"))
                     if comps[i].relate_pattern(comps[j], pattern)}
            for a, b in ((i, j), (j, i)) if kinds else ():
                entry = involved.setdefault(a, (set(), set()))
                entry[0].update(kinds)
                entry[1].add(b)
    rest = [comps[i] for i in ok if i not in involved]
    return not (len(rest) > 1 and not MultiPolygon(rest).is_valid)
