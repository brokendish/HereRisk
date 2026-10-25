"""Municipality lookup with 国土数値情報 N03 行政区域 polygons (Phase 3-D).

The official N03 ZIP (GeoJSON member, JGD2011 lon/lat) is read once at startup. Geometry tests use
shapely (GEOS); nothing geometric is implemented here.

``locate(lat, lon)`` returns one of

* ``("inside", code)``  - the point lies inside one municipality and farther than
                          ``BOUNDARY_TOLERANCE_M`` from its boundary
* ``("ambiguous", [codes])`` - within the tolerance of a municipality boundary (inside or outside;
                          a prefecture border looks the same, the neighbour is not loaded)
* ``("outside", None)`` - no loaded polygon within the tolerance (outside the loaded prefecture)

The features of one municipality (islands, enclaves) are merged into one geometry, so the seams
between them are not boundaries. Holes are outside. This is a test against the data, not a legal
boundary decision.
"""

from __future__ import annotations

import io
import json
import math
import re
import zipfile
from pathlib import Path
from typing import Any

import shapely
from shapely.geometry import shape

BOUNDARY_TOLERANCE_M = 10.0
UNASSIGNED_CODE_SUFFIX = "000"   # N03_007 "13000" = 所属未定地
_GEOJSON = re.compile(r"(?:^|/)N03-(\d{8})_(\d{2})\.geojson\Z")


class MunicipalityDataError(ValueError):
    """The N03 file is missing or malformed. Fixed messages only."""


class N03Municipalities:
    def __init__(self, path: Path) -> None:
        try:
            with zipfile.ZipFile(Path(path)) as z:
                names = [n for n in z.namelist() if _GEOJSON.search(n)]
                if len(names) != 1:
                    raise MunicipalityDataError("the ZIP must contain exactly one N03-<date>_<pref>.geojson")
                raw = z.read(names[0])
        except (OSError, zipfile.BadZipFile) as exc:
            raise MunicipalityDataError("N03 file unavailable or not a ZIP") from exc
        try:
            doc = json.loads(raw)
            features = doc["features"]
        except (ValueError, KeyError, TypeError) as exc:
            raise MunicipalityDataError("N03 GeoJSON unreadable") from exc
        m = _GEOJSON.search(names[0])
        self.meta = {"file": names[0].rsplit("/", 1)[-1], "reference_date": f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}",
                     "prefecture_code": m.group(2), "features": len(features)}
        geoms, codes, self.names = [], [], {}
        for f in features:
            try:
                p, g = f["properties"], f["geometry"]
                code = p["N03_007"]
                if g["type"] not in ("Polygon", "MultiPolygon") or not (isinstance(code, str) and len(code) == 5):
                    raise MunicipalityDataError("N03 feature without a polygon or a 5-digit N03_007")
                geom = shape(g)
            except (KeyError, TypeError, ValueError, shapely.errors.GEOSException) as exc:
                raise MunicipalityDataError("N03 feature unreadable") from exc
            geoms.append(geom)
            codes.append(code)
            self.names[code] = {"prefecture": p["N03_001"],
                                "municipality": (p.get("N03_003") or "") + (p.get("N03_004") or "")}
        if not geoms:
            raise MunicipalityDataError("N03 has no features")
        by_code: dict[str, list[Any]] = {}
        for code, geom in zip(codes, geoms):
            by_code.setdefault(code, []).append(geom)
        self._codes = sorted(by_code)
        self._geoms = [shapely.union_all(by_code[c]) for c in self._codes]
        self._edges = [g.boundary for g in self._geoms]
        shapely.prepare(self._geoms)
        shapely.prepare(self._edges)
        self._tree = shapely.STRtree(self._geoms)

    def is_unassigned(self, code: str) -> bool:
        return code.endswith(UNASSIGNED_CODE_SUFFIX)

    def locate(self, lat: float, lon: float) -> tuple[str, Any]:
        point = shapely.Point(lon, lat)                       # GeoJSON axis order: x = lon, y = lat
        # tolerance in degrees; the longitude scale is the smaller one, so this is never too narrow
        tol = BOUNDARY_TOLERANCE_M / (111320.0 * max(0.01, math.cos(math.radians(lat))))
        near = self._tree.query(point, predicate="dwithin", distance=tol)
        if len(near) == 0:
            return "outside", None
        near_codes = sorted(self._codes[i] for i in near)
        if len(near) == 1:
            i = int(near[0])
            if self._geoms[i].contains(point) and not shapely.dwithin(self._edges[i], point, tol):
                return "inside", self._codes[i]
        return "ambiguous", near_codes
