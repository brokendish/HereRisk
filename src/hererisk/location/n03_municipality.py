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

from hererisk.location.address_provider import AddressDataError

BOUNDARY_TOLERANCE_M = 10.0
UNASSIGNED_CODE_SUFFIX = "000"   # N03_007 "13000" = 所属未定地
_GEOJSON = re.compile(r"(?:^|/)N03-(\d{8})_(\d{2})\.geojson\Z")


class MunicipalityDataError(AddressDataError):
    """The N03 file is missing or malformed. Fixed messages only."""


def _read_file(path: Path, expected_prefecture: str | None) -> tuple[dict[str, Any], list[tuple[str, Any, dict[str, str]]]]:
    """One N03 ZIP -> (meta, [(code, geometry, names)]). The prefecture code comes from the file
    name and must match every N03_007 and, if given, the registered prefecture code."""
    try:
        with zipfile.ZipFile(Path(path)) as z:
            members = [n for n in z.namelist() if _GEOJSON.search(n)]
            if len(members) != 1:
                raise MunicipalityDataError("the ZIP must contain exactly one N03-<date>_<pref>.geojson")
            raw = z.read(members[0])
    except (OSError, zipfile.BadZipFile) as exc:
        raise MunicipalityDataError("N03 file unavailable or not a ZIP") from exc
    m = _GEOJSON.search(members[0])
    pref = m.group(2)
    if expected_prefecture is not None and pref != expected_prefecture:
        raise MunicipalityDataError(f"N03 file is for prefecture {pref}, registered as {expected_prefecture}")
    try:
        features = json.loads(raw)["features"]
    except (ValueError, KeyError, TypeError) as exc:
        raise MunicipalityDataError("N03 GeoJSON unreadable") from exc
    meta = {"file": members[0].rsplit("/", 1)[-1], "prefecture_code": pref, "features": len(features),
            "reference_date": f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]}"}
    out = []
    for f in features:
        try:
            p, g = f["properties"], f["geometry"]
            code = p["N03_007"]
            if g["type"] not in ("Polygon", "MultiPolygon") or not (isinstance(code, str) and len(code) == 5):
                raise MunicipalityDataError("N03 feature without a polygon or a 5-digit N03_007")
            geom = shape(g)
        except (KeyError, TypeError, ValueError, shapely.errors.GEOSException) as exc:
            raise MunicipalityDataError("N03 feature unreadable") from exc
        if not code.startswith(pref):
            raise MunicipalityDataError(f"N03 code {code} is not in prefecture {pref}")
        # 郡・政令市名 + 市区町村名 + 政令市の区名 (e.g. 西多摩郡奥多摩町, 川崎市川崎区)
        name = "".join(p.get(k) or "" for k in ("N03_003", "N03_004", "N03_005"))
        out.append((code, geom, {"prefecture": p["N03_001"], "prefecture_code": pref, "municipality": name}))
    if not out:
        raise MunicipalityDataError("N03 has no features")
    return meta, out


class N03Municipalities:
    """Polygons of one or more prefectures, searched together.

    ``files``: one N03 ZIP path, or a list of ``(registered prefecture code or None, path)``.
    A municipality code may come from one file only.
    """

    def __init__(self, files: Any) -> None:
        if isinstance(files, (str, Path)):
            files = [(None, files)]
        self.files: dict[str, dict[str, Any]] = {}
        by_code: dict[str, list[Any]] = {}
        self.names: dict[str, dict[str, str]] = {}
        for expected, path in files:
            meta, items = _read_file(Path(path), expected)
            if meta["prefecture_code"] in self.files:
                raise MunicipalityDataError(f"prefecture {meta['prefecture_code']} registered twice")
            self.files[meta["prefecture_code"]] = meta
            for code, geom, names in items:
                by_code.setdefault(code, []).append(geom)
                self.names[code] = names
        self.meta = next(iter(self.files.values())) if len(self.files) == 1 else {"files": list(self.files.values())}
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
