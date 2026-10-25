"""MlitAddressProvider: the ``address`` section from MLIT 大字・町丁目レベル位置参照情報 (Phase 3-C).

The official ZIP (or its CSV, Shift-JIS) is read once at startup. A request returns the
representative point nearest to the given position (Haversine distance), as an *estimate*:
``method: nearest_representative_point``, ``is_confirmed_address: false``. This is not a decision
that the point lies inside that 町丁目 or that prefecture.

Distance limit: a match is returned only if it lies within ``max(MIN_LIMIT_M, local spacing)``,
capped at ``MAX_LIMIT_M``, where the local spacing of a representative point is the distance to
its nearest other representative point (sparse rural 大字 get a larger radius than dense city
町丁目). Beyond the limit the section is ``not_available`` (``reason: out_of_coverage``) and no
address is returned. The limit reduces, but does not remove, wrong answers near the edge of the
loaded data (e.g. just across a prefecture border); see docs/api/location-api-v0.1.md 8.2.

With N03 polygons (``municipalities``, Phase 3-D) the municipality is decided first by
point-in-polygon, and only that municipality's representative points are searched
(``method: municipality_polygon_and_nearest_point``). If no point of that municipality lies within
the limit, the municipality alone is returned (``precision: municipality``). Outside every loaded
polygon -> ``out_of_coverage``; on / near a municipality boundary -> ``unknown`` with the candidate
municipalities. There is no fallback to the plain distance search in that mode.

Nothing about a request (position, address) is logged.
"""

from __future__ import annotations

import bisect
import csv
import io
import math
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hererisk.location.model import AVAILABLE, NOT_AVAILABLE, UNKNOWN

HEADER = ["都道府県コード", "都道府県名", "市区町村コード", "市区町村名", "大字町丁目コード", "大字町丁目名",
          "緯度", "経度", "原典資料コード", "大字・字・丁目区分コード"]
EARTH_RADIUS_M = 6371008.8
MIN_LIMIT_M = 500.0
MAX_LIMIT_M = 10000.0
MAX_FILE_BYTES = 64 * 1024 * 1024
# 大字・字・丁目区分コード -> precision
PRECISION = {"3": "chome", "1": "oaza", "2": "aza", "0": "oaza_or_common_name"}
_CSV_NAME = re.compile(r"(?:^|/)(\d{2})_(\d{4})\.csv\Z")
_EDITION_DIR = re.compile(r"(?:^|/)\d{5}-(\d+\.\d+[a-z]?)/")


class AddressDataError(ValueError):
    """The data file is missing or malformed. The message names the row, never a request."""


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


@dataclass(frozen=True)
class Point:
    lat: float
    lon: float
    prefecture: str
    municipality_code: str
    municipality: str
    area: str
    area_code: str
    area_type: str


def _read(path: Path) -> tuple[str, str, str | None]:
    """Returns (csv text, csv member name, edition or None)."""
    path = Path(path)
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise AddressDataError("data file too large")
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                names = [n for n in z.namelist() if _CSV_NAME.search(n)]
                if len(names) != 1:
                    raise AddressDataError("the ZIP must contain exactly one <pref>_<year>.csv")
                raw, name = z.read(names[0]), names[0]
        else:
            raw, name = path.read_bytes(), path.name
    except OSError as exc:
        raise AddressDataError("data file unavailable") from exc
    try:
        text = raw.decode("cp932")
    except UnicodeDecodeError as exc:
        raise AddressDataError("data file is not Shift-JIS (cp932)") from exc
    edition = _EDITION_DIR.search(name)
    return text, name, edition.group(1) if edition else None


def load_points(path: Path) -> tuple[list[Point], dict[str, Any]]:
    text, name, edition = _read(path)
    reader = csv.reader(io.StringIO(text, newline=""))
    if next(reader, None) != HEADER:
        raise AddressDataError("unexpected CSV header")
    points = []
    for lineno, row in enumerate(reader, start=2):
        if not row:
            continue
        if len(row) != len(HEADER):
            raise AddressDataError(f"row {lineno}: {len(row)} columns")
        pref_code, pref, city_code, city, area_code, area, lat_s, lon_s, _, area_type = row
        try:
            lat, lon = float(lat_s), float(lon_s)
        except ValueError as exc:
            raise AddressDataError(f"row {lineno}: latitude / longitude not numeric") from exc
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or not all(math.isfinite(v) for v in (lat, lon)):
            raise AddressDataError(f"row {lineno}: latitude / longitude out of range")
        if not (pref and city and area) or area_type not in PRECISION:
            raise AddressDataError(f"row {lineno}: missing name or unknown area type")
        points.append(Point(lat, lon, pref, city_code, city, area, area_code, area_type))
    if not points:
        raise AddressDataError("no rows")
    m = _CSV_NAME.search(name)
    meta = {"file": name.rsplit("/", 1)[-1], "prefecture_code": m.group(1), "year": m.group(2), "edition": edition,
            "rows": len(points)}
    return points, meta


class PointSet:
    def __init__(self, points: list[Point]) -> None:
        self.points = sorted(points, key=lambda p: p.lat)
        self._lats = [p.lat for p in self.points]

    def nearest(self, lat: float, lon: float, skip: int = -1) -> tuple[float, int]:
        """Exact nearest point: scan outwards in latitude order; |dlat| * R bounds the distance."""
        best, best_i = math.inf, -1
        start = bisect.bisect_left(self._lats, lat)
        lo, hi = start - 1, start
        n = len(self.points)
        while lo >= 0 or hi < n:
            for i in (lo, hi):
                if 0 <= i < n and i != skip:
                    p = self.points[i]
                    d = haversine_m(lat, lon, p.lat, p.lon)
                    if d < best:
                        best, best_i = d, i
            gap_lo = math.radians(lat - self._lats[lo]) * EARTH_RADIUS_M if lo >= 0 else math.inf
            gap_hi = math.radians(self._lats[hi] - lat) * EARTH_RADIUS_M if hi < n else math.inf
            if min(gap_lo, gap_hi) > best:
                break
            lo, hi = lo - 1, hi + 1
        return best, best_i


class MlitAddressProvider:
    id = "mlit_address"

    def __init__(self, path: Path, municipalities: Any = None) -> None:
        """``municipalities``: an ``N03Municipalities`` (Phase 3-D) or None (distance only)."""
        points, self.meta = load_points(path)
        self._all = PointSet(points)
        self._points = self._all.points
        # the limit uses the spacing to the nearest other point of the whole file
        self._limit = {id(p): min(MAX_LIMIT_M, max(MIN_LIMIT_M, self._all.nearest(p.lat, p.lon, skip=i)[0]))
                       for i, p in enumerate(self._points)}
        self._n03 = municipalities
        self._by_code: dict[str, PointSet] = {}
        if municipalities is not None:
            groups: dict[str, list[Point]] = {}
            for p in points:
                groups.setdefault(p.municipality_code, []).append(p)
            self._by_code = {code: PointSet(ps) for code, ps in groups.items()}
            self.meta["codes_without_polygon"] = sorted(set(groups) - set(municipalities.names))
        year, edition = self.meta["year"], self.meta["edition"]
        self._source = {"organization": "国土交通省", "title": "大字・町丁目レベル位置参照情報",
                        "data_version": year,
                        "page_url": "https://nlftp.mlit.go.jp/cgi-bin/isj/dls/_choose_method.cgi",
                        "attribution": {"text": f"位置参照情報 国土交通省（{year}年、{self.meta['file']}）"}}
        if edition:
            self._source["edition"] = edition
        if municipalities is not None:
            n = municipalities.meta
            self._boundary_source = {
                "organization": "国土交通省", "title": "国土数値情報（行政区域データ）", "data_version": n["reference_date"],
                "page_url": f"https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-{n['reference_date'][:4]}.html",
                "attribution": {"text": f"「国土数値情報（行政区域データ）」（国土交通省）（{n['file']}）を加工して作成"}}

    def _nearest(self, lat: float, lon: float, skip: int = -1) -> tuple[float, int]:
        return self._all.nearest(lat, lon, skip)

    def _chome(self, p: Point, distance: float, method: str) -> dict[str, Any]:
        return {"display_name": f"{p.prefecture}{p.municipality}{p.area}付近",
                "prefecture": p.prefecture, "municipality": p.municipality, "municipality_code": p.municipality_code,
                "area": p.area, "area_code": p.area_code, "precision": PRECISION[p.area_type], "method": method,
                "is_confirmed_address": False, "distance_m": round(distance, 1),
                "max_distance_m": round(self._limit[id(p)], 1)}

    def lookup(self, lat: float, lon: float) -> dict[str, Any]:
        base = {"provider": self.id, "synthetic": False, "source": self._source}
        if self._n03 is not None:
            return self._lookup_with_polygons(lat, lon, {**base, "boundary_source": self._boundary_source})
        distance, i = self._nearest(lat, lon)
        if i < 0 or distance > self._limit[id(self._points[i])]:
            return {**base, "status": NOT_AVAILABLE, "result": None, "reason": "out_of_coverage"}
        return {**base, "status": AVAILABLE, "result": self._chome(self._points[i], distance, "nearest_representative_point")}

    def _lookup_with_polygons(self, lat: float, lon: float, base: dict[str, Any]) -> dict[str, Any]:
        state, value = self._n03.locate(lat, lon)
        if state == "outside":
            return {**base, "status": NOT_AVAILABLE, "result": None, "reason": "out_of_coverage"}
        if state == "ambiguous":
            return {**base, "status": UNKNOWN, "result": None, "reason": "municipality_boundary_ambiguous",
                    "candidates": [{"municipality_code": c, **self._n03.names[c]} for c in value]}
        code = value
        names = self._n03.names[code]
        partial = {"prefecture": names["prefecture"], "municipality_code": code, "area": None,
                   "method": "municipality_polygon", "is_confirmed_address": False}
        if self._n03.is_unassigned(code):        # N03 所属未定地: the source does not assign a municipality
            return {**base, "status": AVAILABLE, "result": {
                **partial, "display_name": f"{names['prefecture']}（所属未定地）", "municipality": None,
                "precision": "prefecture", "area_reason": "municipality_unassigned_in_source"}}
        candidates = self._by_code.get(code)
        if candidates is not None:
            distance, i = candidates.nearest(lat, lon)
            p = candidates.points[i]
            if distance <= self._limit[id(p)]:
                return {**base, "status": AVAILABLE,
                        "result": self._chome(p, distance, "municipality_polygon_and_nearest_point")}
        return {**base, "status": AVAILABLE, "result": {
            **partial, "display_name": f"{names['prefecture']}{names['municipality']}", "municipality": names["municipality"],
            "precision": "municipality", "area_reason": "no_representative_point_within_limit"}}
