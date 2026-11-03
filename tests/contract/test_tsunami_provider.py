"""Phase 4-M: Tsunami Provider (A40, local index) on the shared Polygon Engine, synthetic fixtures.

Synthetic prefecture 13 (lon 139.000-139.010, lat 35.000-35.010, see test_flood_provider) and synthetic
A40 ZIPs in the official layout (one folder: GeoJSON with every feature on one line, GML with "lat lon"
8-decimal positions, Shift-JIS metadata). Nothing here is real data. The real-data checks are manual
(README "津波").
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

pytest.importorskip("shapely")

from hererisk.common.polygon import relation                          # noqa: E402
from hererisk.flood.index import build_index as build_flood_index      # noqa: E402
from hererisk.location import server as location_server               # noqa: E402
from hererisk.location.model import check_section                     # noqa: E402
from hererisk.location.tsunami_provider import MAX_ITEMS, TsunamiProvider   # noqa: E402
from hererisk.tsunami import a40                                      # noqa: E402
from hererisk.tsunami.errors import A40FormatError, TsunamiIndexError, TsunamiRegistrationError   # noqa: E402
from hererisk.tsunami.index import build_index, main as tsunami_cli, trace, zone_ref   # noqa: E402
from hererisk.tsunami.registry import load_tsunami_sources            # noqa: E402
from hererisk.tsunami.verify import run as verify_run                 # noqa: E402
from test_flood_provider import data, source as flood_source, sq      # noqa: E402,F401

REPO = Path(__file__).resolve().parents[2]
L1, L2, L3, L4 = "～0.3m未満", "1m以上 ～ 3m未満", "3m以上 ～ 5m未満", "20m以上"
SELF_TOUCH = [[139.006, 35.006], [139.007, 35.006], [139.0067, 35.0065], [139.0073, 35.0065], [139.007, 35.006],
              [139.008, 35.006], [139.008, 35.008], [139.006, 35.008], [139.006, 35.006]]
B1 = [[139.0060, 35.0010], [139.0070, 35.0010], [139.0070, 35.0020], [139.0060, 35.0020], [139.0060, 35.0010],
      [139.0060, 35.0020], [139.0070, 35.0020], [139.0070, 35.0010], [139.0060, 35.0010], [139.0050, 35.0010],
      [139.0060, 35.0000], [139.0060, 35.0010]]
FEATURES = [   # (geometry, A40_003)
    ({"type": "Polygon", "coordinates": [sq(139.001, 35.001, 139.004, 35.004), sq(139.002, 35.002, 139.003, 35.003)]}, L1),
    ({"type": "Polygon", "coordinates": [sq(139.0035, 35.0035, 139.0045, 35.0045)]}, L2),      # overlaps the first
    ({"type": "Polygon", "coordinates": [SELF_TOUCH]}, L3),                                   # invalid (self-touch)
    ({"type": "Polygon", "coordinates": [B1]}, L4),                                           # invalid (Codex B1)
    ({"type": "Polygon", "coordinates": [sq(139.004, 35.001, 139.005, 35.002)]}, L3),          # shares an edge with the first
    ({"type": "MultiPolygon", "coordinates": [[sq(139.001, 35.008, 139.002, 35.009)], [sq(139.002, 35.008, 139.003, 35.009)]]}, L2),
    ({"type": "Polygon", "coordinates": [sq(139.0066, 35.0066, 139.0068, 35.0068)]}, L1),      # valid, inside the self-touch box
]


def geojson_text(features, pref="13", crs="EPSG:6668"):
    feats = [{"type": "Feature", "id": i, "geometry": g,
              "properties": {"FID": i, "A40_001": "テスト都", "A40_002": pref, "A40_003": label}}
             for i, (g, label) in enumerate(features)]
    head = '{\n  "type" : "FeatureCollection",\n  "crs" : {\n    "type" : "name",\n    "properties" : {\n' \
           f'      "name" : "{crs}"\n    }}\n  }},\n  "features" : '
    return head + json.dumps(feats, separators=(",", ":")) + "\n}\n"


def gml_text(features):
    out = ['<?xml version="1.0" encoding="UTF-8"?>\n<ksj:Dataset gml:id="A40Dataset" '
           'xmlns:ksj="http://nlftp.mlit.go.jp/ksj/schemas/ksj-app" xmlns:gml="http://schemas.opengis.net/gml/3.2.1" '
           'xmlns:xlink="http://www.w3.org/1999/xlink">']
    for i, (g, label) in enumerate(features):
        comps = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        patches = []
        for c, rings in enumerate(comps):
            refs = []
            for k, r in enumerate(rings):
                cid = f"cv{i}_{c}_{k}"
                pos = "\n".join(f"{y:.8f} {x:.8f}" for x, y in r)
                out.append(f'<gml:Curve gml:id="{cid}"><gml:segments><gml:LineStringSegment><gml:posList>{pos}'
                           '</gml:posList></gml:LineStringSegment></gml:segments></gml:Curve>')
                if k:   # holes through an OrientableCurve, as in the real file
                    out.append(f'<gml:OrientableCurve gml:id="_{cid}" orientation=" + "><gml:baseCurve xlink:href="#{cid}"/>'
                               '</gml:OrientableCurve>')
                    cid = "_" + cid
                refs.append(cid)
            inner = "".join(f'<gml:interior><gml:Ring><gml:curveMember xlink:href="#{r}"/></gml:Ring></gml:interior>'
                            for r in refs[1:])
            patches.append(f'<gml:PolygonPatch><gml:exterior><gml:Ring><gml:curveMember xlink:href="#{refs[0]}"/>'
                           f'</gml:Ring></gml:exterior>{inner}</gml:PolygonPatch>')
        out.append(f'<gml:Surface gml:id="sf{i}"><gml:patches>{"".join(patches)}</gml:patches></gml:Surface>')
    for i, (g, label) in enumerate(features):
        out.append(f'<ksj:ExpectedTsunamiInundatedArea gml:id="id{i}"><ksj:bounds xlink:href="#sf{i}"/>'
                   f'<ksj:prefectureName>テスト都</ksj:prefectureName><ksj:prefectureCode>13</ksj:prefectureCode>'
                   f'<ksj:classificationOfWaterDepth>{label}</ksj:classificationOfWaterDepth></ksj:ExpectedTsunamiInundatedArea>')
    out.append("</ksj:Dataset>\n")
    return "\n".join(out)


def write_a40(path, features=FEATURES, *, yy="23", pref="13", edition="2.2", geojson=None, gml=None):
    folder = f"A40-{yy}_{pref}_GML/"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(folder, "")
        z.writestr(f"{folder}A40-{yy}_{pref}.geojson", geojson if geojson is not None else geojson_text(features, pref))
        z.writestr(f"{folder}A40-{yy}_{pref}.xml", gml if gml is not None else gml_text(features))
        xml = (f'<?xml version="1.0" encoding="shift_jis"?><MD_Metadata><title>国土数値情報　津波浸水想定　テスト　A40-{yy}_{pref}'
               f'</title><specification><title>国土数値情報（津波浸水想定）製品仕様書　第{edition}版</title></specification></MD_Metadata>')
        z.writestr(f"{folder}KS-META-A40-{yy}_{pref}.xml", xml.encode("cp932"))
    return path


def t_source(sid="local-a40-2023-13", path="a40/A40-23_13_GML.zip", prefs=("13",)):
    return {"source_id": sid, "organization": "テスト都（合成）", "title": "津波浸水想定（合成）", "format": "ksj-a40-geojson",
            "data_year": "2023", "prefecture_code": "13", "service_region": {"prefecture_codes": list(prefs)},
            "files": [{"path": path, "ledger_entry": "ksj-a40-2024-13"}]}


def regions_file(d, tsunami=None, flood=None, prefs=("13", "14")):
    doc = {"regions": [{"prefecture_code": p, "address_isj": f"{p}_2025.csv", "address_n03": f"N03-20260101_{p}_GML.zip"}
                       for p in prefs]}
    if tsunami is not None:
        doc["tsunami_sources"] = tsunami
    if flood is not None:
        doc["flood_sources"] = flood
    p = d / "regions.json"
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return p


@pytest.fixture
def tdata(data):
    (data / "a40").mkdir()
    write_a40(data / "a40" / "A40-23_13_GML.zip")
    return data


@pytest.fixture
def built(tdata, tmp_path):
    regions = regions_file(tdata, [t_source()])
    build_index(regions, tmp_path / "t.sqlite")
    return regions, tmp_path / "t.sqlite"


@pytest.fixture
def provider(built):
    return TsunamiProvider(*built)


def by_id(section):
    return {s["source_id"]: s for s in section["sources"]}


def checked(section):
    return check_section("hazard", "tsunami-a40-local", section, allow_synthetic=False)


# 1. reading A40 -----------------------------------------------------------------------------------------
def test_reader_keeps_the_source_text_and_the_layout(tdata) -> None:
    z, m = a40.open_zip(tdata / "a40" / "A40-23_13_GML.zip")
    with z:
        assert a40.spec_edition(z, m) == "2.2"
        feats = list(a40.read_features(z, m, "13"))
    assert [f["depth_label"] for f in feats] == [label for _, label in FEATURES]          # byte for byte
    assert feats[0]["depth_label"] == "～0.3m未満" and "～" in feats[1]["depth_label"]   # fullwidth tilde kept
    assert [f["fid"] for f in feats] == list(range(len(FEATURES)))
    assert [len(f["polygons"]) for f in feats] == [1, 1, 1, 1, 1, 2, 1]


@pytest.mark.parametrize("bad", ["crs", "extra_property", "missing_property", "fid", "pref", "label_empty", "label_number",
                                 "nan", "unclosed", "point", "edition", "member", "duplicate_key"])
def test_reader_and_build_stop_on_unexpected_data(tdata, tmp_path, bad) -> None:
    f = tdata / "a40" / "A40-23_13_GML.zip"
    text = geojson_text(FEATURES)
    doc = json.loads(text)
    feat0 = doc["features"][0]
    if bad == "crs":
        text = geojson_text(FEATURES, crs="EPSG:4326")
    elif bad in ("extra_property", "missing_property", "fid", "pref", "label_empty", "label_number", "unclosed", "point"):
        {"extra_property": lambda: feat0["properties"].update(extra=1),
         "missing_property": lambda: feat0["properties"].pop("A40_001"),
         "fid": lambda: feat0["properties"].update(FID=5),
         "pref": lambda: feat0["properties"].update(A40_002="14"),
         "label_empty": lambda: feat0["properties"].update(A40_003=""),
         "label_number": lambda: feat0["properties"].update(A40_003=3),
         "unclosed": lambda: feat0["geometry"]["coordinates"][0].pop(),
         "point": lambda: feat0.update(geometry={"type": "Point", "coordinates": [139.0, 35.0]})}[bad]()
        text = json.dumps(doc)
    elif bad == "nan":
        text = text.replace("139.001,", "NaN,", 1)
    elif bad == "duplicate_key":
        text = text.replace('"FID":0,', '"FID":0,"FID":0,', 1)
    if bad == "edition":
        write_a40(f, edition="9.9")
    elif bad == "member":
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("A40-23_13_GML/A40-23_13.geojson", text)
    else:
        write_a40(f, geojson=text)
    regions = regions_file(tdata, [t_source()])
    with pytest.raises((A40FormatError, TsunamiIndexError)):
        build_index(regions, tmp_path / "t.sqlite")
    assert not (tmp_path / "t.sqlite").exists() and not list(tmp_path.glob("t.sqlite.tmp-*"))
    assert tsunami_cli(["build", "--regions", str(regions), "--output", str(tmp_path / "t.sqlite")]) == 3


def test_registration_rules(tdata) -> None:
    ok = t_source()
    for broken in ({**ok, "service_region": {"prefecture_codes": ["11"]}}, {**ok, "prefecture_code": "14"},
                   {**ok, "data_year": "2024"}, {**ok, "format": "ksj-a31a-geojson"}, {**ok, "source_id": "A"},
                   {k: v for k, v in ok.items() if k != "title"}, {**ok, "files": [{"path": "a40/x.zip", "ledger_entry": "e"}]}):
        with pytest.raises(TsunamiRegistrationError):
            load_tsunami_sources(regions_file(tdata, [broken]))
    with pytest.raises(TsunamiRegistrationError):
        load_tsunami_sources(regions_file(tdata, [ok, ok]))
    assert load_tsunami_sources(regions_file(tdata, [ok]))[0]["service_prefectures"] == ["13"]
    assert load_tsunami_sources(regions_file(tdata, None)) == []


# 2. index -----------------------------------------------------------------------------------------------
def test_index_keeps_every_feature_and_classifies_with_the_shared_engine(built) -> None:
    regions, index = built
    db = sqlite3.connect(index)
    rows = db.execute("SELECT feature_index, polygon_index, validity, kind, depth_label, zone_ref, wkb FROM components "
                      "ORDER BY rowid").fetchall()
    meta = {k: json.loads(v) for k, v in db.execute("SELECT key, value FROM meta")}
    db.close()
    assert [(r[0], r[1], r[2]) for r in rows] == [
        (0, 0, "valid"), (1, 0, "valid"), (2, 0, "invalid_geometry"), (3, 0, "invalid_geometry"), (4, 0, "valid"),
        (5, 0, "feature_invalid_component"), (5, 1, "feature_invalid_component"), (6, 0, "valid")]
    assert rows[2][3] == "ring_self_intersection" and rows[5][3] == "shared_edge"
    assert [r[4] for r in rows] == [L1, L2, L3, L4, L3, L2, L2, L1]
    assert len({r[5] for r in rows}) == len(rows) and all(r[5].startswith("loc-tz-") for r in rows)
    import shapely
    assert shapely.from_wkb(rows[0][6]).equals_exact(shapely.Polygon(FEATURES[0][0]["coordinates"][0],
                                                                     FEATURES[0][0]["coordinates"][1:]), 0)   # not repaired
    assert meta["status"] == "complete" and meta["index_format"] == "hererisk-tsunami-index-v0.1"
    s = meta["summary"]["sources"][0]
    assert (s["features"], s["components"], s["holes"]) == (7, 8, 1)
    assert s["not_valid_by_depth_label"] == {L3: 1, L4: 1, L2: 2}
    f = meta["files"]["A40-23_13_GML.zip"]
    assert f["spec_edition"] == "2.2" and f["ledger_sha256_match"] is False       # a synthetic file, not the ledger's
    t = trace(index, rows[2][5])
    assert t["feature_index"] == 2 and t["member"] == "A40-23_13_GML/A40-23_13.geojson" and t["depth_label"] == L3


def test_zone_refs_differ_by_file_feature_and_component() -> None:
    refs = {zone_ref(sha, m, fi, pi) for sha in ("a" * 64, "b" * 64) for m in ("x.geojson", "y.geojson")
            for fi in (0, 1) for pi in (0, 1)}
    assert len(refs) == 16


# 3. provider --------------------------------------------------------------------------------------------
def test_inside_returns_the_source_class_unchanged(provider) -> None:
    s = checked(provider.lookup(35.0012, 139.0012))
    assert s["status"] == "available" and len(s["results"]) == 1
    r = s["results"][0]
    assert r["original_class"] == {"code": None, "label": L1} and r["source_attribute"] == "A40_003"
    assert r["source"]["source_id"] == "local-a40-2023-13" and r["feature_ref"].startswith("loc-tz-")
    assert s["source_caution"] == "実際の津波はこの津波浸水想定よりも大きい場合があります。"
    src = by_id(s)["local-a40-2023-13"]
    assert src["data_use"] == {"scope": "local_verification_only", "usage_terms": "review_required",
                               "public_approval": "unconfirmed"}
    assert src["assessed_extent_relation"] == "unknown" and src["spec_edition"] == "2.2"
    for banned in ("representative", "max_depth", "deeper", "safe", "risk_score", "not_affected", "depth_m"):
        assert banned not in json.dumps(s)


def test_overlapping_zones_are_listed_separately(provider) -> None:
    s = checked(provider.lookup(35.0038, 139.0038))          # in the first square and the overlapping one
    assert s["status"] == "available"
    assert sorted(r["original_class"]["label"] for r in s["results"]) == sorted([L1, L2])
    assert len({r["feature_ref"] for r in s["results"]}) == 2


def test_hole_edge_and_shared_edge(provider) -> None:
    hole = checked(provider.lookup(35.0025, 139.0025))
    assert hole["status"] == "no_match" and hole["results"] == [] and hole["searched_sources"] == ["local-a40-2023-13"]
    assert "津波の影響がないことを意味しません" in hole["scope_notice"] and "大きい場合があります" in hole["scope_notice"]
    assert "安全であることを意味しません" in hole["notice"]
    on_hole_edge = checked(provider.lookup(35.0025, 139.002))
    assert on_hole_edge["status"] == "unknown" and on_hole_edge["reasons"] == ["zone_boundary_contact"]
    shared = checked(provider.lookup(35.0015, 139.004))       # the shared edge of two zones: two contacts, no zone
    src = by_id(shared)["local-a40-2023-13"]
    assert shared["status"] == "unknown" and len(src["boundary_contacts"]) == 2 and src["zones"] == []
    assert {z["original_class"]["label"] for z in src["boundary_contacts"]} == {L1, L3}
    vertex = checked(provider.lookup(35.001, 139.001))
    assert vertex["status"] == "unknown" and len(by_id(vertex)["local-a40-2023-13"]["boundary_contacts"]) == 1


def test_invalid_polygon_is_pending_never_no_match(provider) -> None:
    s = checked(provider.lookup(35.0075, 139.0072))           # in the self-touch box only
    assert s["status"] == "unknown" and s["reasons"] == ["pending_geometry_zone"] and s["results"] is None
    u = by_id(s)["local-a40-2023-13"]["unknowns"]
    assert [(x["reason"], x["invalid_kind"], x["unknown_level"]) for x in u] == [("invalid_geometry", "ring_self_intersection", "L1")]
    assert "original_class" not in u[0]                       # no depth class for a pending zone
    corner = checked(provider.lookup(35.008, 139.008))        # the box corner (boundary included)
    assert corner["status"] == "unknown" and len(by_id(corner)["local-a40-2023-13"]["unknowns"]) == 1
    both = checked(provider.lookup(35.0067, 139.0067))         # a valid zone inside the invalid one's box
    src = by_id(both)["local-a40-2023-13"]
    assert both["status"] == "available" and len(src["zones"]) == 1 and len(src["unknowns"]) == 1
    fic = checked(provider.lookup(35.0085, 139.0015))          # a component of a feature with a shared edge
    assert [x["reason"] for x in by_id(fic)["local-a40-2023-13"]["unknowns"]] == ["feature_invalid_component"]


def test_codex_b1_stays_pending(provider) -> None:
    import shapely
    from shapely.geometry import Point, Polygon
    x, y = 139.0065, 35.0015                                   # inside B1's doubled square
    assert shapely.make_valid(Polygon(B1), method="linework").contains(Point(x, y)) and not Polygon(B1).contains(Point(x, y))
    s = checked(provider.lookup(y, x))
    assert s["status"] == "unknown" and s["reasons"] == ["pending_geometry_zone"]
    assert by_id(s)["local-a40-2023-13"]["unknowns"][0]["reason"] == "invalid_geometry"


def test_outside_and_region_boundary(provider) -> None:
    out = checked(provider.lookup(35.005, 139.020))           # prefecture 14: not registered for tsunami
    assert out["status"] == "not_available" and out["reason"] == "outside_service_region" and out["results"] is None
    edge = checked(provider.lookup(35.005, 139.01003))
    assert edge["status"] == "unknown" and edge["reasons"] == ["service_region_boundary"]


def test_provider_equals_the_shared_engine(built, provider) -> None:
    db = sqlite3.connect(built[1])
    idx = relation.ComponentIndex(relation.Candidate(sid, ref, wkb, v) for sid, ref, v, wkb in
                                  db.execute("SELECT source_id, zone_ref, validity, wkb FROM components ORDER BY rowid"))
    db.close()
    for i in range(0, 51):
        for j in range(0, 51):
            lon, lat = round(139.0 + i * 0.0002, 7), round(35.0 + j * 0.0002, 7)
            s = provider.lookup(lat, lon)
            want = {(f["feature_ref"], f["evaluation"], f["relation"]) for f in idx.search(lon, lat)["features"]}
            got = {(z["zone_ref"], "evaluated", "inside") for src in s["sources"] for z in src["zones"]} | \
                  {(z["zone_ref"], "evaluated", "on_boundary") for src in s["sources"] for z in src["boundary_contacts"]} | \
                  {(z["zone_ref"], "pending_geometry", None) for src in s["sources"] for z in src["unknowns"]}
            assert got == want, (lon, lat)


def test_two_sources_independent(tdata, tmp_path) -> None:
    write_a40(tdata / "a40" / "A40-24_13_GML.zip", FEATURES[:2], yy="24")
    second = {**t_source("local-a40-2024-13", "a40/A40-24_13_GML.zip"), "data_year": "2024"}
    regions = regions_file(tdata, [t_source(), second])
    build_index(regions, tmp_path / "t2.sqlite")
    s = checked(TsunamiProvider(regions, tmp_path / "t2.sqlite").lookup(35.0012, 139.0012))
    assert s["status"] == "available" and s["searched_sources"] == ["local-a40-2023-13", "local-a40-2024-13"]
    assert [(r["source"]["source_id"], r["original_class"]["label"]) for r in s["results"]] == \
        [("local-a40-2023-13", L1), ("local-a40-2024-13", L1)]
    assert s["results"][0]["feature_ref"] != s["results"][1]["feature_ref"]


def test_limit_and_failure_are_never_partial(tdata, tmp_path, provider, monkeypatch) -> None:
    many = [({"type": "Polygon", "coordinates": [sq(139.001, 35.001, 139.009, 35.009)]}, L1)] * (MAX_ITEMS + 1)
    write_a40(tdata / "a40" / "A40-23_13_GML.zip", many)
    regions = regions_file(tdata, [t_source()])
    build_index(regions, tmp_path / "many.sqlite")
    s = checked(TsunamiProvider(regions, tmp_path / "many.sqlite").lookup(35.005, 139.005))
    assert s["status"] == "error" and s["error"]["code"] == "tsunami_response_limit_exceeded"
    monkeypatch.setattr(provider._index, "_search", lambda x, y: 1 / 0)
    with pytest.raises(TsunamiIndexError):
        provider.lookup(35.0012, 139.0012)                    # -> provider_failed in the orchestrator, never no_match


def test_start_only_on_the_index_of_this_registration_and_file(tdata, built, tmp_path) -> None:
    regions, index = built
    write_a40(tdata / "a40" / "A40-23_13_GML.zip", FEATURES[:3])
    with pytest.raises(TsunamiIndexError):
        TsunamiProvider(regions, index)                       # the ZIP changed
    write_a40(tdata / "a40" / "A40-23_13_GML.zip")
    TsunamiProvider(regions, index)
    other = regions_file(tdata, [{**t_source(), "organization": "別"}])
    with pytest.raises(TsunamiIndexError):
        TsunamiProvider(other, index)                         # another registration
    regions_file(tdata, [t_source()])
    db = sqlite3.connect(index)
    db.execute("UPDATE meta SET value = '\"building\"' WHERE key = 'status'")
    db.commit()
    db.close()
    with pytest.raises(TsunamiIndexError, match="incomplete"):
        TsunamiProvider(regions, index)
    (tmp_path / "junk.sqlite").write_bytes(b"junk" * 100)
    with pytest.raises(TsunamiIndexError):
        TsunamiProvider(regions, tmp_path / "junk.sqlite")


# 4. Location API ----------------------------------------------------------------------------------------
def get(srv, lat, lon):
    return srv.location_api.handle("GET", "/api/v1/location", f"lat={lat}&lon={lon}").json()


def test_location_api_tsunami_is_off_by_default_and_on_only_when_asked(tdata, tmp_path) -> None:
    flood = [flood_source("src-a", "東京都（合成）", "13", "13", ["a31a/A31a-25_13_10_GEOJSON.zip"])]
    regions = regions_file(tdata, [t_source()], flood)
    build_flood_index(regions, tmp_path / "f.sqlite")
    build_index(regions, tmp_path / "t.sqlite")
    off = location_server.build_server("127.0.0.1", 0, address_regions=regions, flood_index=tmp_path / "f.sqlite")
    on = location_server.build_server("127.0.0.1", 0, address_regions=regions, flood_index=tmp_path / "f.sqlite",
                                      tsunami_index=tmp_path / "t.sqlite")
    try:
        a, b = get(off, 35.0012, 139.0012), get(on, 35.0012, 139.0012)
        assert a["hazards"]["tsunami"]["status"] == "not_available" and "provider" in a["hazards"]["tsunami"]
        assert b["hazards"]["tsunami"]["status"] == "available"
        assert b["hazards"]["tsunami"]["results"][0]["original_class"]["label"] == L1
        for k in ("address", "elevation"):
            assert a[k] == b[k]
        assert a["hazards"]["flood"] == b["hazards"]["flood"]               # the flood section does not change
        for h in ("storm_surge", "landslide"):
            assert b["hazards"][h]["status"] == "not_available"
    finally:
        off.server_close()
        on.server_close()
    with pytest.raises(ValueError):
        location_server.build_server("127.0.0.1", 0, tsunami_index=tmp_path / "t.sqlite")   # needs the regions file
    with pytest.raises(ValueError):
        location_server.build_server("0.0.0.0", 0, address_regions=regions, tsunami_index=tmp_path / "t.sqlite")
    assert location_server.main(["--address-regions", str(regions), "--tsunami-index", str(tmp_path / "nope")]) == 3


def test_a_tsunami_failure_stays_in_its_section(tdata, tmp_path, monkeypatch) -> None:
    flood = [flood_source("src-a", "東京都（合成）", "13", "13", ["a31a/A31a-25_13_10_GEOJSON.zip"])]
    regions = regions_file(tdata, [t_source()], flood)
    build_flood_index(regions, tmp_path / "f.sqlite")
    build_index(regions, tmp_path / "t.sqlite")
    srv = location_server.build_server("127.0.0.1", 0, address_regions=regions, flood_index=tmp_path / "f.sqlite",
                                       tsunami_index=tmp_path / "t.sqlite")
    try:
        before = get(srv, 35.0012, 139.0012)
        monkeypatch.setattr(TsunamiProvider, "lookup", lambda self, lat, lon: (_ for _ in ()).throw(RuntimeError("x /secret")))
        after = get(srv, 35.0012, 139.0012)
    finally:
        srv.server_close()
    assert after["hazards"]["tsunami"]["status"] == "error" and after["hazards"]["tsunami"]["error"]["code"] == "provider_failed"
    assert "secret" not in json.dumps(after)
    for k in ("address", "elevation"):
        assert after[k] == before[k]
    assert after["hazards"]["flood"] == before["hazards"]["flood"]


# 5. independent check (GML, no shared engine) ------------------------------------------------------------
def test_independent_check_passes_on_the_fixture(built) -> None:
    out = verify_run(*built, sample=50)
    assert out["failed"] == [], out["checks"]
    c = out["checks"]
    assert c["geometry_round8_equal"] == 8 and c["attributes_equal"] == 7 and c["validity_equals_independent"] == 8
    assert c["defect:ring_self_touch"] >= 1 and c["defect:ring_self_overlap"] >= 1          # self-touch, B1
    assert c["expect_inside"] and c["expect_outside"] and c["expect_pending_in_bbox"]


@pytest.mark.parametrize("tamper", ["label", "coordinate", "count"])
def test_independent_check_finds_differences(tdata, tmp_path, tamper) -> None:
    gml_features = list(FEATURES)
    if tamper == "label":
        gml_features[1] = (gml_features[1][0], L3)
    elif tamper == "coordinate":
        g = json.loads(json.dumps(gml_features[4][0]))
        g["coordinates"][0][1][0] = 139.00500001
        gml_features[4] = (g, gml_features[4][1])
    else:
        gml_features = gml_features[:-1]
    write_a40(tdata / "a40" / "A40-23_13_GML.zip", gml=gml_text(gml_features))
    regions = regions_file(tdata, [t_source()])
    build_index(regions, tmp_path / "t.sqlite")
    out = verify_run(regions, tmp_path / "t.sqlite", sample=20)
    assert {"label": "ATTRIBUTES_DIFFER", "coordinate": "GEOMETRY_DIFFERS", "count": "FEATURE_COUNT_DIFFERS"}[tamper] \
        in out["failed"]


# 6. dependencies ------------------------------------------------------------------------------------------
def test_tsunami_depends_on_the_shared_engine_not_on_flood() -> None:
    code = ("import sys, hererisk.tsunami.index, hererisk.tsunami.verify, hererisk.location.tsunami_provider; "
            "print(sorted(m for m in sys.modules if m.startswith(('hererisk.flood', 'hererisk.research'))))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": str(REPO / "src")})
    assert out.stdout.strip() == "[]"
    provider_text = (REPO / "src/hererisk/location/tsunami_provider.py").read_text(encoding="utf-8")
    assert "from hererisk.common.polygon import relation" in provider_text and "relation.ComponentIndex(" in provider_text
    index_text = (REPO / "src/hererisk/tsunami/index.py").read_text(encoding="utf-8")
    assert "validity.classify_components" in index_text and "is_valid" not in index_text
    verify_text = (REPO / "src/hererisk/tsunami/verify.py").read_text(encoding="utf-8")
    assert "common.polygon" not in verify_text and "shapely" not in verify_text.split('"""')[-1]
    for name in ("a40.py", "index.py", "verify.py", "registry.py"):
        text = (REPO / "src/hererisk/tsunami" / name).read_text(encoding="utf-8")
        assert "make_valid" not in text and "buffer(" not in text
