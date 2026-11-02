"""Phase 4-E: classification of flood diagnoses and the Location API Shadow integration.

The official flood answer must be identical with Shadow off and on; only the Provider's unknowns are
diagnosed; a missing / incomplete / foreign diagnosis index stops the start; run-time failures are
counted, never hidden, and never change the answer. Synthetic data only.
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

pytest.importorskip("shapely")

from hererisk.flood import adoption, settings                        # noqa: E402
from hererisk.flood.errors import DiagIndexError                     # noqa: E402
from hererisk.location import flood_shadow, server as location_server   # noqa: E402
from hererisk.location.api import DIAGNOSTICS_PATH, PATH             # noqa: E402
from hererisk.location.flood_provider import FloodProvider            # noqa: E402
from hererisk.location.flood_shadow import ShadowFloodProvider        # noqa: E402
from test_flood_diag import INVERTED, ll, prepared                   # noqa: E402,F401  (fixture + helpers)

RADII = [5, 10, 25, 50, 100]
GRID = [tuple(reversed(ll(x, y))) for x in range(-20, 1080, 53) for y in range(-20, 1850, 61)]


def ctx(**kw):
    return {"status": "complete", "identity_ok": True, "in_provider_unknowns": True,
            "service_region_relation": "inside", **kw}


def comp(**kw):
    return {"reason": "invalid_geometry", "ring_count": 1, **kw}


def local(outcome, **kw):
    return {"local": {"outcome": outcome, "radius_m": 25, **kw}, "defect_within_max": None}


def test_adoption_rules() -> None:
    ok = local("inside", winding=1, parity_inside=True, edge_m=19.0)
    r = adoption.classify(ctx(), comp(), ok)
    assert r["classification"] == "candidate" and r["relation"] == "inside" and r["evidence"]["decided_at_m"] == 25
    out = adoption.classify(ctx(), comp(), local("outside", winding=0, parity_inside=False))
    assert out["classification"] == "candidate" and out["relation"] == "outside"
    for bad, code in ((ctx(status="building"), "diag_index_not_complete"),
                      (ctx(identity_ok=False), "diag_index_identity_mismatch"),
                      (ctx(in_provider_unknowns=False), "zone_ref_not_in_provider_unknowns"),
                      (ctx(service_region_relation=None), "outside_service_region")):
        r = adoption.classify(bad, comp(), ok)
        assert r["classification"] == "rejected" and code in r["reasons"] and r["relation"] is None
    assert adoption.classify(ctx(), None, None)["reasons"] == ["zone_ref_not_in_diag_index"]
    for outcome, code in adoption.LOCAL_UNDETERMINED.items():
        r = adoption.classify(ctx(), comp(), local(outcome))
        assert r["classification"] == "undetermined" and r["reasons"] == [code] and r["relation"] is None
    cases = [(ctx(service_region_relation="boundary"), comp(), ok, "service_region_boundary"),
             (ctx(), comp(reason="feature_invalid_component"), ok, "feature_level_invalidity_not_analyzed"),
             (ctx(), comp(), local("inside", winding=1, parity_inside=False), "even_odd_winding_disagree"),
             (ctx(), comp(), local("inside", winding=2, parity_inside=True), "local_far_disagree"),
             (ctx(), comp(), {**ok, "defect_within_max": (52.0, "touch")}, "defect_within_max_radius")]
    for c, k, a, code in cases:
        r = adoption.classify(c, k, a)
        assert r["classification"] == "undetermined" and code in r["reasons"]
    b = adoption.classify(ctx(), comp(), {**ok, "defect_within_max": (52.0, "touch")})
    assert b["evidence"]["reading"] == "inside" and b["evidence"]["defect_kind"] == "touch"   # kept as a fact only


def test_settings_diagnosis_block(tmp_path) -> None:
    assert settings.load_settings(None)["diagnosis"] == {"shadow_enabled": False, "api_enabled": False}
    la = dict(settings.DEFAULT_LOCAL_ANALYSIS)
    f = tmp_path / "s.json"
    f.write_text(json.dumps({"local_analysis": la}))                      # a Phase 4-C file still loads
    assert settings.load_settings(f)["diagnosis"]["shadow_enabled"] is False
    f.write_text(json.dumps({"local_analysis": la, "diagnosis": {"shadow_enabled": True}}))
    assert settings.load_settings(f)["diagnosis"] == {"shadow_enabled": True, "api_enabled": False}   # a 4-E file
    for bad in ({"local_analysis": la, "diagnosis": {"shadow_enabled": 1}},
                {"local_analysis": la, "diagnosis": {"shadow_enabled": True, "x": 1}},
                {"local_analysis": {**la, "enabled": True}, "diagnosis": {"shadow_enabled": True}},
                {"diagnosis": {"shadow_enabled": True}}, {"local_analysis": la, "other": {}}):
        f.write_text(json.dumps(bad))
        with pytest.raises(settings.FloodSettingsError):
            settings.load_settings(f)
    assert settings.describe()["diagnosis"]["fields"]["shadow_enabled"]["type"] == "boolean"


def test_shadow_keeps_the_official_answer_and_diagnoses_only_unknowns(prepared, monkeypatch) -> None:
    regions, index, diag_path, _ = prepared
    plain = FloodProvider(regions, index)
    shadow = ShadowFloodProvider(FloodProvider(regions, index), diag_path, index, RADII)
    seen = []
    real = shadow._diag.diagnose

    def spy(lat, lon, radii, targets, **kw):
        seen.append(sorted(r for _, _, refs in targets for r in refs))
        return real(lat, lon, radii, targets, **kw)
    monkeypatch.setattr(shadow._diag, "diagnose", spy)
    want = []
    for lat, lon in GRID:
        a, b = plain.lookup(lat, lon), shadow.lookup(lat, lon)
        assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
        refs = sorted(u["zone_ref"] for s in a.get("sources") or [] for u in s["unknowns"])
        if refs:
            want.append(refs)
        shadow.drain()                               # one at a time: no queue overflow here
    assert seen == want and want                     # exactly the Provider's unknowns, in order
    st = shadow.stats()
    assert st["state"] == "active" and st["counts"]["diagnosed_points"] == len(want) and not st["errors"]
    assert st["counts"].get("candidate") and st["counts"].get("undetermined")
    assert st["positions_kept"] is False and str(GRID[0][0])[:7] not in json.dumps(st)


def test_case_classes_through_the_shadow_records(prepared) -> None:
    regions, index, diag_path, _ = prepared
    shadow = ShadowFloodProvider(FloodProvider(regions, index), diag_path, index, RADII)
    lon, lat = INVERTED[6]                                   # on the ring (case A)
    lat2, lon2 = tuple(reversed(ll(410, 20)))                # decided at 5 m, the pinch at 22 m (case B)
    for (la, lo), code in (((lat, lon), "on_boundary"), ((lat2, lon2), "defect_within_max_radius")):
        sec = FloodProvider(regions, index).lookup(la, lo)
        targets = [(s["source_id"], s["service_region_relation"], [u["zone_ref"] for u in s["unknowns"]])
                   for s in sec["sources"] if s["unknowns"]]
        recs = shadow._diag.diagnose(la, lo, RADII, targets, identity_ok=True)
        inv = [r for r in recs if r["depth_class_in_source"]["class_code"] == "3"]
        assert inv and inv[0]["classification"] == "undetermined" and code in inv[0]["reasons"]
        assert sec["status"] == "unknown"                    # the official answer stays unknown


def test_parallel_requests_and_queue_full(prepared, monkeypatch) -> None:
    regions, index, diag_path, _ = prepared
    plain = FloodProvider(regions, index)
    shadow = ShadowFloodProvider(FloodProvider(regions, index), diag_path, index, RADII)
    want = {p: json.dumps(plain.lookup(*p), sort_keys=True) for p in GRID}
    with ThreadPoolExecutor(max_workers=16) as pool:
        got = list(pool.map(lambda p: (p, json.dumps(shadow.lookup(*p), sort_keys=True)), GRID * 3))
    assert all(want[p] == g for p, g in got)
    shadow.drain(10)
    assert not shadow.stats()["errors"]
    gate = threading.Event()
    blocked = ShadowFloodProvider(FloodProvider(regions, index), diag_path, index, RADII)
    monkeypatch.setattr(blocked._diag, "diagnose", lambda *a, **k: gate.wait(5) and [])
    point = next(p for p in GRID if plain.lookup(*p).get("sources") and
                 any(s["unknowns"] for s in plain.lookup(*p)["sources"]))
    t0 = time.perf_counter()
    for _ in range(flood_shadow.QUEUE_SIZE + 20):
        assert json.dumps(blocked.lookup(*point), sort_keys=True) == want[point]
    assert time.perf_counter() - t0 < 2.0                  # the answer never waits for the diagnosis
    assert blocked.stats()["counts"]["skipped_queue_full"] >= 19
    gate.set()


def test_runtime_failures_are_counted_not_hidden(prepared, monkeypatch) -> None:
    regions, index, diag_path, _ = prepared
    plain = FloodProvider(regions, index)
    shadow = ShadowFloodProvider(FloodProvider(regions, index), diag_path, index, RADII)

    def boom(*a, **k):
        raise sqlite3.DatabaseError("database disk image is malformed")
    monkeypatch.setattr(shadow._diag, "diagnose", boom)
    for p in GRID:
        assert json.dumps(shadow.lookup(*p), sort_keys=True) == json.dumps(plain.lookup(*p), sort_keys=True)
    shadow.drain()
    st = shadow.stats()
    assert st["state"] == "error" and st["errors"]["DatabaseError"] > 0 and "candidate" not in st["counts"]
    slow = ShadowFloodProvider(FloodProvider(regions, index), diag_path, index, RADII)
    monkeypatch.setattr(flood_shadow, "DIAGNOSIS_BUDGET_S", -1.0)   # every diagnosis is over its budget
    for p in GRID:
        slow.lookup(*p)
    slow.drain()
    assert slow.stats()["errors"].get("timeout", 0) > 0 and slow.stats()["state"] == "error"


def _server(prepared, tmp_path, *, shadow: bool | None, diag=True):
    regions, index, diag_path, _ = prepared
    kw = {}
    if shadow is not None:
        f = tmp_path / f"flood-settings-{shadow}.json"
        f.write_text(json.dumps({"local_analysis": settings.DEFAULT_LOCAL_ANALYSIS,
                                 "diagnosis": {"shadow_enabled": shadow}}))
        kw = {"flood_settings": f, "flood_diag_index": diag_path if diag else None}
    return location_server.build_server("127.0.0.1", 0, address_regions=regions, flood_index=index, **kw)


def _flood(srv, lat, lon):
    doc = srv.location_api.handle("GET", PATH, f"lat={lat:.9f}&lon={lon:.9f}").json()
    doc.pop("evaluated_at")
    return doc


def test_location_api_answer_identical_with_shadow_off_and_on(prepared, tmp_path) -> None:
    servers = [_server(prepared, tmp_path, shadow=None), _server(prepared, tmp_path, shadow=False, diag=False),
               _server(prepared, tmp_path, shadow=True)]
    try:
        for lat, lon in GRID:
            docs = [_flood(s, lat, lon) for s in servers]
            assert docs[0] == docs[1] == docs[2]
        assert servers[0].location_api.handle("GET", DIAGNOSTICS_PATH, "").status == 404   # off: as before
        assert servers[1].location_api.handle("GET", DIAGNOSTICS_PATH, "").status == 404
        r = servers[2].location_api.handle("GET", DIAGNOSTICS_PATH, "")
        assert r.status == 200 and r.json()["flood_shadow"]["official_answer_changed"] is False
        assert servers[2].location_api.handle("GET", DIAGNOSTICS_PATH, "lat=1").status == 422
        assert servers[2].location_api.handle("POST", DIAGNOSTICS_PATH, "").status == 405
        # timing: Shadow adds a queue put to the request, not the diagnosis
        times = {0: [], 2: []}
        for _ in range(3):
            for lat, lon in GRID:
                for k in times:
                    t0 = time.perf_counter()
                    _flood(servers[k], lat, lon)
                    times[k].append(time.perf_counter() - t0)
        assert statistics.median(times[2]) < statistics.median(times[0]) + 0.002
    finally:
        for s in servers:
            s.server_close()


def test_start_is_refused_for_a_bad_diagnosis_index(prepared, tmp_path) -> None:
    regions, index, diag_path, _ = prepared
    good = diag_path.read_bytes()
    diag_path.unlink()
    with pytest.raises(DiagIndexError, match="not found"):
        _server(prepared, tmp_path, shadow=True)
    diag_path.write_bytes(good[:4096])                                   # truncated
    with pytest.raises(DiagIndexError):
        _server(prepared, tmp_path, shadow=True)
    diag_path.write_bytes(good)
    for broken in ("2000-01-01T00:00:00Z", "other-generation"):
        db = sqlite3.connect(diag_path)
        derived = json.loads(db.execute("SELECT value FROM meta WHERE key = 'derived_from'").fetchone()[0])
        if broken == "other-generation":
            derived["flood_index"]["built_at"] = "2000-01-01T00:00:00Z"
        else:
            derived = broken
        db.execute("UPDATE meta SET value = ? WHERE key = 'derived_from'", (json.dumps(derived),))
        db.commit()
        db.close()
        with pytest.raises(DiagIndexError, match="another flood index"):
            _server(prepared, tmp_path, shadow=True)
        diag_path.write_bytes(good)
    diag_path.write_bytes(good)
    with pytest.raises(ValueError):
        _server(prepared, tmp_path, shadow=False)                          # a diag index with Shadow off
    f = tmp_path / "on.json"
    f.write_text(json.dumps({"local_analysis": settings.DEFAULT_LOCAL_ANALYSIS, "diagnosis": {"shadow_enabled": True}}))
    base = ["--port", "0", "--address-regions", str(regions), "--flood-index", str(index)]
    assert location_server.main(base + ["--flood-settings", str(f)]) == 2              # Shadow without its index
    assert location_server.main(base + ["--flood-diag-index", str(diag_path)]) == 2    # index without Shadow
    diag_path.unlink()
    assert location_server.main(base + ["--flood-settings", str(f), "--flood-diag-index", str(diag_path)]) == 3
    diag_path.write_bytes(good)


def test_shadow_verify_cli(prepared, tmp_path, capsys) -> None:
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
    args = ["shadow-verify", "--regions", str(regions), "--flood-index", str(index), "--diag-index", str(diag_path),
            "--baseline", str(base), "--cases-dir", str(cmp_dir), "--threads", "4", "--report-dir", str(tmp_path / "out")]
    assert flood_cli(args) == 0
    out = json.loads(capsys.readouterr().out.split("report:")[0])
    assert not out["failed"] and out["checks"]["official_identical"] == out["inputs"]["points"]
    assert out["cases"]["A"]["all_undetermined"] and out["cases"]["B"]["all_undetermined"]
    assert out["cases"]["B"]["pairs"] == out["cases"]["B"]["expected_pairs"] > 0
    rec = json.loads(next((tmp_path / "out").iterdir()).joinpath("records.jsonl").read_text().splitlines()[0])
    assert {"method", "adoption_version", "source_id", "zone_ref", "classification", "reasons", "seconds"} <= set(rec)
    diag_path.unlink()
    assert flood_cli(args[:-2]) == 3
