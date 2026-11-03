"""Official geometric relation of a point to component polygons (Phase 4-L).

Same rules as the flood provider's search (``location.flood_provider._Source.search``), without any
hazard attribute:

* a ``valid`` component (``validity``) is evaluated with GEOS: ``contains`` -> ``inside``, else
  ``intersects`` -> ``on_boundary``, else ``outside``. Exact, whatever the polygon's size (no radius)
* any other component (``invalid_geometry`` / ``feature_invalid_component`` / ``unverified``, or no
  validity given) is never evaluated: if the point is in its bounding box (edge included) it is
  ``pending_geometry`` (relation unknown), otherwise it is not a candidate. The bounding box is not the
  polygon's interior: a pending component is neither inside nor outside

``relate(component, x, y)`` is the pure single-component function (``outside`` is a result there).
``ComponentIndex.search(x, y)`` lists, over many components and sources, only ``inside`` /
``on_boundary`` / ``pending_geometry`` (contract v0.2 3.1: an outside component is not listed). Each
component stays its own entry: nothing is merged, ranked, reduced or compared, and an empty list is not
a statement of safety (the provider decides what it means). Above ``max_features`` or on a failure the
call returns ``complete: false`` and ``features: null``, never a partial list.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

import shapely

from hererisk.common.polygon.validity import UNVERIFIED, VALID, VALIDITIES

INSIDE, ON_BOUNDARY, OUTSIDE = "inside", "on_boundary", "outside"
EVALUATED, PENDING, NOT_CANDIDATE = "evaluated", "pending_geometry", "outside_bounding_box"
COMPLETE, LIMIT_EXCEEDED, FAILED = "complete", "limit_exceeded", "failed"
MAX_FEATURES = 500


class RelationInputError(ValueError):
    """The call or the components are refused (bad point, unknown validity, not a polygon)."""


@dataclass(frozen=True)
class Candidate:
    """One component polygon as the provider's index holds it. ``geometry``: a shapely Polygon or WKB."""
    source_id: str
    feature_ref: str
    geometry: Any
    validity: str | None = None        # None: no validity information -> treated as unverified
    detail: str | None = None


def _point(x: Any, y: Any) -> tuple[float, float]:
    if not all(type(v) in (int, float) and math.isfinite(v) for v in (x, y)):
        raise RelationInputError("the point is not a pair of finite numbers")
    return float(x), float(y)


def _geometry(g: Any) -> Any:
    if isinstance(g, (bytes, bytearray, memoryview)):
        try:
            g = shapely.from_wkb(bytes(g))
        except (shapely.errors.GEOSException, ValueError, TypeError) as exc:
            raise RelationInputError("a component geometry cannot be read") from exc
    if not isinstance(g, shapely.Polygon) or g.is_empty:
        raise RelationInputError("a component geometry is not a polygon")
    return g


def _validity(v: str | None) -> str:
    if v is None:
        return UNVERIFIED
    if v not in VALIDITIES:
        raise RelationInputError("unknown validity")
    return v


def relate(geometry: Any, validity: str | None, x: float, y: float) -> dict[str, Any]:
    """One component: {evaluation, relation}. ``outside`` only for a valid component."""
    x, y = _point(x, y)
    g, v = _geometry(geometry), _validity(validity)
    if v == VALID:
        pt = shapely.Point(x, y)
        rel = INSIDE if g.contains(pt) else ON_BOUNDARY if g.intersects(pt) else OUTSIDE
        return {"evaluation": EVALUATED, "relation": rel}
    minx, miny, maxx, maxy = g.bounds
    hit = minx <= x <= maxx and miny <= y <= maxy          # boundary included
    return {"evaluation": PENDING if hit else NOT_CANDIDATE, "relation": None}


class ComponentIndex:
    """Candidate filtering (STRtree on the usable geometries and on the others' bounding boxes) apart
    from the relation itself. Holds what the caller gives (an iterable: rows can be streamed); it does
    not load a data set by itself. Like the flood provider, only the bounding box of a pending
    component is kept, not its geometry."""

    def __init__(self, candidates: Iterable[Candidate]) -> None:
        self._order: dict[str, int] = {}
        self._valid: list[tuple[tuple[str, str, str | None], Any]] = []
        self._pending: list[tuple[tuple[str, str, str | None], str, tuple[float, float, float, float]]] = []
        for c in candidates:
            if not isinstance(c, Candidate) or not isinstance(c.source_id, str) or not isinstance(c.feature_ref, str):
                raise RelationInputError("a candidate needs a source_id and a feature_ref")
            self._order.setdefault(c.source_id, len(self._order))
            g, v = _geometry(c.geometry), _validity(c.validity)
            ids = (c.source_id, c.feature_ref, c.detail)
            if v == VALID:
                self._valid.append((ids, g))
            else:
                self._pending.append((ids, v, g.bounds))
        self._tree = shapely.STRtree([g for _, g in self._valid])
        self._ptree = shapely.STRtree([shapely.box(*b) for _, _, b in self._pending])

    def __len__(self) -> int:
        return len(self._valid) + len(self._pending)

    def search(self, x: float, y: float, *, max_features: int = MAX_FEATURES) -> dict[str, Any]:
        x, y = _point(x, y)
        try:
            features = self._search(x, y)
        except Exception:      # noqa: BLE001  any failure: no partial list, no detail outside
            return {"status": FAILED, "complete": False, "features": None}
        if len(features) > max_features:
            return {"status": LIMIT_EXCEEDED, "complete": False, "features": None,
                    "limit": {"type": "max_features", "value": max_features}}
        features.sort(key=lambda f: (self._order[f["source_id"]], f["feature_ref"]))
        return {"status": COMPLETE, "complete": True, "features": features}

    def _search(self, x: float, y: float) -> list[dict[str, Any]]:
        pt = shapely.Point(x, y)
        out = []
        for i in self._tree.query(pt):
            c, g = self._valid[int(i)]
            if g.contains(pt):
                rel = INSIDE
            elif g.intersects(pt):
                rel = ON_BOUNDARY
            else:
                continue                                   # outside: not listed (contract v0.2 3.1)
            out.append(_feature(c, VALID, EVALUATED, rel))
        for i in self._ptree.query(pt):
            c, v, (minx, miny, maxx, maxy) = self._pending[int(i)]
            if minx <= x <= maxx and miny <= y <= maxy:    # boundary included
                out.append(_feature(c, v, PENDING, None))
        return out


def _feature(ids: tuple[str, str, str | None], validity: str, evaluation: str, relation: str | None) -> dict[str, Any]:
    source_id, feature_ref, detail = ids
    state = {"validity": validity}
    if detail is not None:
        state["detail"] = detail
    return {"source_id": source_id, "feature_ref": feature_ref, "evaluation": evaluation,
            "relation": relation, "geometry_state": state}
