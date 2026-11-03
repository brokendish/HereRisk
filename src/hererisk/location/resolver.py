"""Location Resolver (Phase 4-N.2): a point's relation to the registered N03 administrative areas.

Contract: docs/api/location-resolver-contract-v0.1.md (chapter 2). Reads the index built by
``hererisk.location.admin_index``; nothing is loaded into memory at start but the index metadata.

Per point (``resolve``):

1. the R-tree gives the areas whose bounding box lies within the tolerance (``BOUNDARY_TOLERANCE_M``,
   10 m, as a degree distance on the longitude scale: the same tolerance as ``N03Municipalities`` and the
   providers' ``_Region``). The R-tree stores 32-bit floats rounded outwards, so it never misses an area;
   it is never used as the relation itself
2. only those areas' geometries are read (WKB) and tested with GEOS ``dwithin``; the areas within the
   tolerance are the point's candidates
3. per municipality (and per prefecture set in ``region_relation``) only the candidates are merged (GEOS
   union of the whole candidate features, per point), so seams between features of one municipality, and
   borders inside a prefecture set, are not boundaries; features farther than the tolerance cannot change
   the result. The stored geometries are the N03 features as parsed (nothing merged in the index,
   repaired or simplified)

States: ``inside`` (one municipality, farther than the tolerance from its edge), ``near_boundary`` (every
area within the tolerance listed; never forced to one prefecture), ``outside_admin_area`` (national
registration, no area within the tolerance), ``outside_registered_area`` (partial registration: the
outside may be another prefecture, never called "sea"), ``failed`` (read failure or no free connection:
no partial candidates).

Concurrency: read-only SQLite connections in a bounded pool; a connection is held for the whole decision of
a point (read, WKB parse, GEOS), so at most ``connections`` decisions run at once and the transient memory
does not grow with the calling threads. A free one is waited for at most ``acquire_wait_s``, else
``failed`` (``busy``). The result of a point is a new object per call (it holds its candidates' geometry
for ``region_relation`` until the caller drops it); nothing mutable is shared between requests.
"""

from __future__ import annotations

import math
import queue
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import shapely

from hererisk.location.admin_index import AdminIndexError, read_meta, registration, sha256_file
from hererisk.location.n03_municipality import BOUNDARY_TOLERANCE_M

INSIDE, NEAR, OUTSIDE_ADMIN, OUTSIDE_REGISTERED, FAILED = (
    "inside", "near_boundary", "outside_admin_area", "outside_registered_area", "failed")


class ResolverInputError(ValueError):
    """The point is not a pair of finite numbers in range (the caller validates first)."""


class ResolverBusy(RuntimeError):
    """No resolver slot became free within ``acquire_wait_s`` (the caller answers an error, never a guess)."""


def tolerance_deg(lat: float) -> float:
    return BOUNDARY_TOLERANCE_M / (111320.0 * max(0.01, math.cos(math.radians(lat))))


@dataclass(frozen=True)
class _Area:
    prefecture_code: str
    municipality_code: str
    unassigned: bool
    prefecture_name: str
    municipality_name: str
    geometry: Any


@dataclass(frozen=True)
class ResolvedLocation:
    status: str
    lat: float
    lon: float
    tolerance_deg: float
    coverage: str
    prefectures: tuple[dict[str, Any], ...] = ()
    municipalities: tuple[dict[str, Any], ...] = ()
    reason: str | None = None
    source: dict[str, Any] = field(default_factory=dict)
    _near: tuple[_Area, ...] = field(default=(), repr=False, compare=False)    # the candidates (this point only)

    @property
    def complete(self) -> bool:
        return self.status != FAILED

    def view(self) -> dict[str, Any]:
        out = {"status": self.status, "complete": self.complete, "prefectures": list(self.prefectures),
               "municipalities": list(self.municipalities), "tolerance_m": BOUNDARY_TOLERANCE_M,
               "coverage": self.coverage, "source": self.source}
        if self.reason:
            out["reason"] = self.reason
        return out


def _local(areas: Iterable[_Area], x: float, y: float, tol: float) -> Any:
    """The union of the candidate areas (those within the tolerance), not clipped.

    Clipping before the union was tried and rejected (Tokyo comparison): both ``clip_by_rect`` and an
    ``intersection`` with a box rebuild each feature's shared edge on its own, so the union of the clipped
    neighbours keeps a seam (a boundary that the union of the whole features does not have). Areas farther
    than the tolerance cannot change the relation within the tolerance, so only the candidates are merged."""
    parts = [a.geometry for a in areas]
    return shapely.union_all(parts) if len(parts) > 1 else parts[0]


def _relation(areas: list[_Area], pt: Any, x: float, y: float, tol: float) -> str | None:
    """``_Region.relation`` on the union of ``areas`` (all within the tolerance), computed locally."""
    if not areas:
        return None
    g = _local(areas, x, y, tol)
    if g.contains(pt) and not shapely.dwithin(g.boundary, pt, tol):
        return INSIDE
    return "boundary"


class LocationResolver:
    def __init__(self, index: Path, *, regions_file: Path | None = None, connections: int = 4,
                 acquire_wait_s: float = 0.5, verify_sources: bool = True) -> None:
        """Opens the index (complete, this format). With ``regions_file`` the registered prefectures and,
        with ``verify_sources``, the SHA-256 of each N03 ZIP must equal the index's (else AdminIndexError)."""
        self.meta = read_meta(index)
        if regions_file is not None:
            regs = registration(regions_file)
            if [r["prefecture_code"] for r in regs] != self.meta["prefectures"]:
                raise AdminIndexError("the administrative-area index was built from another registration")
            for r in regs:
                f = self.meta["files"][r["prefecture_code"]]
                if r["path"].name != f["file_name"] or (verify_sources and sha256_file(r["path"]) != f["sha256"]):
                    raise AdminIndexError("a registered N03 file differs from the indexed one; rebuild the index")
        self.coverage = self.meta["coverage"]
        self.source = {"dataset": "N03", "index_format": self.meta["index_format"], "built_at": self.meta["built_at"],
                       "files": [{"prefecture_code": p, "file": f["file"], "reference_date": f["reference_date"]}
                                 for p, f in self.meta["files"].items()]}
        self._acquire_wait_s = acquire_wait_s
        self._pool: queue.Queue = queue.Queue()
        self._all: list[sqlite3.Connection] = []
        try:
            for _ in range(max(1, connections)):
                c = sqlite3.connect(f"file:{Path(index)}?mode=ro", uri=True, check_same_thread=False)
                c.execute("SELECT count(*) FROM area_rtree WHERE id = 0").fetchone()
                self._all.append(c)
                self._pool.put(c)
        except sqlite3.Error as exc:
            self.close()
            raise AdminIndexError("administrative-area index unreadable") from exc

    def close(self) -> None:
        for c in self._all:
            c.close()
        self._all.clear()

    def _failed(self, lat, lon, tol, reason: str) -> ResolvedLocation:
        return ResolvedLocation(FAILED, lat, lon, tol, self.coverage, reason=reason, source=self.source)

    @contextmanager
    def _slot(self):
        """One connection = one concurrent decision: the read, the WKB parse and the GEOS work of a point all
        happen while it is held, so the transient memory is bounded by ``connections`` whatever the number of
        calling threads (measured in Phase 4-N.2: without this bound the RSS grew with the threads)."""
        try:
            conn = self._pool.get(timeout=self._acquire_wait_s)
        except queue.Empty:
            raise ResolverBusy("no free resolver slot") from None
        try:
            yield conn
        finally:
            self._pool.put(conn)

    def _read(self, conn: sqlite3.Connection, x: float, y: float, tol: float) -> list[_Area]:
        rows = conn.execute(
            "SELECT a.prefecture_code, a.municipality_code, a.unassigned, a.prefecture_name, a.municipality_name, "
            "a.wkb FROM area_rtree r JOIN areas a ON a.id = r.id "
            "WHERE r.maxx >= ? AND r.minx <= ? AND r.maxy >= ? AND r.miny <= ? ORDER BY a.id",
            (x - tol, x + tol, y - tol, y + tol)).fetchall()
        return [_Area(p, m, bool(u), pn, mn, shapely.from_wkb(w)) for p, m, u, pn, mn, w in rows]

    def resolve(self, lat: float, lon: float) -> ResolvedLocation:
        if not all(type(v) in (int, float) and math.isfinite(v) for v in (lat, lon)) \
                or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ResolverInputError("the point is not a pair of finite numbers in range")
        x, y, tol = float(lon), float(lat), tolerance_deg(lat)
        try:
            with self._slot() as conn:
                return self._resolve(conn, lat, lon, x, y, tol)
        except ResolverBusy:
            return self._failed(lat, lon, tol, "busy")

    def _resolve(self, conn, lat, lon, x, y, tol) -> ResolvedLocation:
        try:
            boxed = self._read(conn, x, y, tol)
        except (sqlite3.Error, shapely.errors.GEOSException, ValueError, TypeError):
            return self._failed(lat, lon, tol, "read_failed")
        pt = shapely.Point(x, y)
        try:
            near = [a for a in boxed if shapely.dwithin(a.geometry, pt, tol)]
            if not near:
                status = OUTSIDE_ADMIN if self.coverage == "national" else OUTSIDE_REGISTERED
                return ResolvedLocation(status, lat, lon, tol, self.coverage, source=self.source)
            by_code: dict[str, list[_Area]] = {}
            for a in near:
                by_code.setdefault(a.municipality_code, []).append(a)
            munis = []
            for code in sorted(by_code):
                g = _local(by_code[code], x, y, tol)
                a0 = by_code[code][0]
                munis.append({"code": code, "prefecture_code": a0.prefecture_code, "unassigned": a0.unassigned,
                              "name": None if a0.unassigned else a0.municipality_name,
                              "prefecture": a0.prefecture_name, "contains_point": bool(g.contains(pt)),
                              "_edge_near": bool(shapely.dwithin(g.boundary, pt, tol))})
            prefs = sorted({a.prefecture_code for a in near})
            pref_rel = tuple({"code": p, "relation": _relation([a for a in near if a.prefecture_code == p], pt, x, y, tol)}
                             for p in prefs)
            single = len(munis) == 1 and munis[0]["contains_point"] and not munis[0]["_edge_near"]
            for m in munis:
                del m["_edge_near"]
        except (shapely.errors.GEOSException, ValueError, TypeError):
            return self._failed(lat, lon, tol, "read_failed")
        status = INSIDE if single else NEAR
        return ResolvedLocation(status, lat, lon, tol, self.coverage, pref_rel, tuple(munis), source=self.source,
                                _near=tuple(near))

    def region_relation(self, loc: ResolvedLocation, prefecture_set: Iterable[str]) -> str | None:
        """``inside`` / ``boundary`` / None for the union of the prefectures in the set (the providers'
        ``_Region.relation``). Raises ValueError for a failed location (never guessed) and ResolverBusy when
        no slot is free (the GEOS work is bounded by the same slots as ``resolve``)."""
        if not loc.complete:
            raise ValueError("the location was not resolved")
        s = set(prefecture_set)
        areas = [a for a in loc._near if a.prefecture_code in s]
        if not areas:
            return None
        with self._slot():
            return _relation(areas, shapely.Point(loc.lon, loc.lat), loc.lon, loc.lat, loc.tolerance_deg)
