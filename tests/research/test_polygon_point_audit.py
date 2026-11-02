"""Phase 4-J.1: independent, synthetic-only audit reproductions. No product changes."""
import math
import sqlite3

import numpy as np
import pytest
import shapely
from shapely.geometry import Point, Polygon

from hererisk.flood import diag
from hererisk.flood.local_analysis import Prepared
from hererisk.research import point_study as ps

# Square forward, same square backward, then a separate positive-area triangle.
# The triangle keeps the ring's signed area nonzero; there are no hole rings.
RING = [(0, 0), (1000, 0), (1000, 1000), (0, 1000), (0, 0),
        (0, 1000), (1000, 1000), (1000, 0), (0, 0),
        (-1000, 0), (0, -1000), (0, 0)]


def angle_winding(coords, point):
    """Independent angular integral, not the study's horizontal ray algorithm."""
    x, y = point
    terms = []
    for (ax, ay), (bx, by) in zip(coords, coords[1:]):
        ax, ay, bx, by = ax-x, ay-y, bx-x, by-y
        terms.append(math.atan2(ax*by-ay*bx, ax*bx+ay*by))
    return round(math.fsum(terms) / (2*math.pi))


@pytest.mark.parametrize('reverse', [False, True])
@pytest.mark.parametrize('scale', [1, 4])
def test_h2_does_not_imply_interpretation_agreement(reverse, scale):
    ring = [(x*scale, y*scale) for x, y in RING]
    if reverse:
        ring.reverse()
    point = (500*scale, 500*scale)
    # Exact integer shoelace: nonzero orientation; square traversals cancel.
    area2 = sum(ax*by-bx*ay for (ax, ay), (bx, by) in zip(ring, ring[1:]))
    assert area2 == (-1 if reverse else 1)*1000000*scale**2
    assert angle_winding(ring, point) == 0
    # Independent geometric construction: point lies in the square, outside triangle.
    assert Polygon(RING[:5]).contains(Point(500, 500))
    assert not Polygon(RING[8:]).covers(Point(500, 500))
    g = ps._poly(ring)
    lon, lat = ps.ll(*point)
    result = ps.assess(g, lat, lon)
    assert result['facts']['h2_per_ring_unit']
    assert result['facts']['raw_winding_per_ring'] == [0]
    assert result['facts']['edge_m'] > 490*scale
    assert result['interpretations']['even_odd'] == 'outside'
    assert result['interpretations']['nonzero'] == 'outside'
    assert result['interpretations']['make_valid_linework'] == 'inside'
    assert result['interpretations']['make_valid_structure'] == 'outside'
    assert result['interpretations']['buffer0'] == 'outside'
    assert result['study']['class'] == 'interpretation_dependent'
    assert not any(v['conditions_met'] for v in result['local'].values())
    # Call GEOS directly as well: disagreement is not caused by study classification.
    assert shapely.make_valid(g, method='linework').contains(Point(lon, lat))
    assert not shapely.make_valid(g, method='structure').contains(Point(lon, lat))


def test_existing_sqlite_layout_retains_per_ring_evidence():
    # Ephemeral database only. No official or diagnostic index is modified.
    rings = [[ps.ll(*p) for p in RING],
             [ps.ll(*p) for p in [(100, 100), (200, 100), (200, 200), (100, 200), (100, 100)]]]
    prep = Prepared(Polygon(rings[0], rings[1:]))
    d = object.__new__(diag.DiagIndex)
    d.db = sqlite3.connect(':memory:')
    d.db.executescript(diag.SCHEMA)
    d.chunk = 3  # Force joins across chunk boundaries, including repeated vertices.
    metadata = np.array([(k > 0, prep.area_sign[k], prep.inner_left[k], len(r)-1)
                         for k, r in enumerate(rings)], dtype=diag.RING_DTYPE)
    for k, ring in enumerate(rings):
        for start in range(0, len(ring)-1, d.chunk):
            v = np.array(ring[start:start+d.chunk+1], dtype='<f8')
            cid = d.db.execute('INSERT INTO chunks(comp,ring,chunk_no,coords) VALUES(?,?,?,?)',
                               (1, k, start//d.chunk, v.tobytes())).lastrowid
            d.db.execute('INSERT INTO chunk_rtree VALUES(?,?,?,?,?)',
                         (cid, v[:, 0].min(), v[:, 0].max(), v[:, 1].min(), v[:, 1].max()))
    g = Polygon(rings[0], rings[1:])
    minx, miny, maxx, maxy = g.bounds
    comp = dict(id=1, minx=minx, miny=miny, maxx=maxx, maxy=maxy, rings=metadata)
    # Points exercise east, west, north and south shortest rays and hole membership.
    for xy in [(900, 500), (-900, -20), (100, 900), (10, -900), (150, 150), (500, 500)]:
        lon, lat = ps.ll(*xy)
        raw = [angle_winding(r, (lon, lat)) for r in rings]
        # Recover per-ring winding from stored chunks via angular integration.
        angles = [[] for _ in rings]
        for k, blob in d.db.execute('SELECT ring,coords FROM chunks WHERE comp=1'):
            v = np.frombuffer(blob, '<f8').reshape(-1, 2) - [lon, lat]
            for a, b in zip(v, v[1:]):
                angles[k].append(math.atan2(a[0]*b[1]-a[1]*b[0], np.dot(a, b)))
        assert [round(math.fsum(a)/(2*math.pi)) for a in angles] == raw
        w, crossings = d.winding(comp, lat, lon)
        assert w == sum(r*prep.area_sign[k]*(-1 if k else 1) for k, r in enumerate(raw))
        assert crossings % 2 == sum(raw) % 2
    d.db.close()


@pytest.mark.parametrize('offset', [0, 0.0005, -0.0005])
def test_boundary_is_held(offset):
    g = ps._poly([(0, 0), (1000, 0), (1000, 1000), (0, 1000), (0, 0)])
    lon, lat = ps.ll(500, offset)
    assert ps.assess(g, lat, lon)['study']['class'] == 'on_boundary'
