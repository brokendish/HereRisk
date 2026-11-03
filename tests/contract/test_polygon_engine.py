"""Phase 4-K: the shared Polygon Engine (hererisk.common.polygon) returns geometric facts only.

Synthetic geometry and ephemeral SQLite files only. The engine must not import a hazard package, must
not be called by the product yet, must count per-ring windings as the diagnosis index does, must never
return partial facts, and must not turn H2 into an inside / outside decision (Codex B1).
"""

from __future__ import annotations

import json
import math
import sqlite3
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from hererisk.common.polygon import facts as pf
from hererisk.common.polygon.sqlite_reader import Reader, ReaderError

REPO = Path(__file__).resolve().parents[2]
LAT0, LON0 = 35.0, 139.0
KX = 111320.0 * math.cos(math.radians(LAT0))


def ll(x, y):
    return (LON0 + x / KX, LAT0 + y / 111320.0)


def ring(*pts):
    return [ll(*p) for p in pts]


def at(x, y):
    lon, lat = ll(x, y)
    return lat, lon


def angle_winding(coords, lon, lat):
    """Independent of the ray method: the angular integral of one ring around the point."""
    t = []
    for (ax, ay), (bx, by) in zip(coords, coords[1:]):
        ax, ay, bx, by = ax - lon, ay - lat, bx - lon, by - lat
        t.append(math.atan2(ax * by - ay * bx, ax * bx + ay * by))
    return round(math.fsum(t) / (2 * math.pi))


SQ = lambda x0, y0, x1, y1: ring((x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0))   # noqa: E731
B1 = ring((0, 0), (1000, 0), (1000, 1000), (0, 1000), (0, 0), (0, 1000), (1000, 1000), (1000, 0), (0, 0),
          (-1000, 0), (0, -1000), (0, 0))
CIRCLE = [ll(1000 * math.cos(2 * math.pi * k / 600), 1000 * math.sin(2 * math.pi * k / 600)) for k in range(600)]
CIRCLE.append(CIRCLE[0])
CASES = {   # name: (rings, [(x, y, expected normalised winding, expected parity)])
    "square": ([SQ(0, 0, 1000, 1000)], [(500, 500, 1, True), (1500, 500, 0, False)]),
    "hole": ([SQ(0, 0, 1000, 1000), SQ(400, 400, 600, 600)], [(500, 500, 0, False), (100, 100, 1, True)]),
    "5 km": ([SQ(0, 0, 5000, 5000)], [(2500, 2500, 1, True)]),
    "corridor": ([SQ(0, 0, 5000, 300)], [(2500, 150, 1, True)]),
    "U": ([ring((0, 0), (1000, 0), (1000, 1000), (700, 1000), (700, 300), (300, 300), (300, 1000), (0, 1000), (0, 0))],
          [(500, 700, 0, False), (150, 600, 1, True)]),
    "self-touch": ([ring((0, 0), (1500, 0), (1200, 600), (1800, 600), (1500, 0), (3000, 0), (3000, 3000), (0, 3000), (0, 0))],
                   [(1500, 300, 0, False), (1500, 1500, 1, True)]),
    "self-crossing": ([ring((0, 0), (5000, 3000), (5000, 1000), (0, 3000), (0, 0))], [(4500, 2000, -1, True), (600, 2400, 1, True)]),
    "wound twice": ([ring((0, 0), (2000, 0), (2000, 2000), (0, 2000), (0, 10), (1990, 10), (1990, 1990), (10, 1990), (10, 0), (0, 0))],
                    [(1000, 1000, 2, False)]),
    "B1 cancelled": ([B1], [(500, 500, 0, False)]),
    "two holes": ([SQ(0, 0, 3000, 3000), SQ(500, 500, 1000, 1000), SQ(2000, 2000, 2500, 2500)],
                  [(700, 700, 0, False), (1500, 1500, 1, True), (2200, 2200, 0, False)]),
    "zero-area ring": ([SQ(0, 0, 2000, 2000), ring((1000, 1000), (1500, 1000), (1200, 1000), (1000, 1000))],
                       [(1200, 1040, 1, True)]),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_facts_match_an_independent_angular_winding(name) -> None:
    rings, points = CASES[name]
    for x, y, w, parity in points:
        lat, lon = at(x, y)
        f = pf.facts_from_rings(rings, lat, lon)
        assert f["status"] == "complete" and f["complete"] and not f["on_boundary"]
        assert f["raw_winding_per_ring"] == [angle_winding(r, lon, lat) for r in rings], (name, x, y)
        assert f["winding_normalised"] == w and f["parity_inside"] is parity, (name, x, y)
        assert f["ring_role"] == ["shell"] + ["hole"] * (len(rings) - 1)
        assert "relation" not in f and "inside" not in json.dumps(f).replace("parity_inside", "")   # facts only


def test_ring_order_and_direction_do_not_change_the_normalised_reading() -> None:
    for name, (rings, points) in CASES.items():
        if name == "zero-area ring":
            continue
        for x, y, w, parity in points:
            lat, lon = at(x, y)
            a = pf.facts_from_rings(rings, lat, lon)
            b = pf.facts_from_rings([list(reversed(r)) for r in rings], lat, lon)
            assert [-r for r in a["raw_winding_per_ring"]] == b["raw_winding_per_ring"]
            assert (a["winding_normalised"], a["parity_inside"], a["h2_per_ring_unit"]) == \
                (b["winding_normalised"], b["parity_inside"], b["h2_per_ring_unit"]), name
            if len(rings) > 1:      # hole order
                c = pf.facts_from_rings([rings[0], *reversed(rings[1:])], lat, lon)
                assert c["winding_normalised"] == a["winding_normalised"]


def test_h_and_h2() -> None:
    lat, lon = at(4500, 2000)
    f = pf.facts_from_rings(CASES["self-crossing"][0], lat, lon)
    assert f["h_winding_parity"] is False and f["h2_per_ring_unit"] is False
    lat, lon = at(1000, 1000)
    assert pf.facts_from_rings(CASES["wound twice"][0], lat, lon)["h2_per_ring_unit"] is False
    lat, lon = at(1200, 1040)
    z = pf.facts_from_rings(CASES["zero-area ring"][0], lat, lon)
    assert z["area_sign_per_ring"][1] == 0 and z["zero_area_ring_around_point"] is False and z["h2_per_ring_unit"]
    # the Phase 4-J H counterexample shape: a shell winding twice around the point and a hole subtracting once
    shell = ring((0, 0), (2000, 0), (2000, 2000), (0, 2000), (0, 10), (1990, 10), (1990, 1990), (10, 1990), (10, 0), (0, 0))
    lat, lon = at(1000, 1000)
    f = pf.facts_from_rings([shell, SQ(500, 500, 1500, 1500)], lat, lon)
    assert f["winding_normalised"] == 1 and f["parity_inside"] and f["h_winding_parity"] and not f["h2_per_ring_unit"]


def test_codex_b1_h2_true_is_not_an_agreed_or_outside_result() -> None:
    """Phase 4-J.1 B1: forward and backward traversal of the square cancels; H2 holds, interpretations differ."""
    shapely = pytest.importorskip("shapely")
    from shapely.geometry import Point, Polygon
    for scale in (1, 4):
        for reverse in (False, True):
            r = [ll(x * scale, y * scale) for x, y in [(0, 0), (1000, 0), (1000, 1000), (0, 1000), (0, 0), (0, 1000),
                                                         (1000, 1000), (1000, 0), (0, 0), (-1000, 0), (0, -1000), (0, 0)]]
            r = list(reversed(r)) if reverse else r
            lat, lon = at(500 * scale, 500 * scale)
            f = pf.facts_from_rings([r], lat, lon)
            assert f["raw_winding_per_ring"] == [0] and f["winding_normalised"] == 0 and f["parity_inside"] is False
            assert f["h_winding_parity"] and f["h2_per_ring_unit"]                       # H2 holds ...
            assert shapely.make_valid(Polygon(r), method="linework").contains(Point(lon, lat))   # ... yet linework reads inside
            # the engine returns no relation, no agreement and no "outside": H2 is a fact with a stated scope
            assert not {"relation", "interpretation", "classification", "candidate", "outside"} & set(f)
            assert "not every interpretation" in f["h2_scope"] and "not an official" in f["h2_scope"]


def test_boundary_uses_the_unrounded_distance() -> None:
    sq = CASES["square"][0]
    for y_mm, on in ((0.0, True), (0.5, True), (-0.5, True), (0.96, True), (1.04, False), (5.0, False)):
        lat, lon = at(500, y_mm / 1000)
        f = pf.facts_from_rings(sq, lat, lon)
        assert f["on_boundary"] is on, y_mm
        assert f["boundary_distance_m"] == pytest.approx(abs(y_mm) / 1000, abs=2e-6)
        if on:
            assert f["raw_winding_per_ring"] is None and f["h2_per_ring_unit"] is None     # not defined on a ring
    lat, lon = at(500, 500)
    far = pf.facts_from_rings(sq, lat, lon, boundary_search_m=1.0)
    assert far["boundary_distance_m"] is None and far["boundary_search_m"] == 1.0       # not "0", not a guess


# --- SQLite index -------------------------------------------------------------------------------------
def _schema():
    from hererisk.flood import diag      # the test builds the existing layout; the engine never imports it
    return diag


def _write_index(path: Path, comps: dict[str, list], *, chunk: int = 3, status: str = "complete") -> None:
    diag = _schema()
    from hererisk.flood.local_analysis import Prepared
    from shapely.geometry import Polygon
    db = sqlite3.connect(path)
    db.executescript(diag.SCHEMA)
    for cid, (ref, rings) in enumerate(comps.items(), start=1):
        prep = Prepared(Polygon(rings[0], rings[1:]))
        meta = np.array([(k > 0, prep.area_sign[k], prep.inner_left[k], len(r) - 1) for k, r in enumerate(rings)],
                        dtype=diag.RING_DTYPE)
        pts, kinds, same = diag._defect_kinds(prep)
        allv = np.concatenate([np.asarray(r) for r in rings])
        db.execute("INSERT INTO comps (id, zone_ref, source_id, product_ref, feature_index, polygon_index, reason, river_code, "
                   "river_name, manager, depth_class, minx, miny, maxx, maxy, valid, defects_unlocated, segments, defects, "
                   "zero_area_rings, rings) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (cid, ref, "s", "p", 0, 0, "invalid_geometry", "r", "r", "m", "{}", allv[:, 0].min(), allv[:, 1].min(),
                    allv[:, 0].max(), allv[:, 1].max(), int(prep.valid), int(prep.defects_unlocated), prep.segments, len(pts),
                    0, meta.tobytes()))
        db.execute("INSERT INTO comp_rtree VALUES (?,?,?,?,?)", (cid, allv[:, 0].min(), allv[:, 0].max(), allv[:, 1].min(), allv[:, 1].max()))
        for k, r in enumerate(rings):
            for start in range(0, len(r) - 1, chunk):
                v = np.array(r[start:start + chunk + 1], dtype="<f8")
                hid = db.execute("INSERT INTO chunks (comp, ring, chunk_no, coords) VALUES (?,?,?,?)",
                                 (cid, k, start // chunk, v.tobytes())).lastrowid
                db.execute("INSERT INTO chunk_rtree VALUES (?,?,?,?,?)",
                           (hid, v[:, 0].min(), v[:, 0].max(), v[:, 1].min(), v[:, 1].max()))
        for (x, y), kd, sr in zip(pts, kinds, same):
            did = db.execute("INSERT INTO defects (comp, x, y, kind, same_ring) VALUES (?,?,?,?,?)", (cid, x, y, kd, sr)).lastrowid
            db.execute("INSERT INTO defect_rtree VALUES (?,?,?,?,?)", (did, x, x, y, y))
    for k, v in (("diag_format", "hererisk-flood-diag-v0.1"), ("method", diag.METHOD), ("chunk_segments", chunk),
                 ("built_at", "2026-11-03T00:00:00Z"), ("status", status)):
        db.execute("INSERT INTO meta VALUES (?, ?)", (k, json.dumps(v)))
    db.commit()
    db.close()


@pytest.fixture
def index(tmp_path):
    pytest.importorskip("shapely")
    p = tmp_path / "diag.sqlite"
    comps = {name: rings for name, (rings, _) in CASES.items() if name != "zero-area ring"}
    comps["circle"] = [CIRCLE]
    _write_index(p, comps)
    return p


def test_reader_equals_in_memory_facts_across_chunk_boundaries(index) -> None:
    r = Reader(index)
    for name, (rings, points) in CASES.items():
        if name == "zero-area ring":
            continue
        for x, y, w, parity in points:
            lat, lon = at(x, y)
            got = r.point_facts(name, lat, lon)
            want = pf.facts_from_rings(rings, lat, lon)
            assert got["status"] == "complete" and got["complete"], name
            for k in ("raw_winding_per_ring", "winding_normalised", "parity_inside", "h_winding_parity",
                      "h2_per_ring_unit", "on_boundary", "ring_role", "area_sign_per_ring"):
                assert got[k] == want[k], (name, k)
    b1 = r.point_facts("B1 cancelled", *at(500, 500))
    assert b1["h2_per_ring_unit"] and b1["component_defect_kinds"].get("overlap")   # the cancellation leaves an overlap fact
    r.close()


def test_rtree_reads_only_the_chunks_near_the_point_and_the_ray(index) -> None:
    r = Reader(index)
    total = math.ceil((len(CIRCLE) - 1) / 3)
    for x, y in ((0, 0), (900, 0), (-500, 500), (0, -1500), (2000, 2000)):
        f = r.point_facts("circle", *at(x, y))
        want = pf.facts_from_rings([CIRCLE], *at(x, y))
        assert f["complete"] and f["raw_winding_per_ring"] == want["raw_winding_per_ring"]
        assert f["chunks_read"] < total / 4, (x, y, f["chunks_read"], total)        # not every chunk
        if (x, y) not in ((0, -1500), (2000, 2000)):
            assert f["chunks_read"] > 0
        else:
            assert f["chunks_read"] == 0 and f["raw_winding_per_ring"] == [0]      # outside the box: nothing to read
    r.close()


def test_reader_equals_the_existing_diag_index_winding(index) -> None:
    diag = _schema()
    d = diag.DiagIndex(index)
    r = Reader(index)
    for name, (rings, points) in CASES.items():
        if name == "zero-area ring":
            continue
        comp = d.by_refs([name])[0]
        for x in range(-300, 5300, 410):
            for y in range(-300, 3300, 370):
                lat, lon = at(x + 0.37, y + 0.53)
                f = r.point_facts(name, lat, lon)
                if f["on_boundary"]:
                    continue
                w, crossings = d.winding(comp, lat, lon)
                assert (f["winding_normalised"], f["parity_inside"]) == (w, bool(crossings % 2)), (name, x, y)
    r.close()


def test_reader_never_returns_partial_facts(index, tmp_path, monkeypatch) -> None:
    r = Reader(index)
    lat, lon = at(2500, 2500)
    for kw, status in (({"max_chunks": 1}, "limit_exceeded"), ({"budget_s": -1.0}, "timeout")):
        f = r.point_facts("5 km", lat, lon, **kw) if status == "timeout" else r.point_facts("B1 cancelled", *at(500, 500), **kw)
        assert f["status"] == status and f["complete"] is False
        assert "raw_winding_per_ring" not in f and "parity_inside" not in f and "winding_normalised" not in f
    assert r.point_facts("no such zone", lat, lon) == {**r.point_facts("no such zone", lat, lon), "status": "not_found", "complete": False}

    class Broken:
        def __getattr__(self, name):
            return getattr(r.db, name)

        def execute(self, *a, **k):
            raise sqlite3.DatabaseError("database disk image is malformed")
    real = r.db
    r.db = Broken()
    f = r.point_facts("square", *at(500, 500))
    assert f["status"] == "failed" and not f["complete"] and "parity_inside" not in f
    r.db = real
    r.close()
    with pytest.raises(ReaderError):
        Reader(tmp_path / "missing.sqlite")
    (tmp_path / "junk.sqlite").write_bytes(b"not a database" * 100)
    with pytest.raises(ReaderError):
        Reader(tmp_path / "junk.sqlite")
    _write_index(tmp_path / "building.sqlite", {"square": CASES["square"][0]}, status="building")
    with pytest.raises(ReaderError, match="incomplete"):
        Reader(tmp_path / "building.sqlite")


def test_reader_is_read_only(index) -> None:
    before = index.read_bytes()
    r = Reader(index)
    with pytest.raises(sqlite3.OperationalError):
        r.db.execute("DELETE FROM comps")
    r.point_facts("square", *at(500, 500))
    r.close()
    assert index.read_bytes() == before


def test_engine_depends_on_no_hazard_and_is_not_used_by_the_product() -> None:
    code = ("import sys, hererisk.common.polygon.facts, hererisk.common.polygon.sqlite_reader; "
            "print(sorted(m for m in sys.modules if m.startswith(('hererisk.flood', 'hererisk.location', 'hererisk.research', 'shapely'))))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": str(REPO / "src")})
    assert out.stdout.strip() == "[]"                       # no hazard, no research, not even shapely
    for path in (REPO / "src/hererisk").rglob("*.py"):
        if "research" in path.parts or path.parts[-3:-1] == ("common", "polygon"):
            continue
        text = path.read_text(encoding="utf-8")
        assert "hererisk.common.polygon." not in text and "hererisk.common.polygon import" not in text, path   # not wired in yet
