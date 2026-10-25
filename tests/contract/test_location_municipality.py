"""Phase 3-D: municipality by N03 polygons, then the nearest representative point of that municipality.

Synthetic N03 ZIP and 位置参照情報 CSV (fictional names). The real-data test runs only when
HERERISK_ISJ_DATA and HERERISK_N03_DATA point at the official Tokyo ZIPs (kept outside Git).
"""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("shapely")

from hererisk.location.address_provider import HEADER, MlitAddressProvider   # noqa: E402
from hererisk.location.api import PATH, LocationApi                          # noqa: E402
from hererisk.location.n03_municipality import MunicipalityDataError, N03Municipalities   # noqa: E402
from hererisk.location.orchestrator import Orchestrator                      # noqa: E402
from hererisk.location.providers import default_providers                    # noqa: E402


def sq(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


def feature(code, name, polygons):
    return {"type": "Feature", "properties": {"N03_001": "東京都", "N03_002": None, "N03_003": None, "N03_004": name,
                                              "N03_005": None, "N03_007": code},
            "geometry": {"type": "MultiPolygon", "coordinates": polygons}}


FEATURES = [
    # テスト市A: a square with a hole, plus an island (two parts of one municipality)
    feature("13901", "テスト市", [[sq(139.000, 35.000, 139.010, 35.010), sq(139.004, 35.004, 139.006, 35.006)]]),
    feature("13901", "テスト市", [[sq(139.050, 35.050, 139.052, 35.052)]]),
    # テスト町B: shares the edge lon = 139.010 with A
    feature("13902", "テスト町", [[sq(139.010, 35.000, 139.020, 35.010)]]),
    # 所属未定地
    feature("13000", "所属未定地", [[sq(139.030, 35.000, 139.032, 35.002)]]),
]
ROWS = [
    ("13", "東京都", "13901", "テスト市", "139010001001", "本町一丁目", "35.005000", "139.002000", "0", "3"),
    ("13", "東京都", "13901", "テスト市", "139010002000", "島", "35.051000", "139.051000", "0", "1"),
    ("13", "東京都", "13902", "テスト町", "139020001001", "境町一丁目", "35.005000", "139.010500", "0", "3"),
]


@pytest.fixture
def data(tmp_path):
    n03 = tmp_path / "N03-20260101_13_GML.zip"
    with zipfile.ZipFile(n03, "w") as z:
        z.writestr("N03-20260101_13.geojson", json.dumps({"type": "FeatureCollection", "features": FEATURES}))
    isj = tmp_path / "13_2025.csv"
    lines = [",".join(f'"{v}"' for v in HEADER)] + [",".join(f'"{v}"' for v in r) for r in ROWS]
    isj.write_bytes(("\r\n".join(lines) + "\r\n").encode("cp932"))
    return isj, n03


@pytest.fixture
def provider(data):
    isj, n03 = data
    return MlitAddressProvider(isj, N03Municipalities(n03))


def test_polygon_decides_municipality_not_the_nearest_neighbour(provider, data) -> None:
    lat, lon = 35.005, 139.0095            # in A, 45 m from the border; B's point is ~90 m away
    r = provider.lookup(lat, lon)["result"]
    assert r["municipality"] == "テスト市" and r["municipality_code"] == "13901" and r["area"] == "本町一丁目"
    assert r["method"] == "municipality_polygon_and_nearest_point" and r["precision"] == "chome"
    assert r["is_confirmed_address"] is False and r["distance_m"] > 600
    assert MlitAddressProvider(data[0]).lookup(lat, lon)["result"]["municipality"] == "テスト町"   # distance only


def test_municipality_only_when_no_point_within_limit(provider) -> None:
    s = provider.lookup(35.0095, 139.0095)
    r = s["result"]
    assert s["status"] == "available" and r["precision"] == "municipality" and r["area"] is None
    assert r["display_name"] == "東京都テスト市" and r["area_reason"] == "no_representative_point_within_limit"
    assert r["method"] == "municipality_polygon"


def test_island_part_and_hole(provider) -> None:
    assert provider.lookup(35.0511, 139.0511)["result"]["area"] == "島"
    hole = provider.lookup(35.005, 139.005)                       # inside the hole: not テスト市
    assert hole["status"] == "not_available" and hole["reason"] == "out_of_coverage"


def test_boundary_is_ambiguous_and_lists_candidates(provider) -> None:
    s = provider.lookup(35.005, 139.01002)                        # ~2 m from the shared edge
    assert s["status"] == "unknown" and s["result"] is None and s["reason"] == "municipality_boundary_ambiguous"
    assert [c["municipality"] for c in s["candidates"]] == ["テスト市", "テスト町"]
    edge = provider.lookup(35.005, 139.02005)                     # ~5 m outside the outer edge of B
    assert edge["status"] == "unknown" and [c["municipality_code"] for c in edge["candidates"]] == ["13902"]


def test_outside_polygons_never_falls_back_to_distance(provider, data) -> None:
    lat, lon = 35.06, 139.06                                      # ~1.3 km from the island point
    assert MlitAddressProvider(data[0]).lookup(lat, lon)["status"] == "available"   # old behaviour
    s = provider.lookup(lat, lon)
    assert s["status"] == "not_available" and s["result"] is None and s["reason"] == "out_of_coverage"


def test_unassigned_area_returns_prefecture_only(provider) -> None:
    r = provider.lookup(35.001, 139.031)["result"]
    assert r["precision"] == "prefecture" and r["municipality"] is None and r["municipality_code"] == "13000"


def test_api_section_and_sources(provider) -> None:
    providers = default_providers()
    providers["address"] = provider
    doc = LocationApi(Orchestrator(providers, mode="local", allow_synthetic=False)).handle(
        "GET", PATH, "lat=35.005&lon=139.0095").json()
    a = doc["address"]
    assert a["status"] == "available" and a["boundary_source"]["title"] == "国土数値情報（行政区域データ）"
    assert "加工して作成" in a["boundary_source"]["attribution"]["text"]
    assert doc["elevation"]["status"] == "not_available"


def test_bad_n03_file(tmp_path) -> None:
    for name, content in (("a.zip", b"not a zip"),):
        (tmp_path / name).write_bytes(content)
        with pytest.raises(MunicipalityDataError):
            N03Municipalities(tmp_path / name)
    z = tmp_path / "N03-20260101_13_GML.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("N03-20260101_13.geojson", json.dumps({"features": [feature("139", "x", [[sq(0, 0, 1, 1)]])]}))
    with pytest.raises(MunicipalityDataError):
        N03Municipalities(z)


ISJ, N03 = os.environ.get("HERERISK_ISJ_DATA"), os.environ.get("HERERISK_N03_DATA")


@pytest.mark.skipif(not (ISJ and N03), reason="official data paths not set (kept outside Git)")
def test_real_tokyo_data() -> None:
    p = MlitAddressProvider(Path(ISJ), N03Municipalities(Path(N03)))
    assert p.lookup(35.681236, 139.767125)["result"]["display_name"] == "東京都千代田区丸の内一丁目付近"
    assert p.lookup(35.6347, 139.5786)["result"]["municipality"] == "狛江市"
    assert p.lookup(35.5313, 139.6969)["status"] == "not_available"               # Kawasaki (Kanagawa)
    assert p.lookup(35.623307, 139.573312)["status"] == "unknown"                 # Komae / Kawasaki border
    assert p.lookup(33.115, 139.786)["result"]["municipality"] == "八丈町"
