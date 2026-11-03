"""Format adapter: 国土数値情報 A40 津波浸水想定, the GeoJSON in the distribution ZIP.

Facts this adapter relies on (Phase 2-C.3 / 2-C.4 / 2-C.6, checked again in Phase 4-M against
``A40-23_13_GML.zip`` and the product specification 第2.2版):

* ZIP ``A40-<yy>_<pref>_GML.zip`` holds one folder ``A40-<yy>_<pref>_GML/`` with the GML
  (``A40-<yy>_<pref>.xml``), the GeoJSON (``A40-<yy>_<pref>.geojson``), a Shapefile and the metadata
  ``KS-META-A40-<yy>_<pref>.xml`` (Shift-JIS). The distribution page calls it "GML" although all
  formats are inside
* the metadata names the product specification edition (``製品仕様書　第2.2版``)
* GeoJSON: ``{"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "EPSG:6668"}},
  "features": [...]}``; JGD2011, GeoJSON axis order (lon, lat). Each Feature has exactly ``type``,
  ``id``, ``geometry`` (Polygon / MultiPolygon) and ``properties``
* properties are exactly ``FID`` (integer, equal to ``id`` and the position), ``A40_001`` 都道府県名
  (string), ``A40_002`` 都道府県コード (2-digit string, the code list), ``A40_003`` 津波浸水深の区分
  (string: "各都道府県の津波浸水想定調査報告書等に記載のある, 想定する浸水深のランク区分"). ``A40_003``
  is the prefecture's own wording; it is kept byte for byte (no trimming, no Unicode normalisation,
  no number is read from it) and is not the A31a depth class

Anything else stops the read (``A40FormatError``); a file is never partly used. Geometry structure and
coordinates are checked by the shared ``hererisk.common.polygon.validity`` (nothing is repaired).
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path
from typing import Any, Iterator

from hererisk.common.config import ConfigurationError, parse_strict_json
from hererisk.common.polygon import validity
from hererisk.tsunami.errors import A40FormatError

FORMAT_ID = "ksj-a40-geojson"
# 国土数値情報の利用規約: 出典と、編集・加工した旨の記載が必要（文言は未確定: 洪水と同じ OI-10）
ATTRIBUTION = "「国土数値情報（津波浸水想定データ）」（国土交通省）を加工して作成"
# the distribution page's own caution, kept for the presentation (Phase 4-M)
SOURCE_CAUTION = "実際の津波はこの津波浸水想定よりも大きい場合があります。"
PROPERTY_KEYS = ("FID", "A40_001", "A40_002", "A40_003")
DEPTH_ATTRIBUTE = "A40_003"
SUPPORTED_EDITIONS = ("2.2",)
CRS_NAMES = ("EPSG:6668", "urn:ogc:def:crs:EPSG::6668")
MAX_GEOJSON_BYTES = 512 << 20
_ZIP_NAME = re.compile(r"A40-(?P<yy>\d{2})_(?P<pref>\d{2})_GML\.zip\Z")
_SPEC = re.compile(r"製品仕様書[\s　]*第(?P<v>\d+\.\d+)版")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def zip_name_codes(path: Path) -> dict[str, str] | None:
    m = _ZIP_NAME.fullmatch(Path(path).name)
    return m.groupdict() if m else None


def members(yy: str, pref: str) -> dict[str, str]:
    folder = f"A40-{yy}_{pref}_GML/"
    return {"folder": folder, "geojson": f"{folder}A40-{yy}_{pref}.geojson", "gml": f"{folder}A40-{yy}_{pref}.xml",
            "metadata": f"{folder}KS-META-A40-{yy}_{pref}.xml"}


def open_zip(path: Path) -> tuple[zipfile.ZipFile, dict[str, str]]:
    codes = zip_name_codes(path)
    if codes is None:
        raise A40FormatError("not an A40 ZIP name (A40-<yy>_<pref>_GML.zip)")
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise A40FormatError("A40 file unavailable or not a ZIP") from exc
    m = members(codes["yy"], codes["pref"])
    names = set(z.namelist())
    if not {m["geojson"], m["gml"], m["metadata"]} <= names or any(not n.startswith(m["folder"]) for n in names):
        z.close()
        raise A40FormatError("the ZIP does not hold the expected A40 folder, GeoJSON, GML and metadata")
    return z, m


def spec_edition(z: zipfile.ZipFile, m: dict[str, str]) -> str:
    text = z.read(m["metadata"]).decode("cp932", "replace")
    if "A40" not in text:
        raise A40FormatError("the metadata does not name A40")
    editions = set(_SPEC.findall(text))
    if len(editions) != 1:
        raise A40FormatError("the product specification edition is not stated once in the metadata")
    edition = editions.pop()
    if edition not in SUPPORTED_EDITIONS:
        raise A40FormatError(f"product specification edition {edition} is not supported here")
    return edition


def read_features(z: zipfile.ZipFile, m: dict[str, str], prefecture_code: str) -> Iterator[dict[str, Any]]:
    """Every feature of the GeoJSON, checked, in file order:
    {feature_index, fid, prefecture_name, prefecture_code, depth_label, polygons}."""
    info = z.getinfo(m["geojson"])
    if info.file_size > MAX_GEOJSON_BYTES:
        raise A40FormatError("the GeoJSON is larger than this adapter reads")
    try:
        doc = parse_strict_json(z.read(m["geojson"]))
    except ConfigurationError as exc:
        raise A40FormatError("the GeoJSON is not strict JSON") from exc
    if not isinstance(doc, dict) or set(doc) != {"type", "crs", "features"} or doc["type"] != "FeatureCollection":
        raise A40FormatError("not a FeatureCollection with crs and features")
    crs = doc["crs"]
    if not isinstance(crs, dict) or crs.get("type") != "name" or set(crs) != {"type", "properties"} \
            or not isinstance(crs["properties"], dict) or crs["properties"].get("name") not in CRS_NAMES:
        raise A40FormatError("the crs is not EPSG:6668 (JGD2011)")
    features = doc["features"]
    if not isinstance(features, list) or not features:
        raise A40FormatError("the FeatureCollection has no features")
    for i, f in enumerate(features):
        if not isinstance(f, dict) or set(f) != {"type", "id", "geometry", "properties"} or f["type"] != "Feature":
            raise A40FormatError("feature members not as expected")
        p = f["properties"]
        if not isinstance(p, dict) or tuple(p) != PROPERTY_KEYS:
            raise A40FormatError("feature properties are not exactly FID, A40_001..A40_003")
        if type(p["FID"]) is not int or p["FID"] != i or f["id"] != i:
            raise A40FormatError("FID / id is not the feature's position")
        if not all(isinstance(p[k], str) and p[k] for k in ("A40_001", "A40_002", "A40_003")):
            raise A40FormatError("A40_001..A40_003 must be non-empty strings")
        if p["A40_002"] != prefecture_code:
            raise A40FormatError("A40_002 (prefecture code) does not match the registration")
        try:
            polys = validity.polygons_of(f["geometry"])
            if set(f["geometry"]) != {"type", "coordinates"}:
                raise A40FormatError("feature geometry has unexpected members")
            validity.check_coordinates(polys)
        except validity.GeometryInputError as exc:
            raise A40FormatError(f"feature geometry refused ({exc})") from exc
        yield {"feature_index": i, "fid": p["FID"], "prefecture_name": p["A40_001"], "prefecture_code": p["A40_002"],
               "depth_label": p[DEPTH_ATTRIBUTE], "polygons": polys}
