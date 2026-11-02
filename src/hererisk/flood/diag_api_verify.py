"""Automated check of the Phase 4-G flood diagnostic API (generated test points only).

    python -m hererisk.flood diag-api-verify --regions <regions.json> --flood-index <index.sqlite>
        --diag-index <diag.sqlite> --baseline <4-C report dir> [--cases-dir <4-D compare dir>]
        [--threads N] [--report-dir DIR]

Points: the fixed-seed points of a Phase 4-C report (generated, not user positions). In process, through
the request -> response function of the Location API (``LocationApi.handle``), with the flood section
connected and the address / elevation sections not connected. For each point:

1. ``GET /api/v1/location`` with the diagnostic API off and on: identical; ``official_assessment`` of
   ``GET /api/v1/diagnostics/flood`` equals that ``hazards.flood`` section and the Flood Provider's answer
2. the interpretations are exactly the Provider's ``unknowns`` (source_id, zone_ref, order); their
   classes, reason codes and relations equal ``DiagIndex.diagnose`` (Phase 4-E); every reason code is
   known to the catalog (Phase 4-F); no depth except for a candidate read as inside, and then the source's
3. the Phase 4-D cases (``--cases-dir``): none is a candidate
4. the same points from ``--threads`` threads, and from 4x as many: identical answers or an explicit
   ``busy`` (counted); timings and memory

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

from hererisk.flood.adoption import ADOPTION_VERSION, CANDIDATE
from hererisk.flood.diag import DiagIndex, _baseline, _dist, _rss_bytes
from hererisk.flood.errors import DiagIndexError
from hererisk.flood.settings import load_settings, radii as setting_radii
from hererisk.flood.shadow_verify import _cases

BANNED = ("安全", "浸水しません", "区域外です", "該当しません")


def _strip(doc: dict[str, Any]) -> str:
    return json.dumps({k: v for k, v in doc.items() if k != "evaluated_at"}, sort_keys=True, ensure_ascii=False)


def run(regions: Path, flood_index: Path, diag_index: Path, baseline: Path, *, cases_dir: Path | None = None,
        settings: Path | None = None, threads: int = 8, log=lambda m: None) -> dict[str, Any]:
    from hererisk.location.api import FLOOD_DIAGNOSIS_PATH, PATH, LocationApi
    from hererisk.location.flood_diagnostics import MAX_TARGETS, WORKERS, FloodDiagnosisApi
    from hererisk.location.flood_provider import FloodProvider
    from hererisk.location.orchestrator import Orchestrator
    from hererisk.location.providers import default_providers
    radii = setting_radii(load_settings(settings)["local_analysis"])
    summary, points = _baseline(baseline)
    if setting_radii(summary["inputs"]["local_analysis"]) != radii:
        raise ValueError("the radii differ from the baseline report's settings")
    cases = _cases(cases_dir)
    rss0 = _rss_bytes()
    provider = FloodProvider(regions, flood_index)
    rss_provider = _rss_bytes()
    fd = FloodDiagnosisApi(provider, diag_index, flood_index, radii)
    rss_api = _rss_bytes()
    orchestrator = Orchestrator({**default_providers(), "flood": provider}, mode="local", allow_synthetic=False)
    off, on = LocationApi(orchestrator), LocationApi(orchestrator, flood_diagnosis=fd.lookup)
    diag = DiagIndex(diag_index, flood_index=flood_index)            # Phase 4-E records (reference)
    checks, kinds, statuses, reasons, case_result = Counter(), Counter(), Counter(), Counter(), Counter()
    records, t_loc, t_api, per_point_targets = [], [], [], Counter()
    sequential = {}
    for n, pt in enumerate(points):
        lat, lon = pt["lat"], pt["lon"]
        q = f"lat={lat!r}&lon={lon!r}"
        t0 = time.perf_counter()
        loc_on = on.handle("GET", PATH, q)
        t1 = time.perf_counter()
        r = on.handle("GET", FLOOD_DIAGNOSIS_PATH, q)
        t2 = time.perf_counter()
        t_loc.append((t1 - t0) * 1000)
        t_api.append((t2 - t1) * 1000)
        loc_off = off.handle("GET", PATH, q)
        doc = r.json()
        sequential[n] = _strip(doc)
        checks["location_identical_off_on" if _strip(loc_off.json()) == _strip(loc_on.json())
               else "LOCATION_DIFFERS"] += 1
        official = doc["official_assessment"]
        checks["official_equals_location_flood" if official == loc_off.json()["hazards"]["flood"]
               else "OFFICIAL_DIFFERS_FROM_LOCATION"] += 1
        raw = {k: v for k, v in official.items() if k != "notice"}
        checks["official_equals_provider" if json.dumps(raw, sort_keys=True) ==
               json.dumps(provider.lookup(lat, lon), sort_keys=True) else "OFFICIAL_DIFFERS_FROM_PROVIDER"] += 1
        d = doc["diagnostic"]
        statuses[d["status"]] += 1
        targets = [(s["source_id"], s["service_region_relation"], [u["zone_ref"] for u in s["unknowns"]])
                   for s in official.get("sources") or [] if s.get("unknowns")]
        want = [(s, z) for s, _, refs in targets for z in refs]
        per_point_targets[len(want)] += 1
        its = d["interpretations"]
        if its is None:
            checks[f"NOT_COMPLETE_{d['status'].upper()}"] += 1
            continue
        checks["interpreted_equal_unknowns" if [(i["source_id"], i["zone_ref"]) for i in its] == want
               else "INTERPRETED_DIFFER_FROM_UNKNOWNS"] += 1
        recs = diag.diagnose(lat, lon, radii, targets, identity_ok=True)
        same = [(i["zone_ref"], i["classification"], i["reasons"], i["relation"]) for i in its] == \
            [(x["zone_ref"], x["classification"], x["reasons"], x["relation"]) for x in recs]
        checks["phase_4e_classes_identical" if same else "PHASE_4E_CLASSES_DIFFER"] += 1
        for it, rec in zip(its, recs):
            kinds[it["interpretation"]] += 1
            reasons.update(f"{it['interpretation']}:{c}" for c in it["reasons"])
            if not all(m["known"] for m in it["reason_messages"]):
                checks["UNEXPLAINED_REASON"] += 1
            text = it["message"]["message_ja"] + it["message"]["detail_ja"]
            if any(b in text for b in BANNED):
                checks["BANNED_WORDING"] += 1
            if it["interpretation"] == "candidate_inside":
                checks["depth_is_source_class" if it["depth_class_in_source"] == rec["depth_class_in_source"]
                       else "DEPTH_NOT_SOURCE_CLASS"] += 1
            elif it["depth_class_in_source"] is not None:
                checks["DEPTH_SHOWN_WITHOUT_CANDIDATE_INSIDE"] += 1
            key = (lat, lon, it["zone_ref"])
            for tag, keys in cases.items():
                if key in keys:
                    case_result[f"{tag}:{it['classification']}"] += 1
            records.append({"category": pt["category"], "lat": lat, "lon": lon, "source_id": it["source_id"],
                            "zone_ref": it["zone_ref"], "classification": it["classification"],
                            "interpretation": it["interpretation"], "relation": it["relation"],
                            "reasons": it["reasons"], "message_ja": it["message"]["message_ja"],
                            "depth_class_code": (it["depth_class_in_source"] or {}).get("class_code")})
        if (n + 1) % 100 == 0:
            log(f"diag-api verify: {n + 1}/{len(points)} points")
    for tag, keys in cases.items():
        got = sum(v for k, v in case_result.items() if k.startswith(tag + ":"))
        if got != len(keys) or case_result.get(f"{tag}:{CANDIDATE}"):
            checks[f"CASE_{tag}_NOT_KEPT_FROM_CANDIDATE"] += 1
    concurrency = {}
    for n_threads in (threads, threads * 4):
        q = [(i, f"lat={p['lat']!r}&lon={p['lon']!r}") for i, p in enumerate(points)]
        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=n_threads) as pool:
            got = list(pool.map(lambda iq: (iq[0], on.handle("GET", FLOOD_DIAGNOSIS_PATH, iq[1]).json()), q))
        secs = time.perf_counter() - t0
        c = Counter()
        for i, doc in got:
            st = doc["diagnostic"]["status"]
            if st == "busy":
                c["busy"] += 1
            elif _strip(doc) == sequential[i]:
                c["identical"] += 1
            else:
                c["DIFFERS"] += 1
        if c["DIFFERS"]:
            checks[f"PARALLEL_{n_threads}_DIFFERS"] += c["DIFFERS"]
        concurrency[str(n_threads)] = {**c, "requests": len(got), "seconds": round(secs, 2),
                                       "requests_per_second": round(len(got) / secs, 1)}
    return {"adoption_version": ADOPTION_VERSION, "method": diag.meta["method"],
            "started_at": datetime.now(timezone.utc).isoformat(), "radii_m": radii,
            "limits": {"workers": WORKERS, "max_targets": MAX_TARGETS},
            "inputs": {"baseline": str(baseline), "cases_dir": None if cases_dir is None else str(cases_dir),
                       "points": len(points), "threads": threads},
            "checks": dict(checks), "failed": sorted(k for k in checks if k.isupper()),
            "diagnostic_status": dict(statuses), "interpretations": dict(kinds),
            "targets_per_point": {str(k): v for k, v in sorted(per_point_targets.items())},
            "reasons": dict(reasons.most_common()), "cases": dict(case_result),
            "timing_ms": {"location_api": _dist(t_loc), "diagnostic_api": _dist(t_api)},
            "concurrency": concurrency,
            "memory": {"rss_start_bytes": rss0, "rss_after_provider_bytes": rss_provider,
                       "rss_after_diagnostic_api_bytes": rss_api, "peak_rss_bytes": _rss_bytes(),
                       "diag_index_bytes": Path(diag_index).stat().st_size},
            "records": records}


def main(argv: list[str]) -> int:
    import argparse
    from hererisk.flood.settings import FloodSettingsError
    p = argparse.ArgumentParser(prog="python -m hererisk.flood diag-api-verify")
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
        sys.stderr.write(f"flood diag-api-verify: {exc}\n")
        return 2
    except DiagIndexError as exc:
        sys.stderr.write(f"flood diag-api-verify: {exc}\n")
        return 3
    except Exception as exc:    # noqa: BLE001
        sys.stderr.write(f"flood diag-api-verify: ERROR ({type(exc).__name__}: {exc})\n")
        return 3
    print(json.dumps({k: v for k, v in rep.items() if k != "records"}, ensure_ascii=False, indent=1))
    if args.report_dir:
        out = Path(args.report_dir) / f"flood-diag-api-verify-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        out.mkdir(parents=True, exist_ok=False)
        (out / "summary.json").write_text(json.dumps({k: v for k, v in rep.items() if k != "records"},
                                                     ensure_ascii=False, indent=1), encoding="utf-8")
        with open(out / "records.jsonl", "w", encoding="utf-8") as f:   # generated test points only
            for r in rep["records"]:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"report: {out}")
    return 1 if rep["failed"] else 0
