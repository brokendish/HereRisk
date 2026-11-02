"""Phase 4-G: the flood diagnostic interpretation of a point (GET /api/v1/diagnostics/flood).

The official flood answer must be returned unchanged beside the interpretation; only the Provider's
unknowns are interpreted; Phase 4-E classes and Phase 4-F messages are used as they are; failures,
limits and overload are explicit (never a partial list, never "outside"). Synthetic data only.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip("shapely")

from hererisk.common import polygon_reasons as pr                       # noqa: E402
from hererisk.flood import diag, reason_messages, settings               # noqa: E402
from hererisk.flood.errors import DiagIndexError                          # noqa: E402
from hererisk.flood.index import build_index                               # noqa: E402
from hererisk.location import flood_diagnostics, server as location_server   # noqa: E402
from hererisk.location.api import FLOOD_DIAGNOSIS_PATH, PATH               # noqa: E402
from hererisk.location.flood_diagnostics import FloodDiagnosisApi           # noqa: E402
from hererisk.location.flood_provider import FloodProvider                 # noqa: E402
from test_flood_diag import FEATURES, INVERTED, ll, prepared, ring          # noqa: E402,F401  (fixture + helpers)
from test_flood_provider import feat, poly, source, write_a31a, write_isj, write_n03, write_regions, sq   # noqa: E402

RADII = [5, 10, 25, 50, 100]
GRID = [tuple(reversed(ll(x, y))) for x in range(-20, 1080, 53) for y in range(-20, 1850, 61)]
BANNED = ("安全", "浸水しません", "区域外です", "該当しません", "誤り", "危険")


def _api(prepared, radii=RADII, **kw):
    regions, index, diag_path, _ = prepared
    return FloodDiagnosisApi(FloodProvider(regions, index), diag_path, index, radii, **kw)


def _targets(section):
    return [(s["source_id"], s["service_region_relation"], [u["zone_ref"] for u in s["unknowns"]])
            for s in section.get("sources") or [] if s.get("unknowns")]


def _records(prepared, lat, lon):
    regions, index, diag_path, _ = prepared
    sec = FloodProvider(regions, index).lookup(lat, lon)
    return diag.DiagIndex(diag_path, flood_index=index).diagnose(lat, lon, RADII, _targets(sec), identity_ok=True)


def _settings(tmp_path, *, shadow=False, api=True):
    f = tmp_path / f"flood-settings-{shadow}-{api}.json"
    f.write_text(json.dumps({"local_analysis": settings.DEFAULT_LOCAL_ANALYSIS,
                             "diagnosis": {"shadow_enabled": shadow, "api_enabled": api}}))
    return f


def _server(prepared, tmp_path, *, api: bool | None, shadow=False):
    regions, index, diag_path, _ = prepared
    kw = {}
    if api is not None:
        kw = {"flood_settings": _settings(tmp_path, shadow=shadow, api=api),
              "flood_diag_index": diag_path if (api or shadow) else None}
    return location_server.build_server("127.0.0.1", 0, address_regions=regions, flood_index=index, **kw)


def _get(srv, path, lat, lon):
    r = srv.location_api.handle("GET", path, f"lat={lat:.9f}&lon={lon:.9f}")
    doc = r.json()
    doc.pop("evaluated_at", None)
    return r.status, doc


def _by_kind(api):
    out = {}
    for lat, lon in GRID:
        for it in api.lookup(lat, lon)["diagnostic"]["interpretations"] or []:
            out.setdefault(it["interpretation"], (lat, lon, it))
    return out


def test_interpretations_per_kind(prepared) -> None:
    api = _api(prepared)
    kinds = _by_kind(api)
    assert {"candidate_inside", "candidate_outside", "undetermined"} <= set(kinds)
    # 1. candidate + inside: the source's depth class, as the source gives it
    lat, lon, it = kinds["candidate_inside"]
    rec = next(r for r in _records(prepared, lat, lon) if r["zone_ref"] == it["zone_ref"])
    assert it["depth_class_in_source"] == rec["depth_class_in_source"] and it["depth_class_in_source"]["label"]
    assert it["message"]["message_ja"] == "この浸水深の想定区域に含まれる可能性があります。"
    assert it["certainty"] == "diagnostic_only" and it["official"] is False and it["relation"] == "inside"
    # 2. candidate + outside: never "safe", never no_match, no depth
    lat, lon, it = kinds["candidate_outside"]
    doc = api.lookup(lat, lon)
    assert it["message"]["message_ja"] == "参考解析では、この想定区域の外側と解釈されました。"
    assert "浸水しないことを意味しません" in it["message"]["detail_ja"] and it["depth_class_in_source"] is None
    assert not any(b in it["message"]["message_ja"] + it["message"]["detail_ja"] for b in BANNED)
    assert doc["official_assessment"]["status"] == "unknown"                  # not turned into no_match
    # 3. undetermined: the Phase 4-F message of the representative reason, no depth
    lat, lon, it = kinds["undetermined"]
    rec = next(r for r in _records(prepared, lat, lon) if r["zone_ref"] == it["zone_ref"])
    rep = pr.resolve_reasons(it["reasons"], "flood", params=reason_messages.message_params(rec))["representative"]
    assert it["message"] == {"code": rep["code"], "cause": rep["cause"], "message_ja": rep["message_ja"],
                             "detail_ja": rep["detail_ja"]}
    assert it["depth_class_in_source"] is None and it["relation"] is None
    assert [m["code"] for m in it["reason_messages"]] == it["reasons"] and all(m["known"] for m in it["reason_messages"])


def test_rejected_is_not_a_candidate(prepared, monkeypatch) -> None:
    api = _api(prepared, workers=1)
    slot = api._slots.queue[0]
    monkeypatch.setattr(slot.diag, "by_refs", lambda refs: [None for _ in refs])   # not in the diagnosis index
    lat, lon = tuple(reversed(ll(100, 400)))
    its = api.lookup(lat, lon)["diagnostic"]["interpretations"]
    assert its and all(i["classification"] == "rejected" and i["interpretation"] == "rejected" for i in its)
    assert all(i["relation"] is None and i["depth_class_in_source"] is None for i in its)
    assert its[0]["message"]["code"] == "zone_ref_not_in_diag_index" and its[0]["assessment_kind"] == "not_applicable"


def test_official_unchanged_and_only_unknowns(prepared, tmp_path, monkeypatch) -> None:
    servers = [_server(prepared, tmp_path, api=None), _server(prepared, tmp_path, api=False),
               _server(prepared, tmp_path, api=True), _server(prepared, tmp_path, api=True, shadow=True)]
    regions, index, diag_path, _ = prepared
    plain = FloodProvider(regions, index)
    fd = servers[2].location_api._flood_diagnosis.__self__
    seen = []
    for slot in list(fd._slots.queue):
        real = slot.diag.diagnose

        def spy(lat, lon, radii, targets, _real=real, **kw):
            seen.append([(s, r) for s, _, refs in targets for r in refs])
            return _real(lat, lon, radii, targets, **kw)
        monkeypatch.setattr(slot.diag, "diagnose", spy)
    try:
        n_targets = 0
        for lat, lon in GRID:
            locs = [_get(s, PATH, lat, lon) for s in servers]
            assert locs[0] == locs[1] == locs[2] == locs[3]                   # /location: unchanged when on
            st, doc = _get(servers[2], FLOOD_DIAGNOSIS_PATH, lat, lon)
            assert st == 200 and doc["schema_version"] == "flood-diagnostic-v0.1"
            official = doc["official_assessment"]
            assert official == locs[0][1]["hazards"]["flood"]                 # the same section, unchanged
            raw = {k: v for k, v in official.items() if k != "notice"}          # notice: added as for /location
            assert json.dumps(raw, sort_keys=True) == json.dumps(plain.lookup(lat, lon), sort_keys=True)
            want = [(s, r) for s, _, refs in _targets(official) for r in refs]
            got = [(i["source_id"], i["zone_ref"]) for i in doc["diagnostic"]["interpretations"]]
            assert got == want                                               # exactly the Provider's unknowns
            seen_now, seen[:] = [p for call in seen for p in call], []
            assert seen_now == want
            n_targets += len(want)
            assert all(i["zone_ref"] not in json.dumps(official.get("results")) for i in
                       doc["diagnostic"]["interpretations"])                 # never mixed into the official zones
            assert doc["diagnostic"]["complete"] is True and doc["diagnostic"]["official"] is False
        assert n_targets
        for s in servers[:2]:
            assert s.location_api.handle("GET", FLOOD_DIAGNOSIS_PATH, "lat=35&lon=139").status == 404   # off
        assert servers[2].location_api.handle("GET", FLOOD_DIAGNOSIS_PATH, "lat=1").status == 422
        assert servers[2].location_api.handle("GET", FLOOD_DIAGNOSIS_PATH, "lat=91&lon=139").status == 422
        assert servers[2].location_api.handle("GET", FLOOD_DIAGNOSIS_PATH, "lat=35&lon=139&x=1").status == 422
        assert servers[2].location_api.handle("POST", FLOOD_DIAGNOSIS_PATH, "lat=35&lon=139").status == 405
        assert servers[2].location_api.handle("GET", "/api/v1/diagnostics/flood-shadow", "").status == 404  # Shadow off
        assert servers[3].location_api.handle("GET", "/api/v1/diagnostics/flood-shadow", "").status == 200
    finally:
        for s in servers:
            s.server_close()


def test_phase_4e_classes_and_cases_a_b(prepared) -> None:
    api = _api(prepared)
    for lat, lon in GRID:
        its = api.lookup(lat, lon)["diagnostic"]["interpretations"]
        recs = _records(prepared, lat, lon)
        assert [(i["zone_ref"], i["classification"], i["reasons"]) for i in its] == \
            [(r["zone_ref"], r["classification"], r["reasons"]) for r in recs]
        assert [i["relation"] for i in its] == [r["relation"] for r in recs]
    for (lon, lat), code in ((INVERTED[6], "on_boundary"), (ll(410, 20), "defect_within_max_radius")):   # cases A / B
        its = api.lookup(lat, lon)["diagnostic"]["interpretations"]
        inv = [i for i in its if code in i["reasons"]]
        assert inv and all(i["classification"] == "undetermined" and i["depth_class_in_source"] is None for i in inv)


def test_missing_depth_class_is_not_invented() -> None:
    base = {"classification": "candidate", "relation": "inside", "reasons": ["all_conditions_met"],
            "source_id": "s", "zone_ref": "z", "method": "m", "adoption_version": "a"}
    for dc in (None, {}, {"class_code": "3"}, {"class_code": "", "label": "x"}, "3"):
        it = reason_messages.interpret({**base, "depth_class_in_source": dc})
        assert it["interpretation"] == "candidate_inside_class_unknown" and it["depth_class_in_source"] is None
        assert "浸水深は示していません" in it["message"]["detail_ja"]
    for cls, rel in (("undetermined", None), ("rejected", None), ("candidate", "outside")):
        it = reason_messages.interpret({**base, "classification": cls, "relation": rel,
                                        "reasons": ["on_boundary"] if cls != "candidate" else base["reasons"],
                                        "depth_class_in_source": {"class_code": "3", "label": "3.0～5.0m未満"}})
        assert it["depth_class_in_source"] is None                         # only a candidate read as inside


@pytest.fixture
def two_sources(tmp_path):
    d = tmp_path / "data2"
    (d / "a31a").mkdir(parents=True)
    write_n03(d / "N03-20260101_13_GML.zip", "13", sq(138.99, 34.99, 139.03, 35.03), "テスト都")
    write_isj(d / "13_2025.csv", "13", "テスト都", 139.005)
    write_a31a(d / "a31a" / "A31a-25_13_10_GEOJSON.zip", "13", {"1300000001": FEATURES})
    bowtie = ring((300, 300), (700, 700), (700, 300), (300, 700), (300, 300))
    b = [feat(poly(INVERTED), 4, "83", "関東地方整備局", ("8303000001", "国の川")),
         feat(poly(bowtie), 5, "83", "関東地方整備局", ("8303000001", "国の川"))]
    write_a31a(d / "a31a" / "A31a-25_83_10_GEOJSON.zip", "83", {"8303000001": b})
    regions = write_regions(d, [source("src-a", "東京都（合成）", "13", "13", ["a31a/A31a-25_13_10_GEOJSON.zip"]),
                                source("src-b", "関東地方整備局（合成）", "83", "83", ["a31a/A31a-25_83_10_GEOJSON.zip"])],
                            prefs=("13",))
    build_index(regions, tmp_path / "index2.sqlite")
    diag.build(regions, tmp_path / "index2.sqlite", tmp_path / "diag2.sqlite")
    return regions, tmp_path / "index2.sqlite", tmp_path / "diag2.sqlite", None


def test_several_zones_and_sources_stay_separate(two_sources) -> None:
    api = _api(two_sources)
    lat, lon = tuple(reversed(ll(500, 400)))
    doc = api.lookup(lat, lon)
    its = doc["diagnostic"]["interpretations"]
    assert sorted({i["source_id"] for i in its}) == ["src-a", "src-b"] and len(its) == 3
    assert len({i["zone_ref"] for i in its}) == 3
    for it in its:                                                          # each zone keeps its own class
        rec = next(r for r in _records(two_sources, lat, lon) if r["zone_ref"] == it["zone_ref"])
        assert it["classification"] == rec["classification"] and it["source_id"] == rec["source_id"]
        if it["interpretation"] == "candidate_inside":
            assert it["depth_class_in_source"] == rec["depth_class_in_source"]
    assert "zones" not in doc["diagnostic"] and "max_depth" not in json.dumps(doc)
    assert all(not s["zones"] for s in doc["official_assessment"]["sources"])   # nothing added to the official zones


def test_start_checks_the_diagnosis_index(prepared, tmp_path) -> None:
    regions, index, diag_path, _ = prepared
    good = diag_path.read_bytes()
    db = sqlite3.connect(diag_path)
    derived = json.loads(db.execute("SELECT value FROM meta WHERE key = 'derived_from'").fetchone()[0])
    derived["flood_index"]["built_at"] = "2000-01-01T00:00:00Z"
    db.execute("UPDATE meta SET value = ? WHERE key = 'derived_from'", (json.dumps(derived),))
    db.commit()
    db.close()
    with pytest.raises(DiagIndexError, match="another flood index"):
        _server(prepared, tmp_path, api=True)
    diag_path.write_bytes(good)
    db = sqlite3.connect(diag_path)
    db.execute("UPDATE meta SET value = ? WHERE key = 'status'", (json.dumps("building"),))
    db.commit()
    db.close()
    with pytest.raises(DiagIndexError, match="incomplete"):
        _server(prepared, tmp_path, api=True)
    diag_path.write_bytes(good)
    base = ["--port", "0", "--address-regions", str(regions), "--flood-index", str(index)]
    on = _settings(tmp_path, api=True)
    assert location_server.main(base + ["--flood-settings", str(on)]) == 2               # API without its index
    off = _settings(tmp_path, api=False)
    assert location_server.main(base + ["--flood-settings", str(off), "--flood-diag-index", str(diag_path)]) == 2
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"local_analysis": settings.DEFAULT_LOCAL_ANALYSIS,
                               "diagnosis": {"shadow_enabled": False, "api_enabled": "yes"}}))
    assert location_server.main(base + ["--flood-settings", str(bad), "--flood-diag-index", str(diag_path)]) == 2
    diag_path.unlink()
    assert location_server.main(base + ["--flood-settings", str(on), "--flood-diag-index", str(diag_path)]) == 3
    diag_path.write_bytes(good)


def _unknown_point(api):
    return next(p for p in GRID if api.lookup(*p)["diagnostic"]["targets_total"])


def test_timeout_limit_failure_are_explicit(prepared, monkeypatch) -> None:
    api = _api(prepared)
    lat, lon = _unknown_point(api)
    official = api.lookup(lat, lon)["official_assessment"]

    def check(status, code):
        doc = api.lookup(lat, lon)
        d = doc["diagnostic"]
        assert d["status"] == status and d["complete"] is False and d["interpretations"] is None
        assert d["reason"]["code"] == code and d["reason"]["message_ja"]
        assert doc["official_assessment"] == official                       # still the official answer
    monkeypatch.setattr(flood_diagnostics, "DIAGNOSIS_BUDGET_S", -1.0)
    check("timeout", "diagnosis_timeout")
    monkeypatch.setattr(flood_diagnostics, "DIAGNOSIS_BUDGET_S", 1.0)
    monkeypatch.setattr(flood_diagnostics, "MAX_TARGETS", 0)
    check("limit_exceeded", "diagnosis_limit_exceeded")
    monkeypatch.setattr(flood_diagnostics, "MAX_TARGETS", 32)
    for slot in list(api._slots.queue):
        monkeypatch.setattr(slot.diag, "diagnose", lambda *a, **k: (_ for _ in ()).throw(sqlite3.DatabaseError("x")))
    check("failed", "diagnosis_failed")
    no = api.lookup(*tuple(reversed(ll(5000, 5000))))                       # outside the region: nothing to diagnose
    assert no["diagnostic"]["status"] == "no_targets" and no["diagnostic"]["interpretations"] == []


def test_sqlite_interrupt_stays_on_its_own_connection(prepared) -> None:
    api = _api(prepared, workers=2)
    a, b = list(api._slots.queue)
    a.deadline = 1.0                                                          # long past: a is interrupted
    with pytest.raises(sqlite3.OperationalError, match="interrupt"):
        a.diag.db.execute("WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c WHERE x < 100000) "
                          "SELECT count(*) FROM c").fetchone()
    assert b.diag.db.execute("SELECT count(*) FROM comps").fetchone()[0] > 0
    a.deadline = 0.0
    assert a.diag.db.execute("SELECT count(*) FROM comps").fetchone()[0] > 0   # reusable afterwards


def test_concurrency_and_overload(prepared, monkeypatch) -> None:
    api = _api(prepared)
    want = {p: json.dumps({k: v for k, v in api.lookup(*p).items() if k != "evaluated_at"}, sort_keys=True)
            for p in GRID}
    with ThreadPoolExecutor(max_workers=16) as pool:
        got = list(pool.map(lambda p: (p, api.lookup(*p)), GRID * 3))
    busy = 0
    for p, doc in got:
        if doc["diagnostic"]["status"] == "busy":
            busy += 1
            assert doc["diagnostic"]["interpretations"] is None
            continue
        doc.pop("evaluated_at")
        assert json.dumps(doc, sort_keys=True) == want[p]
    assert busy < len(got) // 10
    # overload: the only connection is held; the next request answers busy without waiting long
    one = _api(prepared, workers=1)
    gate, entered = threading.Event(), threading.Event()
    slot = one._slots.queue[0]
    real = slot.diag.diagnose

    def slow(*a, **k):
        entered.set()
        gate.wait(5)
        return real(*a, **k)
    monkeypatch.setattr(slot.diag, "diagnose", slow)
    p = _unknown_point(_api(prepared))
    t = threading.Thread(target=one.lookup, args=p)
    t.start()
    entered.wait(5)
    doc = one.lookup(*p)
    assert doc["diagnostic"]["status"] == "busy" and doc["diagnostic"]["reason"]["code"] == "diagnosis_busy"
    assert doc["official_assessment"]["status"] in ("unknown", "available")
    gate.set()
    t.join(5)
    assert one.lookup(*p)["diagnostic"]["status"] == "complete"             # the connection was returned


def test_no_position_in_logs_or_files(prepared, tmp_path, capfd, monkeypatch) -> None:
    import socket
    from test_flood_provider import _REAL_CONNECT
    monkeypatch.setattr(socket.socket, "connect", lambda self, a: _REAL_CONNECT(self, a) if a[0] == "127.0.0.1"
                        else (_ for _ in ()).throw(AssertionError("only loopback")))
    regions, index, diag_path, _ = prepared
    before = (diag_path.read_bytes(), index.read_bytes())
    srv = _server(prepared, tmp_path, api=True)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        lat, lon = _unknown_point(_api(prepared))
        q = f"lat={lat:.9f}&lon={lon:.9f}"
        with socket.socket() as sock:
            sock.settimeout(5)
            sock.connect(("127.0.0.1", srv.server_address[1]))
            sock.sendall(f"GET {FLOOD_DIAGNOSIS_PATH}?{q} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
            data = b""
            while chunk := sock.recv(65536):
                data += chunk
        head, _, payload = data.partition(b"\r\n\r\n")
        assert b"Cache-Control: no-store" in head and json.loads(payload)["diagnostic"]["interpretations"]
    finally:
        srv.shutdown()
        srv.server_close()
    out = capfd.readouterr()
    assert f"{lat:.6f}"[:8] not in out.out + out.err and "diagnostics/flood" not in out.out + out.err
    assert (diag_path.read_bytes(), index.read_bytes()) == before             # read only
    assert sorted(p.name for p in tmp_path.iterdir() if p.suffix in (".sqlite", ".jsonl", ".log")) == \
        ["diag.sqlite", "index.sqlite"]
    fd = srv.location_api._flood_diagnosis.__self__
    assert f"{lat}" not in json.dumps({k: str(v) for k, v in vars(fd).items()})   # nothing about the point kept


def test_diag_api_verify_cli(prepared, tmp_path, capsys) -> None:
    from hererisk.flood import local_analysis
    from hererisk.flood.index import main as flood_cli
    regions, index, diag_path, _ = prepared
    rep = local_analysis.run(regions, index=index, per_category=4, per_rank=2, defect_points=4,
                             extra_points=[tuple(reversed(ll(410, 20))), tuple(reversed(INVERTED[6]))])
    base = local_analysis.write_report(rep, rep.pop("_geoms"), tmp_path / "reports")
    assert flood_cli(["diag", "compare", "--diag-index", str(diag_path), "--baseline", str(base),
                      "--report-dir", str(tmp_path / "reports")]) == 0
    cmp_dir = next(p for p in (tmp_path / "reports").iterdir() if p.name.startswith("flood-diag-compare-"))
    capsys.readouterr()
    args = ["diag-api-verify", "--regions", str(regions), "--flood-index", str(index), "--diag-index", str(diag_path),
            "--baseline", str(base), "--cases-dir", str(cmp_dir), "--threads", "4", "--report-dir", str(tmp_path / "out")]
    assert flood_cli(args) == 0
    out = json.loads(capsys.readouterr().out.split("report:")[0])
    n = out["inputs"]["points"]
    assert not out["failed"] and out["checks"]["official_equals_location_flood"] == n
    assert out["checks"]["location_identical_off_on"] == n and out["checks"]["phase_4e_classes_identical"]
    assert out["cases"] and not any(k.endswith(":candidate") for k in out["cases"])
    assert out["concurrency"]["4"]["requests"] == n
    diag_path.unlink()
    assert flood_cli(args[:-2]) == 3



def test_search_radius_comes_from_the_record(prepared) -> None:
    """Phase 4-I: the radius in the no_local_boundary text is the largest radius actually searched."""
    for radii, shown in ((RADII, "100"), ([5, 10, 25, 50], "50")):
        api = _api(prepared, radii=radii)
        seen = 0
        for lat, lon in GRID:
            doc = api.lookup(lat, lon)
            assert doc["diagnostic"]["message_version"] == "v0.2" and doc["diagnostic"]["radii_m"] == radii
            for it in doc["diagnostic"]["interpretations"] or []:
                text = json.dumps(it, ensure_ascii=False)
                assert "{max_radius_m}" not in text
                for m in it["reason_messages"]:
                    assert m["cause"] in pr.CAUSES
                    if m["code"] == "no_local_boundary":
                        seen += 1
                        assert m["cause"] == "search_scope"
                        assert m["message_ja"].startswith(f"周辺{shown}mの範囲では") and f"半径{shown}m" in m["detail_ja"]
                if it["message"].get("code") == "no_local_boundary":
                    assert it["message"]["message_ja"].startswith(f"周辺{shown}mの範囲では")
        assert seen, radii
