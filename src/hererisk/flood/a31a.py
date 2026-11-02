"""Format adapter: 国土数値情報 A31a 洪水浸水想定区域（河川単位）, GeoJSON distribution ZIP.

Facts this adapter relies on (reviews/phase2/phase2a1, phase2a3; checked again in Phase 4-A):

* the ZIP name's last code (``_10`` / ``_20``) is the river class, NOT the scenario. Scenarios are
  folders inside the ZIP (``10_計画規模``, ``20_想定最大規模``, ``30_浸水継続時間`` ...); only the
  folder of the registered scenario is read
* member path ``<folder>\\A31a-<category>-<yy>_<distribution>_<river code>_<nn>.geojson``
  (backslash separator, UTF-8 names); the category in the member name must equal the folder's
* the distribution code (a prefecture, or e.g. a 地方整備局) is not a prefecture code; which area a
  source serves is a separate registration (``service_region``)
* GDAL layout: a FeatureCollection header, then exactly one Feature per line
* every Feature has exactly ``A31a_201``..``A31a_205``; ``A31a_205`` (浸水ランクコード) is an integer
  in some files and a string in others; the original type is kept, never guessed
* the metadata XML (Shift-JIS) names the product specification edition (``製品仕様書　第4.3版``)

Anything else stops the read (``A31aFormatError``); a file is never partly used.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, Iterator

FORMAT_ID = "ksj-a31a-geojson"
# 国土数値情報の利用規約: 出典と、編集・加工した旨の記載が必要（文言は未確定: Integration契約 OI-10）
ATTRIBUTION = "「国土数値情報（洪水浸水想定区域データ）」（国土交通省）を加工して作成"
SCENARIO_FOLDERS = {"maximum": ("20", "20_想定最大規模")}
PROPERTY_KEYS = ("A31a_201", "A31a_202", "A31a_203", "A31a_204", "A31a_205")
_MEMBER = re.compile(r"A31a-(?P<cat>\d{2})-(?P<yy>\d{2})_(?P<dist>\d{2})_(?P<river>\d{10})_(?P<nn>\d{2})\.geojson\Z")
_META = re.compile(r"KS-META-A31a-(?P<yy>\d{2})_(?P<dist>\d{2})_(?P<nn>\d{2})\.xml\Z")
_SPEC = re.compile(r"製品仕様書[\s　]*第(?P<v>\d+\.\d+)版")
_ZIP_NAME = re.compile(r"A31a-(?P<yy>\d{2})_(?P<dist>\d{2})_(?P<nn>\d{2})_GEOJSON\.zip\Z")

# 浸水ランクコード (product specification 第4.3版 / water_depth_code; presentation contract 7.2).
# The labels and bounds are the source's definitions; no representative depth is derived from them.
DEPTH_SCHEMES = {
    "4.3": {"scheme_id": "ksj-a31a-water-depth-rank", "scheme_version": "KS-PS-A31a-4.3",
            "classes": {"1": ("0～0.5m未満", 0.0, 0.5), "2": ("0.5～3.0m未満", 0.5, 3.0),
                        "3": ("3.0～5.0m未満", 3.0, 5.0), "4": ("5.0～10.0m未満", 5.0, 10.0),
                        "5": ("10.0～20.0m未満", 10.0, 20.0), "6": ("20.0m以上", 20.0, None)}},
}


class A31aFormatError(ValueError):
    """The file is not in the A31a layout this adapter knows. Fixed messages, no coordinates."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def normalized_member(name: str) -> str:
    return unicodedata.normalize("NFC", name.replace("\\", "/"))


def zip_name_codes(path: Path) -> dict[str, str] | None:
    m = _ZIP_NAME.search(Path(path).name)
    return m.groupdict() if m else None


def open_zip(path: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise A31aFormatError("A31a file unavailable or not a ZIP") from exc


def scenario_members(z: zipfile.ZipFile, scenario: str, distribution: str, year: str) -> list[str]:
    """Members of the registered scenario folder (sorted), each checked against the folder,
    the distribution code and the data year."""
    if scenario not in SCENARIO_FOLDERS:
        raise A31aFormatError(f"scenario {scenario!r} is not supported by {FORMAT_ID}")
    cat, folder = SCENARIO_FOLDERS[scenario]
    out = []
    for name in z.namelist():
        norm = normalized_member(name)
        head, _, base = norm.rpartition("/")
        if head != folder:
            continue
        m = _MEMBER.fullmatch(base)
        if not m:
            raise A31aFormatError("unexpected member in the scenario folder")
        if m["cat"] != cat or m["dist"] != distribution or m["yy"] != year[2:]:
            raise A31aFormatError("member category / distribution code / year does not match the registration")
        out.append(name)
    if not out:
        raise A31aFormatError("the scenario folder is missing or empty")
    return sorted(out, key=normalized_member)


def spec_edition(z: zipfile.ZipFile, distribution: str) -> str:
    metas = [n for n in z.namelist() if (m := _META.search(normalized_member(n))) and m["dist"] == distribution]
    if len(metas) != 1:
        raise A31aFormatError("exactly one KS-META-A31a XML is required")
    text = z.read(metas[0]).decode("cp932", "replace")
    editions = set(_SPEC.findall(text))
    if len(editions) != 1:
        raise A31aFormatError("the product specification edition is not stated once in the metadata")
    edition = editions.pop()
    if edition not in DEPTH_SCHEMES:
        raise A31aFormatError(f"product specification edition {edition} has no depth class table here")
    return edition


def iter_features(z: zipfile.ZipFile, member: str) -> Iterator[tuple[int, dict[str, Any]]]:
    """(feature_index, feature) for every line of the FeatureCollection; strict GDAL layout."""
    stem = normalized_member(member).rsplit("/", 1)[-1][: -len(".geojson")]
    header: list[str] = []
    index = 0
    state = "header"
    with z.open(member) as fh:
        for raw in fh:
            line = raw.decode("utf-8").strip()
            if state == "header":
                if line == '"features": [':
                    try:
                        head = json.loads("\n".join(header).rstrip().rstrip(",") + "}")
                    except ValueError as exc:
                        raise A31aFormatError("FeatureCollection header unreadable") from exc
                    if head.get("type") != "FeatureCollection" or head.get("name") != stem \
                            or (head.get("crs") or {}).get("properties", {}).get("name") != "urn:ogc:def:crs:EPSG::6668":
                        raise A31aFormatError("FeatureCollection header (type / name / EPSG:6668) not as expected")
                    state = "features"
                else:
                    header.append(line)
                continue
            if state == "features":
                if line == "]":
                    state = "end"
                    continue
                try:
                    feature = json.loads(line[:-1] if line.endswith(",") else line)
                except ValueError as exc:
                    raise A31aFormatError("a feature line is not one JSON object") from exc
                _check_feature(feature)
                yield index, feature
                index += 1
                continue
            if state == "end":
                if line == "}":
                    state = "closed"
                    continue
            if line:
                raise A31aFormatError("unexpected content after the features")
    if state != "closed":
        raise A31aFormatError("FeatureCollection not closed")


def _check_feature(f: Any) -> None:
    if not isinstance(f, dict) or f.get("type") != "Feature" or set(f) != {"type", "properties", "geometry"}:
        raise A31aFormatError("feature members not as expected")
    p, g = f["properties"], f["geometry"]
    if not isinstance(p, dict) or tuple(p) != PROPERTY_KEYS:
        raise A31aFormatError("feature properties are not exactly A31a_201..A31a_205")
    if not isinstance(g, dict) or g.get("type") not in ("Polygon", "MultiPolygon") or set(g) != {"type", "coordinates"}:
        raise A31aFormatError("feature geometry is not a Polygon / MultiPolygon")


def depth_class(edition: str, value: Any) -> dict[str, Any]:
    """The source's class for one A31a_205 value; an unknown code stops the read (no guess)."""
    if type(value) is int:
        code, value_type = str(value), "integer"
    elif isinstance(value, str) and value.isdigit():
        code, value_type = value, "string"
    else:
        raise A31aFormatError("A31a_205 is neither an integer nor a digit string")
    scheme = DEPTH_SCHEMES[edition]
    if code not in scheme["classes"]:
        raise A31aFormatError("A31a_205 is not a code of the depth class table")
    label, lower, upper = scheme["classes"][code]
    return {"scheme_id": scheme["scheme_id"], "scheme_version": scheme["scheme_version"], "class_code": code,
            "label": label, "lower_m": lower, "upper_m": upper, "bounds_inclusion": "unspecified",
            "source_value_type": value_type}


def check_coordinates(polygons: list[Any]) -> None:
    """Initial coordinate profile: finite 2-D lon/lat, -180 < lon < 180, -90 <= lat <= 90,
    closed rings of 4+ positions, no edge longer than 180 degrees of longitude."""
    for rings in polygons:
        if not isinstance(rings, list) or not rings:
            raise A31aFormatError("a polygon without rings")
        for ring in rings:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                raise A31aFormatError("a ring is not closed or too short")
            prev = None
            for pos in ring:
                if not isinstance(pos, list) or len(pos) != 2 or not all(type(v) in (int, float) for v in pos):
                    raise A31aFormatError("a position is not a 2-D number pair")
                x, y = pos
                if not (-180 < x < 180 and -90 <= y <= 90):
                    raise A31aFormatError("a position is outside the coordinate profile")
                if prev is not None and abs(x - prev) > 180:
                    raise A31aFormatError("an edge crosses the antimeridian")
                prev = x
