"""Automated check of the Phase 4-E Shadow diagnosis (generated test points only).

    python -m hererisk.flood shadow-verify --regions <regions.json> --flood-index <index.sqlite>
        --diag-index <diag.sqlite> --baseline <4-C report dir> [--cases-dir <4-D compare dir>]
        [--threads N] [--report-dir DIR]

Points: the fixed-seed points of a Phase 4-C report (generated, not user positions). For each point:

1. the official flood section with the plain Flood Provider and through ``ShadowFloodProvider`` must
   be identical (JSON); the diagnosed zone_refs must be exactly the Provider's ``unknowns``
2. the diagnosis records (``DiagIndex.diagnose``: classification, reason codes, decided radius,
   duration) and, offline, whether a candidate agrees with the Phase 4-C ``make_valid`` reading
3. the Phase 4-D cases (``--cases-dir``): case A (make_valid vs even-odd, 15 pairs) and case B (decided,
   then a defect at a larger radius, 521 pairs) must all be ``undetermined`` with their reason codes
4. the same points from ``--threads`` threads at once through one Shadow provider: identical answers,
   no errors; timings without and with Shadow

Exit: 0 all checks hold, 1 a check failed, 2 bad arguments, 3 the inputs were refused.
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hererisk.flood.adoption import ADOPTION_VERSION, CANDIDATE, UNDETERMINED
from hererisk.flood.diag import DiagIndex, _baseline, _dist, _rss_bytes
from hererisk.flood.errors import DiagIndexError
from hererisk.flood.settings import load_settings, radii as setting_radii


def _cases(cases_dir: Path | None) -> dict[str, set[tuple[float, float, str]]]:
    if cases_dir is None:
        return {}
    out = {}
    for tag, name in (("A", "cases-a-make_valid-vs-even_odd.json"), ("B", "cases-b-radius-dependence.json")):
        out[tag] = {(c["lat"], c["lon"], c["zone_ref"]) for c in json.loads((Path(cases_dir) / name).read_text("utf-8"))}
    return out


def run(regions: Path, flood_index: Path, diag_index: Path, baseline: Path, *, cases_dir: Path | None = None,
        settings: Path | None = None, threads: int = 8, log=lambda m: None) -> dict[str, Any]:
    from hererisk.location.flood_provider import FloodProvider
    from hererisk.location.flood_shadow import ShadowFloodProvider
    radii = setting_radii(load_settings(settings)["local_analysis"])
    summary, points = _baseline(baseline)
    if setting_radii(summary["inputs"]["local_analysis"]) != radii:
        raise ValueError("the radii differ from the baseline report's settings")
    cases = _cases(cases_dir)
    provider = FloodProvider(regions, flood_index)
    rss_provider = _rss_bytes()
    shadow = ShadowFloodProvider(provider, diag_index, flood_index, radii)
    rss_shadow = _rss_bytes()
    diag = DiagIndex(diag_index, flood_index=flood_index)          # the records below (synchronous)
    checks = Counter()
    records, cls, reasons, by_source = [], Counter(), Counter(), Counter()
    case_result = {t: Counter() for t in cases}
    mv = Counter()
    t_plain, t_shadow, t_diag = [], [], []
    for n, pt in enumerate(points):
        lat, lon = pt["lat"], pt["lon"]
        t0 = time.perf_counter()
        plain = provider.lookup(lat, lon)
        t1 = time.perf_counter()
        shadowed = shadow.lookup(lat, lon)
        t2 = time.perf_counter()
        t_plain.append((t1 - t0) * 1000)
        t_shadow.append((t2 - t1) * 1000)
        checks["official_identical" if json.dumps(plain, sort_keys=True) == json.dumps(shadowed, sort_keys=True)
               else "OFFICIAL_DIFFERS"] += 1
        targets = [(s["source_id"], s["service_region_relation"], [u["zone_ref"] for u in s["unknowns"]])
                   for s in plain.get("sources") or [] if s.get("unknowns")]
        base = {p["zone_ref"]: p for p in pt["pairs"] if not p["control"]}
        unknown_refs = {r for _, _, refs in targets for r in refs}
        checks["unknowns_equal_phase_4c_pending" if unknown_refs == set(base) else "UNKNOWNS_DIFFER_FROM_4C"] += 1
        t0 = time.perf_counter()
        recs = diag.diagnose(lat, lon, radii, targets, identity_ok=True)
        t_diag.append((time.perf_counter() - t0) * 1000)
        checks["diagnosed_refs_equal_unknowns" if {r["zone_ref"] for r in recs} == unknown_refs
               else "DIAGNOSED_REFS_DIFFER"] += 1
        for r in recs:
            cls[r["classification"]] += 1
            by_source[f"{r['source_id']} {r['classification']}"] += 1
            reasons.update(f"{r['classification']}:{c}" for c in r["reasons"])
            reads = (base.get(r["zone_ref"]) or {}).get("reads") or {}
            if r["classification"] == CANDIDATE and reads:
                mv["candidate make_valid " + ("agrees" if reads["make_valid"] == (r["relation"] == "inside")
                                              else "DISAGREES")] += 1
                mv["candidate exterior_only " + ("agrees" if reads["exterior_only"] == (r["relation"] == "inside")
                                                 else "differs (holes ignored)")] += 1
            key = (lat, lon, r["zone_ref"])
            for tag, keys in cases.items():
                if key in keys:
                    case_result[tag][f"{r['classification']}:{','.join(r['reasons'])}"] += 1
            records.append({"category": pt["category"], "lat": lat, "lon": lon, **r})
        if (n + 1) % 100 == 0:
            log(f"shadow verify: {n + 1}/{len(points)} points")
    shadow.drain(30)
    # concurrency: one Shadow provider, many threads, the same points
    want = {i: json.dumps(provider.lookup(p["lat"], p["lon"]), sort_keys=True) for i, p in enumerate(points)}
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=threads) as pool:
        got = list(pool.map(lambda ip: (ip[0], json.dumps(shadow.lookup(ip[1]["lat"], ip[1]["lon"]), sort_keys=True)),
                            enumerate(points)))
    parallel_s = time.perf_counter() - t0
    checks["parallel_identical" if all(want[i] == g for i, g in got) else "PARALLEL_DIFFERS"] += len(got)
    shadow.drain(60)
    stats = shadow.stats()
    if stats["errors"]:
        checks["SHADOW_ERRORS"] += sum(stats["errors"].values())
    case_ok = {}
    for tag, c in case_result.items():
        total = sum(c.values())
        want_n = len(cases[tag])
        case_ok[tag] = {"pairs": total, "expected_pairs": want_n,
                        "all_undetermined": all(k.startswith(UNDETERMINED + ":") for k in c),
                        "by_class_and_reasons": dict(c)}
        if total != want_n or not case_ok[tag]["all_undetermined"]:
            checks[f"CASE_{tag}_NOT_REPRODUCED"] += 1
    if mv.get("candidate make_valid DISAGREES"):
        checks["CANDIDATE_MAKE_VALID_DISAGREES"] += mv["candidate make_valid DISAGREES"]
    return {"adoption_version": ADOPTION_VERSION, "method": diag.meta["method"],
            "started_at": datetime.now(timezone.utc).isoformat(), "radii_m": radii,
            "inputs": {"baseline": str(baseline), "cases_dir": None if cases_dir is None else str(cases_dir),
                       "points": len(points), "threads": threads},
            "checks": dict(checks), "failed": sorted(k for k in checks if k.isupper()),
            "classification": dict(cls), "by_source": dict(sorted(by_source.items())),
            "reasons": dict(reasons.most_common()), "offline_make_valid": dict(mv), "cases": case_ok,
            "timing_ms": {"official_plain": _dist(t_plain), "official_through_shadow": _dist(t_shadow),
                          "diagnosis_per_point": _dist(t_diag), "shadow_thread": stats["duration_ms"],
                          "parallel_seconds": round(parallel_s, 2)},
            "memory": {"rss_after_provider_bytes": rss_provider, "rss_after_shadow_open_bytes": rss_shadow,
                       "peak_rss_bytes": _rss_bytes(), "diag_index_bytes": Path(diag_index).stat().st_size},
            "shadow_stats": stats, "records": records}


def main(argv: list[str]) -> int:
    import argparse
    from hererisk.flood.settings import FloodSettingsError
    p = argparse.ArgumentParser(prog="python -m hererisk.flood shadow-verify")
    p.add_argument("--regions", type=Path, required=True)
    p.add_argument("--flood-index", type=Path, required=True)
    p.add_argument("--diag-index", type=Path, required=True)
    p.add_argument("--baseline", type=Path, required=True, help="a flood-local-analysis-* report directory")
    p.add_argument("--cases-dir", type=Path, help="a flood-diag-compare-* report directory (cases A / B)")
    p.add_argument("--settings", type=Path)
    p.add_argument("--threads", type=int, default=8)
    p.add_argument("--report-dir", type=Path)
    args = p.parse_args(argv)
    try:
        rep = run(args.regions, args.flood_index, args.diag_index, args.baseline, cases_dir=args.cases_dir,
                  settings=args.settings, threads=args.threads, log=lambda m: sys.stderr.write(m + "\n"))
    except FloodSettingsError as exc:
        sys.stderr.write(f"flood shadow-verify: {exc}\n")
        return 2
    except DiagIndexError as exc:
        sys.stderr.write(f"flood shadow-verify: {exc}\n")
        return 3
    except Exception as exc:    # noqa: BLE001
        sys.stderr.write(f"flood shadow-verify: ERROR ({type(exc).__name__}: {exc})\n")
        return 3
    print(json.dumps({k: v for k, v in rep.items() if k != "records"}, ensure_ascii=False, indent=1))
    if args.report_dir:
        out = Path(args.report_dir) / f"flood-shadow-verify-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        out.mkdir(parents=True, exist_ok=False)
        (out / "summary.json").write_text(json.dumps({k: v for k, v in rep.items() if k != "records"},
                                                     ensure_ascii=False, indent=1), encoding="utf-8")
        with open(out / "records.jsonl", "w", encoding="utf-8") as f:   # generated test points only
            for r in rep["records"]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"report: {out}")
    return 1 if rep["failed"] else 0
