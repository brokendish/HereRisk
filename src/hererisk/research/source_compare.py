"""Phase 4-N.3 check: the Source Resolver against the current flood / tsunami providers' source choice.

    python -m hererisk.research.source_compare --regions <regions with flood_sources / tsunami_sources>
        --admin-index <admin.sqlite> --flood-index <f.sqlite> --tsunami-index <t.sqlite>
        [--baseline <flood-local-analysis-* dir>] [--per-kind 2000] [--report-dir DIR]

Reference: ``FloodProvider.lookup`` / ``TsunamiProvider.lookup`` unchanged (their ``sources`` order,
``service_region_relation``, ``region_state``, and ``not_available`` for no listed source). Points: those of
``resolver_compare`` plus the N03 micro-gaps (centre and 5 / 9.9 / 10.1 / 15 m east of it). A difference is
accepted only with a stated cause (ADR-003: ``o14_source_micro_gap``; contract SR-8:
``sr8_missing_forces_boundary``); anything else fails. Research only.
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import shapely

from hererisk.flood.registry import load_flood_sources
from hererisk.location.address_regions import load_regions
from hererisk.location.n03_municipality import _read_file
from hererisk.location.resolver import LocationResolver
from hererisk.location.source_resolver import SourceRegistry, SourceResolver, entries_from_registrations
from hererisk.research.resolver_compare import MicroGap, points
from hererisk.tsunami.registry import load_tsunami_sources


def gap_points(regions: Path) -> list[tuple]:
    pts = []
    for r in load_regions(regions):
        feats = [g for _, g, _ in _read_file(r["address_n03"], r["prefecture_code"])[1]]
        tree = shapely.STRtree(feats)
        for i, j in zip(*tree.query(feats, predicate="dwithin", distance=1e-7)):
            if i >= j:
                continue
            a, b = feats[i], feats[j]
            u = shapely.union_all([a, b])
            own = {x.wkb for f in (a, b) for q in getattr(f, "geoms", [f]) for x in q.interiors}
            for q in getattr(u, "geoms", [u]):
                for ring in q.interiors:
                    k = 111320.0 ** 2 * math.cos(math.radians(ring.coords[0][1]))
                    if ring.wkb not in own and shapely.Polygon(ring).area * k < 1.0:
                        c = shapely.Polygon(ring).centroid
                        kx = 111320.0 * math.cos(math.radians(c.y))
                        pts += [(c.x + d / kx, c.y, f"micro_gap_{d}m") for d in (0.0, 5.0, 9.9, 10.1, 15.0)]
    return pts


def run(regions: Path, admin_index: Path, flood_index: Path, tsunami_index: Path, baseline: Path | None,
        per_kind: int, log=lambda m: None) -> dict[str, Any]:
    from hererisk.location.flood_provider import FloodProvider
    from hererisk.location.tsunami_provider import TsunamiProvider
    regs = {"flood": load_flood_sources(regions), "tsunami": load_tsunami_sources(regions)}
    registry = SourceRegistry([e for h, srcs in regs.items() for e in entries_from_registrations(h, srcs)])
    res = LocationResolver(admin_index, regions_file=regions)
    sr = SourceResolver(registry, res)
    log("providers")
    providers = {"flood": FloodProvider(regions, flood_index), "tsunami": TsunamiProvider(regions, tsunami_index)}
    log("points")
    pts = points(regions, baseline, tsunami_index, per_kind) + gap_points(regions)
    log(f"{len(pts)} points")
    gaps = MicroGap(regions)
    checks, diffs, kinds = Counter(), [], Counter()
    for x, y, kind in pts:
        kinds[kind] += 1
        loc = res.resolve(y, x)
        for hazard, provider in providers.items():
            sel = sr.select(hazard, loc)
            if not sel.complete:
                checks[f"SELECTION_INCOMPLETE:{sel.reason}"] += 1
                continue
            section = provider.lookup(y, x)
            want = [] if section["status"] == "not_available" else \
                [(s["source_id"], s["service_region_relation"]) for s in section["sources"]]
            got = [(s["source_id"], s["service_region_relation"]) for s in sel.sources]
            want_state = section.get("region_state") if want else None
            same = got == want and sel.region_state == want_state
            checks[f"{hazard}:missing" if sel.missing else f"{hazard}:no_missing"] += 1
            if same:
                checks[f"{hazard}:equal"] += 1
                continue
            cls = "UNCLASSIFIED"
            if [g[0] for g in got] == [w[0] for w in want]:
                rel_diff = [(g, w) for g, w in zip(got, want) if g[1] != w[1]]
                prefs = {e.source_id: set(e.service_prefectures) for e in registry.entries(hazard)}
                if rel_diff and all(g[1] == "boundary" and w[1] == "inside" and gaps(prefs[g[0]], x, y, loc.tolerance_deg)
                                    for g, w in rel_diff):
                    cls = "o14_source_micro_gap"
                elif not rel_diff and sel.missing and sel.region_state == "region_boundary" and want_state == "inside":
                    cls = "sr8_missing_forces_boundary"
            checks[f"{hazard}:differs:{cls}"] += 1
            diffs.append({"hazard": hazard, "kind": kind, "lon": x, "lat": y, "selection": got, "provider": want,
                          "selection_state": sel.region_state, "provider_state": want_state,
                          "missing": [m["prefecture_code"] for m in sel.missing], "class": cls})
    res.close()
    return {"started_at": datetime.now(timezone.utc).isoformat(), "points": len(pts),
            "point_kinds": dict(sorted(kinds.items())), "checks": dict(sorted(checks.items())),
            "failed": sorted(k for k in checks if k.endswith("UNCLASSIFIED") or k.split(":")[0].isupper()),
            "differences": diffs[:300], "differences_total": len(diffs)}


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="python -m hererisk.research.source_compare")
    for a in ("--regions", "--admin-index", "--flood-index", "--tsunami-index"):
        p.add_argument(a, type=Path, required=True)
    p.add_argument("--baseline", type=Path)
    p.add_argument("--per-kind", type=int, default=2000)
    p.add_argument("--report-dir", type=Path)
    args = p.parse_args(argv)
    out = run(args.regions, args.admin_index, args.flood_index, args.tsunami_index, args.baseline, args.per_kind,
              log=lambda m: sys.stderr.write(f"source compare: {m}\n"))
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if args.report_dir:
        d = Path(args.report_dir) / f"source-compare-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
        d.mkdir(parents=True)
        (d / "summary.json").write_text(text + "\n", encoding="utf-8")
        sys.stderr.write(f"source compare: report {d}\n")
    print(text)
    return 1 if out["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
