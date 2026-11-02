"""Phase 4-A: Flood Provider (A31a, local index) on synthetic fixtures.

Synthetic prefectures 13 (lon 139.000-139.010) and 14 (lon 139.010-139.030), lat 35.000-35.010,
and synthetic A31a ZIPs in the official layout (scenario folders, metadata XML, one feature per
line). Nothing here is real data. The real-data check is a manual step (README "洪水").
"""

from __future__ import annotations

import json
import socket
import sqlite3
import zipfile

import pytest

pytest.importorskip("shapely")

from hererisk.data_inventory.inventory import build_inventory         # noqa: E402
from hererisk.flood import a31a                                       # noqa: E402
from hererisk.flood.errors import FloodIndexError                     # noqa: E402
from hererisk.flood.index import build_index, main as flood_cli, trace   # noqa: E402
from hererisk.flood.registry import FloodRegistrationError, load_flood_sources   # noqa: E402
from hererisk.location import server as location_server               # noqa: E402
from hererisk.location.address_provider import HEADER                 # noqa: E402
from hererisk.location.flood_provider import MAX_ITEMS, FloodProvider   # noqa: E402
from hererisk.location.model import check_section                     # noqa: E402

FOLDER = "20_想定最大規模"
_REAL_CONNECT = socket.socket.connect


def sq(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


def poly(*rings):
    return {"type": "Polygon", "coordinates": list(rings)}


def feat(geometry, rank, manager="13", manager_name="テスト都", river=("1300000001", "試験川")):
    return {"type": "Feature", "properties": {"A31a_201": river[0], "A31a_202": river[1], "A31a_203": manager,
                                              "A31a_204": manager_name, "A31a_205": rank}, "geometry": geometry}


def member_text(stem, features):
    head = ('{\n"type": "FeatureCollection",\n' f'"name": "{stem}",\n'
            '"crs": { "type": "name", "properties": { "name": "urn:ogc:def:crs:EPSG::6668" } },\n'
            '"xy_coordinate_resolution": 1e-09,\n"features": [\n')
    body = ",\n".join(json.dumps(f, ensure_ascii=False, separators=(",", ":")) for f in features)
    return head + body + "\n]\n}\n"


def write_a31a(path, dist, products, *, edition="4.3", other_folders=True):
    """products: {river code: [features]} -> official-layout ZIP (scenario folder 20 + a decoy 10)."""
    with zipfile.ZipFile(path, "w") as z:
        for river, features in products.items():
            stem = f"A31a-20-25_{dist}_{river}_10"
            z.writestr(f"{FOLDER}\\{stem}.geojson", member_text(stem, features))
            if other_folders:   # another scenario: must never be read
                s10 = f"A31a-10-25_{dist}_{river}_10"
                z.writestr(f"10_計画規模\\{s10}.geojson", member_text(s10, [feat(poly(sq(139.0, 35.0, 139.01, 35.01)), 6)]))
        xml = f'<?xml version="1.0" encoding="shift_jis"?><MD_Metadata><title>国土数値情報（洪水浸水想定区域）（河川単位）製品仕様書　第{edition}版 （6 データ品質）</title></MD_Metadata>'
        z.writestr(f"メタデータ\\KS-META-A31a-25_{dist}_10.xml", xml.encode("cp932"))
    return path


def write_n03(path, pref, ring, name):
    f = {"type": "Feature", "properties": {"N03_001": name, "N03_002": None, "N03_003": None, "N03_004": "市",
                                           "N03_005": None, "N03_007": f"{pref}901"},
         "geometry": {"type": "MultiPolygon", "coordinates": [[ring]]}}
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(f"N03-20260101_{pref}.geojson", json.dumps({"type": "FeatureCollection", "features": [f]}))
    return path


def write_isj(path, pref, name, lon):
    row = (pref, name, f"{pref}901", "市", f"{pref}9010001001", "本町一丁目", "35.005000", f"{lon:.6f}", "0", "3")
    path.write_bytes(("\r\n".join(",".join(f'"{v}"' for v in r) for r in (HEADER, row)) + "\r\n").encode("cp932"))
    return path


# Source A (東京都管理, distribution 13): rank 2 square and a hole; a feature with a valid island P and
# an invalid bow-tie Q; a MultiPolygon of two overlapping valid squares; a far feature outside the region.
HOLE = poly(sq(139.001, 35.001, 139.004, 35.004), sq(139.002, 35.002, 139.003, 35.003))
BOWTIE = [[139.006, 35.006], [139.008, 35.008], [139.008, 35.006], [139.006, 35.008], [139.006, 35.006]]
A_FEATURES = [
    feat(HOLE, 2),
    feat({"type": "MultiPolygon", "coordinates": [[sq(139.0055, 35.0055, 139.0065, 35.0065)], [BOWTIE]]}, "3"),
    feat({"type": "MultiPolygon", "coordinates": [[sq(139.001, 35.006, 139.003, 35.008)],
                                                  [sq(139.002, 35.007, 139.004, 35.009)]]}, 1),
    feat(poly(sq(140.5, 36.5, 140.6, 36.6)), 4),
]
# Source B (関東地方整備局, distribution 83, integer ranks): rank 4 overlapping A's square; rank 5 in 14
B_FEATURES = [feat(poly(sq(139.0015, 35.0015, 139.0035, 35.0035)), 4, "83", "関東地方整備局", ("8303000001", "国の川")),
              feat(poly(sq(139.012, 35.002, 139.014, 35.004)), 5, "83", "関東地方整備局", ("8303000001", "国の川"))]


def source(sid, org, manager, dist, files, prefs=("13",)):
    return {"source_id": sid, "organization": org, "title": f"洪水浸水想定区域（想定最大規模）{org}（合成）",
            "category": "flood_inundation", "format": "ksj-a31a-geojson", "scenario": "maximum", "data_year": "2025",
            "river_manager_code": manager, "service_region": {"prefecture_codes": list(prefs)},
            "files": [{"path": f, "distribution_code": dist, "ledger_entry": f"ksj-a31a-2025-{dist}-10"} for f in files]}


@pytest.fixture
def data(tmp_path):
    d = tmp_path / "data"
    (d / "a31a").mkdir(parents=True)
    write_n03(d / "N03-20260101_13_GML.zip", "13", sq(139.000, 35.000, 139.010, 35.010), "テスト都")
    write_n03(d / "N03-20260101_14_GML.zip", "14", sq(139.010, 35.000, 139.030, 35.010), "テスト県")
    write_isj(d / "13_2025.csv", "13", "テスト都", 139.005)
    write_isj(d / "14_2025.csv", "14", "テスト県", 139.020)
    write_a31a(d / "a31a" / "A31a-25_13_10_GEOJSON.zip", "13", {"1300000001": A_FEATURES})
    write_a31a(d / "a31a" / "A31a-25_83_10_GEOJSON.zip", "83", {"8303000001": B_FEATURES})
    return d


def write_regions(d, sources, prefs=("13", "14")):
    regions = [{"prefecture_code": p, "address_isj": f"{p}_2025.csv", "address_n03": f"N03-20260101_{p}_GML.zip"}
               for p in prefs]
    p = d / "regions.json"
    p.write_text(json.dumps({"regions": regions, "flood_sources": sources}, ensure_ascii=False), encoding="utf-8")
    return p


def two_sources(d, b_prefs=("13",)):
    return write_regions(d, [source("src-a", "東京都（合成）", "13", "13", ["a31a/A31a-25_13_10_GEOJSON.zip"]),
                             source("src-b", "関東地方整備局（合成）", "83", "83", ["a31a/A31a-25_83_10_GEOJSON.zip"], b_prefs)])


@pytest.fixture
def provider(data, tmp_path):
    regions = two_sources(data)
    build_index(regions, tmp_path / "index.sqlite")
    return FloodProvider(regions, tmp_path / "index.sqlite")


def by_id(section):
    return {s["source_id"]: s for s in section["sources"]}


def checked(section):
    return check_section("hazard", "flood-a31a-local", section, allow_synthetic=False)


# 1. match, depth class kept as in the source ---------------------------------------------------------
def test_match_keeps_source_class(provider) -> None:
    s = checked(provider.lookup(35.0012, 139.0012))           # in A's square, outside the hole, outside B
    assert s["status"] == "available" and len(s["results"]) == 1
    r = s["results"][0]
    assert r["original_class"] == {"code": "2", "label": "0.5～3.0m未満"}
    assert r["depth_class"] == {"scheme_id": "ksj-a31a-water-depth-rank", "scheme_version": "KS-PS-A31a-4.3",
                                "class_code": "2", "label": "0.5～3.0m未満", "lower_m": 0.5, "upper_m": 3.0,
                                "bounds_inclusion": "unspecified", "source_value_type": "integer"}
    assert r["source"]["source_id"] == "src-a" and r["feature_ref"].startswith("loc-zn-")
    assert by_id(s)["src-b"]["zones"] == [] and s["summary"] == {"sources_total": 2, "sources_with_zones": 1,
                                                                 "sources_with_unknown_or_boundary": 0}
    assert s["candidate_completeness"] == "not_guaranteed"


# 2. two official sources at one point: both returned, nothing compared ---------------------------------
def test_two_sources_independent(provider) -> None:
    s = checked(provider.lookup(35.0018, 139.0018))
    assert s["status"] == "available"
    assert sorted((r["source"]["source_id"], r["original_class"]["code"]) for r in s["results"]) == [("src-a", "2"), ("src-b", "4")]
    assert by_id(s)["src-b"]["zones"][0]["depth_class"]["source_value_type"] == "integer"
    text = json.dumps(s)
    for banned in ("representative", "deeper", "max_depth", "overall_status", "assessment_status", "selection"):
        assert banned not in text
    for internal in ("A31a-20-25", ".geojson", ".zip", "feature_index"):
        assert internal not in text                           # no file names / internal keys in the section


# 3. no zone inside the region: no_match with the searched sources, never "safe" -----------------------
def test_no_match_lists_searched_sources(provider) -> None:
    s = checked(provider.lookup(35.0095, 139.0095))
    assert s["status"] == "no_match" and s["results"] == [] and s["searched_sources"] == ["src-a", "src-b"]
    assert all(src["assessed_extent_relation"] == "unknown" for src in s["sources"])
    assert "安全であることを意味しません" in s["notice"] and "浸水しないことを意味しません" in s["scope_notice"]


# 4. holes: inside a hole is not in the zone; the hole's edge is a boundary contact --------------------
def test_hole_and_boundary(provider) -> None:
    assert checked(provider.lookup(35.0025, 139.0025))["status"] == "available"   # B's square still covers it
    assert by_id(provider.lookup(35.0025, 139.0025))["src-a"]["zones"] == []      # A: inside the hole
    s = checked(provider.lookup(35.0039, 139.0039))           # in A's square only, near the corner
    assert s["status"] == "available"
    edge = checked(provider.lookup(35.0045, 139.002))         # outside everything
    assert edge["status"] == "no_match"
    on_edge = provider.lookup(35.004, 139.0037)               # on A's outer edge, outside B
    assert on_edge["status"] == "unknown" and "zone_boundary_contact" in on_edge["reasons"]
    assert by_id(on_edge)["src-a"]["boundary_contacts"] and on_edge["results"] is None


# 5. invalid geometry: unknown, never no_match; a valid island of the same feature still matches -------
def test_invalid_component_is_unknown(provider) -> None:
    s = checked(provider.lookup(35.0075, 139.0072))           # inside the bow-tie's bounding box only
    assert s["status"] == "unknown" and "pending_geometry_zone" in s["reasons"]
    u = by_id(s)["src-a"]["unknowns"]
    assert len(u) == 1 and u[0]["reason"] == "invalid_geometry" and u[0]["unknown_level"] == "L1"
    assert "depth_class" not in u[0]                          # FA-U5: no class for an unknown zone
    both = provider.lookup(35.0062, 139.0062)                 # in island P and in Q's bounding box
    a = by_id(both)["src-a"]
    assert both["status"] == "available" and len(a["zones"]) == 1 and len(a["unknowns"]) == 1
    assert a["zones"][0]["zone_ref"] != a["unknowns"][0]["zone_ref"]


def test_feature_level_invalidity_keeps_both_components_pending(provider) -> None:
    s = provider.lookup(35.0075, 139.0025)                    # inside both overlapping squares
    u = by_id(s)["src-a"]["unknowns"]
    assert s["status"] == "unknown" and [x["reason"] for x in u] == ["feature_invalid_component"] * 2
    assert by_id(s)["src-a"]["zones"] == []
    assert len(by_id(provider.lookup(35.0065, 139.0015))["src-a"]["unknowns"]) == 1   # first square only


# 6. outside / boundary of the service region -----------------------------------------------------------
def test_outside_and_region_boundary(provider) -> None:
    out = checked(provider.lookup(35.005, 139.020))           # prefecture 14: no source serves it
    assert out["status"] == "not_available" and out["reason"] == "outside_service_region" and out["results"] is None
    edge = checked(provider.lookup(35.005, 139.01003))        # ~3 m east of 13's edge
    assert edge["status"] == "unknown" and edge["reasons"] == ["service_region_boundary"]
    assert edge["region_state"] == "region_boundary"
    assert {s["service_region_relation"] for s in edge["sources"]} == {"boundary"}


def test_service_region_is_per_source(data, tmp_path) -> None:
    regions = two_sources(data, b_prefs=("13", "14"))         # B serves 13 and 14: adding a region is a registration
    build_index(regions, tmp_path / "i.sqlite")
    p = FloodProvider(regions, tmp_path / "i.sqlite")
    s = p.lookup(35.003, 139.013)
    assert s["status"] == "available" and s["searched_sources"] == ["src-b"]
    assert s["results"][0]["original_class"] == {"code": "5", "label": "10.0～20.0m未満"}
    assert p.lookup(35.005, 139.01001)["sources"][1]["service_region_relation"] == "inside"   # 13|14 seam is internal


# 7. no partial answers ---------------------------------------------------------------------------------
def test_response_limit_is_an_error(data, tmp_path) -> None:
    many = [feat(poly(sq(139.001, 35.001, 139.009, 35.009)), 1) for _ in range(MAX_ITEMS + 1)]
    write_a31a(data / "a31a" / "A31a-25_13_10_GEOJSON.zip", "13", {"1300000001": many})
    regions = write_regions(data, [source("src-a", "東京都（合成）", "13", "13", ["a31a/A31a-25_13_10_GEOJSON.zip"])])
    build_index(regions, tmp_path / "i.sqlite")
    s = checked(FloodProvider(regions, tmp_path / "i.sqlite").lookup(35.005, 139.005))
    assert s["status"] == "error" and s["error"]["code"] == "flood_response_limit_exceeded"


# 8. the index records every feature; far features are counted, not silently lost ----------------------
def test_index_counts_and_trace(data, tmp_path) -> None:
    summary = build_index(two_sources(data), tmp_path / "i.sqlite")
    a = summary["sources"][0]
    assert (a["features_total"], a["features_kept"], a["pending_total"]) == (4, 3, 3)
    db = sqlite3.connect(tmp_path / "i.sqlite")
    counts = json.loads(db.execute("SELECT counts FROM products WHERE source_id='src-a'").fetchone()[0])
    assert counts["invalid_geometry_total"] == 1 and counts["feature_invalid_component_total"] == 2
    ref = db.execute("SELECT zone_ref FROM components WHERE reason='invalid_geometry'").fetchone()[0]
    t = trace(tmp_path / "i.sqlite", ref)
    assert t["zip_member"] == f"{FOLDER}/A31a-20-25_13_1300000001_10.geojson" and t["feature_index"] == 1
    assert t["polygon_index"] == 1 and t["depth_class"]["class_code"] == "3" and t["pending_reason"] == "invalid_geometry"
    assert db.execute("SELECT count(*) FROM components WHERE minx > 140").fetchone()[0] == 0


# 9. the source is read as it is, or not at all ---------------------------------------------------------
@pytest.mark.parametrize("bad", ["rank", "manager", "keys", "edition", "category"])
def test_build_refuses_unexpected_source_data(data, tmp_path, bad) -> None:
    f = data / "a31a" / "A31a-25_13_10_GEOJSON.zip"
    features = [feat(poly(sq(139.001, 35.001, 139.002, 35.002)), 1)]
    if bad == "rank":
        features = [feat(poly(sq(139.001, 35.001, 139.002, 35.002)), 7)]
    if bad == "manager":
        features = [feat(poly(sq(139.001, 35.001, 139.002, 35.002)), 1, manager="83")]
    if bad == "keys":
        features[0]["properties"]["extra"] = 1
    write_a31a(f, "13", {"1300000001": features}, edition="9.9" if bad == "edition" else "4.3")
    if bad == "category":
        with zipfile.ZipFile(f, "a") as z:
            z.writestr(f"{FOLDER}\\A31a-30-25_13_1300000002_10.geojson", member_text("x", []))
    regions = write_regions(data, [source("src-a", "東京都（合成）", "13", "13", ["a31a/A31a-25_13_10_GEOJSON.zip"])])
    with pytest.raises((a31a.A31aFormatError, FloodIndexError)):
        build_index(regions, tmp_path / "i.sqlite")
    assert not (tmp_path / "i.sqlite").exists() and not list(tmp_path.glob("i.sqlite.tmp-*"))
    assert flood_cli(["build", "--regions", str(regions), "--output", str(tmp_path / "i.sqlite")]) == 3


def test_registration_rules(data) -> None:
    ok = source("src-a", "東京都（合成）", "13", "13", ["a31a/A31a-25_13_10_GEOJSON.zip"])
    for broken in ({**ok, "service_region": {"prefecture_codes": ["11"]}},      # no N03 for 11
                   {**ok, "files": [{**ok["files"][0], "distribution_code": "14"}]},   # name says 13
                   {**ok, "scenario": "planned"}, {**ok, "source_id": "A"}, {k: v for k, v in ok.items() if k != "title"}):
        with pytest.raises(FloodRegistrationError):
            load_flood_sources(write_regions(data, [broken]))
    with pytest.raises(FloodRegistrationError):
        load_flood_sources(write_regions(data, [ok, ok]))
    assert load_flood_sources(write_regions(data, [ok]))[0]["service_prefectures"] == ["13"]


# 10. the provider starts only on the index of this registration and these files ------------------------
def test_index_must_match_registration_and_files(data, tmp_path) -> None:
    regions = two_sources(data)
    build_index(regions, tmp_path / "i.sqlite")
    write_regions(data, [source("src-a", "東京都（合成）", "13", "13", ["a31a/A31a-25_13_10_GEOJSON.zip"])])
    with pytest.raises(FloodIndexError):
        FloodProvider(regions, tmp_path / "i.sqlite")
    regions = two_sources(data)
    write_a31a(data / "a31a" / "A31a-25_83_10_GEOJSON.zip", "83", {"8303000001": B_FEATURES[:1]})
    with pytest.raises(FloodIndexError):
        FloodProvider(regions, tmp_path / "i.sqlite")


# 11. Location API and Data Inventory -------------------------------------------------------------------
def test_location_api_serves_flood_with_address(data, tmp_path, monkeypatch) -> None:
    import threading
    monkeypatch.setattr(socket.socket, "connect", lambda self, a: _REAL_CONNECT(self, a) if a[0] == "127.0.0.1"
                        else (_ for _ in ()).throw(AssertionError("only loopback")))
    regions = two_sources(data)
    build_index(regions, tmp_path / "i.sqlite")
    httpd = location_server.build_server("127.0.0.1", 0, address_regions=regions, flood_index=tmp_path / "i.sqlite")
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        with socket.socket() as sock:
            sock.settimeout(5)
            sock.connect(("127.0.0.1", httpd.server_address[1]))
            sock.sendall(b"GET /api/v1/location?lat=35.0018&lon=139.0018 HTTP/1.1\r\nHost: x\r\n\r\n")
            data_ = b""
            while chunk := sock.recv(65536):
                data_ += chunk
        body = json.loads(data_.partition(b"\r\n\r\n")[2])
    finally:
        httpd.shutdown()
        httpd.server_close()
    assert body["mode"] == "local"
    assert body["address"]["status"] == "available"                      # the address section is unchanged
    flood = body["hazards"]["flood"]
    assert flood["status"] == "available" and flood["synthetic"] is False and len(flood["results"]) == 2
    assert body["hazards"]["tsunami"]["status"] == "not_available"
    with pytest.raises(ValueError):
        location_server.build_server("127.0.0.1", 0, flood_index=tmp_path / "i.sqlite")   # needs the regions file
    assert location_server.main(["--address-regions", str(regions), "--flood-index", str(tmp_path / "nope")]) == 3


def test_inventory_lists_registered_flood_files(data) -> None:
    inv = build_inventory(two_sources(data))
    flood = [i for i in inv["items"] if i["category"] == "flood_inundation"]
    assert [i["data_id"] for i in flood] == ["flood-src-a-1", "flood-src-b-1"]
    b = flood[1]
    assert (b["prefecture_name"], b["organization"], b["year"], b["file"]["state"]) == ("東京都", "関東地方整備局（合成）", "2025", "present")
    assert b["api_connection"]["configured"] is True and b["public_approval"] == "unconfirmed"
    assert b["version"]["distribution_code"] == "83" and b["prefecture_code_matches_file"] is None
    assert len([i for i in inv["items"] if i["category"] != "flood_inundation"]) == 4   # address + N03 kept
