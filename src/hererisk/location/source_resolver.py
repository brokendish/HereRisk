"""Source Resolver (Phase 4-N.3): which registered hazard sources to search at a resolved location.

Contract: docs/api/location-resolver-contract-v0.1.md chapter 3 (SR-1..SR-9, the state table 3.4 is the
provider's). Input: a hazard id, a ``ResolvedLocation`` (``hererisk.location.resolver``) and an immutable
``SourceRegistry``. Output: a ``SourceSelection``. Nothing geometric is done here: the relation to a source's
service region is the Location Resolver's ``region_relation`` (N03, 10 m, ADR-003); no polygon, no index,
no attribute is read, nothing is merged or ranked, no assessed extent is inferred.

Registration: the small common contract is ``SourceEntry(hazard, source_id, service_prefectures, index)``.
``entries_from_registrations(hazard, sources)`` converts a hazard's own checked registration (the
``load_flood_sources`` / ``load_tsunami_sources`` output: ``source_id`` + ``service_prefectures``) without
importing the hazard package; a new hazard needs the same two fields, not a change here. ``index`` is only
what the caller knows (``None`` now: the regions file does not name indexes or generations; nothing is
guessed).

Rules (per hazard, registration order kept):

* a source is selected when one of its service prefectures is a candidate prefecture of the location;
  its relation is ``region_relation(loc, service_prefectures)`` (the union of its prefectures: a border
  inside the set is not an edge). A source is listed once, whatever the number of its prefectures
* ``missing``: candidate prefectures that no source of the hazard serves (``no_source_registered``);
  ``hazard_registered: false`` when the hazard has no source at all (a different thing from a gap at a
  border, and from an unknown assessed extent, which the source data does not state)
* ``coverage: partial`` when ``missing`` is not empty; ``region_state`` is then ``region_boundary`` (SR-8)
* a failed or busy location -> ``complete: false``, ``sources: null`` (never a selection from a guess)
* outside the registered N03 area / outside every area -> ``complete: true``, ``sources: []``; the
  location's ``coverage`` says whether "outside" can be told from "unregistered prefecture" (SR-5, SR-9)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from hererisk.location.resolver import FAILED, INSIDE, OUTSIDE_ADMIN, OUTSIDE_REGISTERED, ResolvedLocation, ResolverBusy

_HAZARD = re.compile(r"[a-z][a-z0-9_]{1,31}\Z")
_SOURCE = re.compile(r"[a-z0-9][a-z0-9-]{2,63}\Z")
_PREF = re.compile(r"(0[1-9]|[1-3]\d|4[0-7])\Z")


class SourceRegistryError(ValueError):
    """The registration given to the Source Resolver is malformed or inconsistent. Fixed messages."""


@dataclass(frozen=True)
class SourceEntry:
    hazard: str
    source_id: str
    service_prefectures: tuple[str, ...]
    index: Mapping[str, Any] | None = None       # only what the caller knows; never guessed


def entries_from_registrations(hazard: str, sources: Iterable[Mapping[str, Any]],
                               index: Mapping[str, Any] | None = None) -> list[SourceEntry]:
    """A hazard's checked registration -> common entries (``source_id`` and ``service_prefectures`` only)."""
    out = []
    for s in sources:
        try:
            out.append(SourceEntry(hazard, s["source_id"], tuple(s["service_prefectures"]),
                                   dict(index) if index else None))
        except (KeyError, TypeError) as exc:
            raise SourceRegistryError("a registration needs source_id and service_prefectures") from exc
    return out


class SourceRegistry:
    """An immutable snapshot of the registered sources, per hazard, in registration order."""

    def __init__(self, entries: Iterable[SourceEntry]) -> None:
        by_hazard: dict[str, list[SourceEntry]] = {}
        seen: set[tuple[str, str]] = set()
        for e in entries:
            if not isinstance(e, SourceEntry) or not isinstance(e.hazard, str) or not _HAZARD.match(e.hazard):
                raise SourceRegistryError("an entry needs a hazard id")
            if not isinstance(e.source_id, str) or not _SOURCE.match(e.source_id):
                raise SourceRegistryError("an entry needs a source_id")
            if (e.hazard, e.source_id) in seen:
                raise SourceRegistryError("the same source is registered twice for a hazard")
            prefs = e.service_prefectures
            if not isinstance(prefs, tuple) or not prefs or len(set(prefs)) != len(prefs) \
                    or not all(isinstance(p, str) and _PREF.match(p) for p in prefs):
                raise SourceRegistryError("service_prefectures must be distinct 2-digit JIS codes")
            seen.add((e.hazard, e.source_id))
            by_hazard.setdefault(e.hazard, []).append(e)
        self._by_hazard = {h: tuple(v) for h, v in by_hazard.items()}

    def hazards(self) -> tuple[str, ...]:
        return tuple(self._by_hazard)

    def entries(self, hazard: str) -> tuple[SourceEntry, ...]:
        return self._by_hazard.get(hazard, ())

    def prefectures(self) -> set[str]:
        return {p for es in self._by_hazard.values() for e in es for p in e.service_prefectures}


@dataclass(frozen=True)
class SourceSelection:
    hazard: str
    complete: bool
    sources: tuple[dict[str, Any], ...] | None
    missing: tuple[dict[str, str], ...]
    hazard_registered: bool
    coverage: str | None              # "full" / "partial" (missing sources); None when not complete
    region_state: str | None          # "inside" / "region_boundary"; None when nothing is selected
    location_status: str
    location_coverage: str            # the N03 registration: "national" / "partial"
    reason: str | None = None

    def view(self) -> dict[str, Any]:
        out = {"hazard": self.hazard, "complete": self.complete,
               "sources": None if self.sources is None else [dict(s) for s in self.sources],
               "missing": [dict(m) for m in self.missing], "hazard_registered": self.hazard_registered,
               "coverage": self.coverage, "region_state": self.region_state,
               "location_status": self.location_status, "location_coverage": self.location_coverage}
        if self.reason:
            out["reason"] = self.reason
        return out


class SourceResolver:
    def __init__(self, registry: SourceRegistry, resolver: Any) -> None:
        """``resolver``: the Location Resolver whose ``region_relation`` is used. Every service prefecture
        must be registered there (else a source could never be selected: SourceRegistryError)."""
        known = set(resolver.meta["prefectures"])
        if not registry.prefectures() <= known:
            raise SourceRegistryError("a service prefecture has no N03 in the Location Resolver")
        self._registry = registry
        self._resolver = resolver

    def select(self, hazard: str, loc: ResolvedLocation) -> SourceSelection:
        entries = self._registry.entries(hazard)
        base = {"hazard": hazard, "hazard_registered": bool(entries), "location_status": loc.status,
                "location_coverage": loc.coverage}
        if loc.status == FAILED:
            return SourceSelection(complete=False, sources=None, missing=(), coverage=None, region_state=None,
                                   reason=f"location_{loc.reason or 'failed'}", **base)
        if loc.status in (OUTSIDE_ADMIN, OUTSIDE_REGISTERED):
            return SourceSelection(complete=True, sources=(), missing=(), coverage="full", region_state=None, **base)
        candidates = [p["code"] for p in loc.prefectures]
        selected = []
        try:
            for e in entries:
                if not set(e.service_prefectures) & set(candidates):
                    continue
                rel = self._resolver.region_relation(loc, e.service_prefectures)
                if rel is None:
                    continue
                selected.append({"source_id": e.source_id, "service_region_relation": rel,
                                 "service_prefectures": list(e.service_prefectures),
                                 "index": dict(e.index) if e.index else None})
        except ResolverBusy:
            return SourceSelection(complete=False, sources=None, missing=(), coverage=None, region_state=None,
                                   reason="location_busy", **base)
        served = {p for e in entries for p in e.service_prefectures}
        missing = tuple({"prefecture_code": p, "reason": "no_source_registered"} for p in candidates if p not in served)
        region_state = None
        if selected:
            inside = all(s["service_region_relation"] == INSIDE for s in selected) and not missing
            region_state = "inside" if inside else "region_boundary"
        return SourceSelection(complete=True, sources=tuple(selected), missing=missing,
                               coverage="partial" if missing else "full", region_state=region_state, **base)
