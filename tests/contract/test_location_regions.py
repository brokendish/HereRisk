"""Phase 3-E: several prefectures registered in one address provider (regions file).

Synthetic data for two adjacent prefectures (13 and 14, fictional names). The real-data test runs
only when HERERISK_ADDRESS_REGIONS points at a local regions file (kept outside Git).
"""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("shapely")

from hererisk.location import server as location_server                    # noqa: E402
from hererisk.location.address_provider import HEADER, AddressDataError, MlitAddressProvider   # noqa: E402
from hererisk.location.address_regions import load_regions                  # noqa: E402
from hererisk.location.api import PATH, LocationApi                         # noqa: E402
from hererisk.location.n03_municipality import N03Municipalities            # noqa: E402
from hererisk.location.orchestrator import Orchestrator                     # noqa: E402
from hererisk.location.providers import default_providers                   # noqa: E402


def sq(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


def feature(pref_name, code, name, ring):
    return {"type": "Feature", "properties": {"N03_001": pref_name, "N03_002": None, "N03_003": None,
                                              "N03_004": name, "N03_005": None, "N03_007": code},
            "geometry": {"type": "MultiPolygon", "coordinates": [[ring]]}}


# prefecture 13 (テスト都): lon 139.000-139.010; prefecture 14 (テスト県): lon 139.010-139.030 (two cities)
N03 = {
    "13": [feature("テスト都", "13901", "西市", sq(139.000, 35.000, 139.010, 35.010))],
    "14": [feature("テスト県", "14901", "東市", sq(139.010, 35.000, 139.020, 35.010)),
           feature("テスト県", "14902", "遠町", sq(139.020, 35.000, 139.030, 35.010))],
}
ISJ = {
    "13": [("13", "テスト都", "13901", "西市", "139010001001", "本町一丁目", "35.005000", "139.002000", "0", "3")],
    "14": [("14", "テスト県", "14901", "東市", "149010001001", "境町一丁目", "35.005000", "139.010500", "0", "3"),
           ("14", "テスト県", "14901", "東市", "149010002001", "端町一丁目", "35.009000", "139.019500", "0", "3"),
           ("14", "テスト県", "14902", "遠町", "149020001000", "奥", "35.009000", "139.029000", "0", "1")],
}


def write_isj(path, rows):
    lines = [",".join(f'"{v}"' for v in HEADER)] + [",".join(f'"{v}"' for v in r) for r in rows]
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("cp932"))
    return path


def write_n03(path, pref, features):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"N03-20260101_{pref}.geojson", json.dumps({"type": "FeatureCollection", "features": features}))
    return path


@pytest.fixture
def files(tmp_path):
    out = {}
    for pref in ("13", "14"):
        out[pref] = {"isj": write_isj(tmp_path / f"{pref}_2025.csv", ISJ[pref]),
                     "n03": write_n03(tmp_path / f"N03-20260101_{pref}_GML.zip", pref, N03[pref])}
    return out


def provider(files, order=("13", "14")):
    return MlitAddressProvider([(p, files[p]["isj"]) for p in order],
                               N03Municipalities([(p, files[p]["n03"]) for p in order]))


def regions_file(tmp_path, entries):
    p = tmp_path / "regions.json"
    p.write_text(json.dumps({"regions": entries}, ensure_ascii=False))
    return p


QUERIES = [(35.005, 139.0095), (35.005, 139.012), (35.0095, 139.0195), (35.005, 139.0100), (35.5, 139.5), (35.009, 139.028)]


def test_two_prefectures_and_their_sources(files) -> None:
    p = provider(files)
    west = p.lookup(35.005, 139.0095)                 # in 13, 45 m from the border; 14's point is ~90 m away
    assert west["result"]["display_name"] == "テスト都西市本町一丁目付近"   # never the other prefecture's point
    assert "13_2025.csv" in west["source"]["attribution"]["text"]
    assert "N03-20260101_13" in west["boundary_source"]["attribution"]["text"]
    east = p.lookup(35.005, 139.012)
    assert east["result"]["prefecture"] == "テスト県" and east["result"]["municipality_code"] == "14901"
    assert "14_2025.csv" in east["source"]["attribution"]["text"]


def test_registration_order_does_not_change_results(files) -> None:
    a, b = provider(files, ("13", "14")), provider(files, ("14", "13"))
    for lat, lon in QUERIES:
        assert a.lookup(lat, lon) == b.lookup(lat, lon)


def test_prefecture_border_is_ambiguous(files) -> None:
    s = provider(files).lookup(35.005, 139.01001)
    assert s["status"] == "unknown" and s["result"] is None
    assert [(c["prefecture"], c["municipality_code"]) for c in s["candidates"]] == [("テスト都", "13901"), ("テスト県", "14901")]
    assert len(s["sources"]) == 2 and len(s["boundary_sources"]) == 2


def test_municipality_only_and_unregistered(files) -> None:
    p = provider(files)
    r = p.lookup(35.0005, 139.0205)["result"]          # 遠町, ~1.2 km from its only point (limit ~0.87 km)
    assert r["precision"] == "municipality" and r["display_name"] == "テスト県遠町" and r["area"] is None
    assert p.lookup(35.5, 139.5)["status"] == "not_available"   # no registered polygon
    only13 = MlitAddressProvider([("13", files["13"]["isj"])], N03Municipalities([("13", files["13"]["n03"])]))
    s = only13.lookup(35.005, 139.012)                 # prefecture 14 not registered
    assert s["status"] == "not_available" and s["reason"] == "out_of_coverage"


def test_tokyo_only_regions_file_matches_the_legacy_flags(files, tmp_path) -> None:
    legacy = MlitAddressProvider(files["13"]["isj"], N03Municipalities(files["13"]["n03"]))
    regs = load_regions(regions_file(tmp_path, [{"prefecture_code": "13", "address_isj": "13_2025.csv",
                                                 "address_n03": "N03-20260101_13_GML.zip"}]))   # relative paths
    viafile = MlitAddressProvider([(r["prefecture_code"], r["address_isj"]) for r in regs],
                                  N03Municipalities([(r["prefecture_code"], r["address_n03"]) for r in regs]))
    for lat, lon in QUERIES:
        assert legacy.lookup(lat, lon) == viafile.lookup(lat, lon)


@pytest.mark.parametrize("bad", [
    lambda f: ([("14", f["13"]["isj"]), ("13", f["14"]["isj"])], None),                # files swapped
    lambda f: ([("13", f["13"]["isj"]), ("13", f["13"]["isj"])], None),                # registered twice
    lambda f: ([("13", f["13"]["isj"])], [("14", f["13"]["n03"])]),                    # N03 for another prefecture
    lambda f: ([("13", f["13"]["isj"]), ("14", f["14"]["isj"])], [("13", f["13"]["n03"])]),   # N03 missing for 14
])
def test_inconsistent_registration_is_rejected(files, bad) -> None:
    isj, n03 = bad(files)
    with pytest.raises(AddressDataError):
        MlitAddressProvider(isj, N03Municipalities(n03 or [(p, files[p]["n03"]) for p, _ in isj]))


def test_row_of_another_prefecture_is_rejected(tmp_path) -> None:
    bad = write_isj(tmp_path / "13_2025.csv", [ISJ["14"][0]])
    with pytest.raises(AddressDataError):
        MlitAddressProvider(bad)


@pytest.mark.parametrize("doc", [
    '{"regions": []}', '{"regions": [{"prefecture_code": "13"}]}',
    '{"regions": [{"prefecture_code": "48", "address_isj": "a", "address_n03": "b"}]}',
    '{"regions": [{"prefecture_code": 13, "address_isj": "a", "address_n03": "b"}]}',
    '{"regions": [], "regions": []}', 'not json',
    '{"regions": [{"prefecture_code": "13", "address_isj": "a", "address_n03": "b"},'
    ' {"prefecture_code": "13", "address_isj": "c", "address_n03": "d"}]}',
])
def test_bad_regions_file(tmp_path, doc) -> None:
    p = tmp_path / "regions.json"
    p.write_text(doc)
    with pytest.raises(AddressDataError):
        load_regions(p)


def test_server_refuses_bad_data_and_serves_with_elevation(files, tmp_path, capsys) -> None:
    bad = regions_file(tmp_path, [{"prefecture_code": "14", "address_isj": str(files["13"]["isj"]),
                                   "address_n03": str(files["14"]["n03"])}])
    assert location_server.main(["--address-regions", str(bad), "--port", "0"]) == 3
    assert "registered as 14" in capsys.readouterr().err

    class FixedElevation:
        id = "elevation-api"

        def lookup(self, lat, lon):
            return {"provider": self.id, "synthetic": False, "status": "available",
                    "result": {"elevation_m": 7.0, "unit": "m"}, "source": {"source_id": "x"}}
    providers = default_providers()
    providers["address"] = provider(files)
    providers["elevation"] = FixedElevation()
    doc = LocationApi(Orchestrator(providers, mode="local", allow_synthetic=False)).handle(
        "GET", PATH, "lat=35.005&lon=139.012").json()
    assert doc["address"]["result"]["municipality"] == "東市" and doc["elevation"]["result"]["elevation_m"] == 7.0
    assert set(doc) >= {"schema_version", "mode", "location", "address", "elevation", "hazards"}


REAL = os.environ.get("HERERISK_ADDRESS_REGIONS")


@pytest.mark.skipif(not REAL, reason="HERERISK_ADDRESS_REGIONS not set (official data is kept outside Git)")
def test_real_tokyo_and_kanagawa() -> None:
    regs = load_regions(Path(REAL))
    p = MlitAddressProvider([(r["prefecture_code"], r["address_isj"]) for r in regs],
                            N03Municipalities([(r["prefecture_code"], r["address_n03"]) for r in regs]))
    muni = lambda lat, lon: (p.lookup(lat, lon).get("result") or {}).get("municipality")   # noqa: E731
    assert muni(35.681236, 139.767125) == "千代田区"
    assert muni(35.6347, 139.5786) == "狛江市"
    assert muni(35.5310, 139.6990) == "川崎市川崎区"       # Kawasaki Station east exit
    assert muni(35.4658, 139.6223) == "横浜市西区"         # Yokohama Station
    assert muni(35.5422, 139.4466) == "町田市"
    assert p.lookup(35.623307, 139.573312)["status"] == "unknown"   # Komae / Kawasaki border
    assert p.lookup(34.7025, 135.4959)["status"] == "not_available"  # Osaka
