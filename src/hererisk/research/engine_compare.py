"""Phase 4-K check: the shared Polygon Engine's SQLite reader against the existing diagnosis and Phase 4-J.

    python -m hererisk.research.engine_compare --diag-index <diag.sqlite> --study <polygon-point-study-real-* dir>
        [--report-dir DIR]

Per invalid (component, point) pair of the Phase 4-J study (the Tokyo flood fixed set, generated points):

* ``hererisk.common.polygon.sqlite_reader.Reader.point_facts`` (chunk by chunk from the index)
* ``hererisk.flood.diag.DiagIndex.winding`` (the existing normalised winding and crossings)
* the Phase 4-J facts computed from the original geometry (``raw_winding_per_ring``, H, H2, boundary)

Research only (read only; nothing is adopted).
"""

from __future__ import annotations

import json
import platform
import resource
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hererisk.common.polygon.sqlite_reader import Reader
from hererisk.flood.diag import DiagIndex, _dist


def _rss() -> int:
    v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(v if platform.system() == "Darwin" else v * 1024)


def run(diag_index: Path, study: Path, log=lambda m: None) -> dict[str, Any]:
    pairs = [json.loads(line) for line in (Path(study) / "pairs.jsonl").read_text("utf-8").splitlines() if line.strip()]
    pairs = [p for p in pairs if not p["control"]]
    rss0 = _rss()
    reader = Reader(diag_index)
    diag = DiagIndex(diag_index)
    rss1 = _rss()
    checks, statuses = Counter(), Counter()
    ms, chunks, segs = [], [], []
    for n, p in enumerate(pairs):
        lat, lon, ref = p["lat"], p["lon"], p["zone_ref"]
        t0 = time.perf_counter()
        f = reader.point_facts(ref, lat, lon)
        ms.append((time.perf_counter() - t0) * 1000)
        statuses[f["status"]] += 1
        if not f["complete"]:
            checks[f"NOT_COMPLETE_{f['status'].upper()}"] += 1
            continue
        chunks.append(f["chunks_read"])
        segs.append(f["ray_read"]["segments"])
        old = p["facts"]
        research_on = p["study"]["class"] == "on_boundary"
        checks["on_boundary_same_as_phase_4j" if f["on_boundary"] == research_on else "ON_BOUNDARY_DIFFERS"] += 1
        if f["on_boundary"]:
            continue
        w, crossings = diag.winding(diag.by_refs([ref])[0], lat, lon)
        checks["equals_diag_index_winding" if (f["winding_normalised"], f["parity_inside"]) == (w, bool(crossings % 2))
               else "DIFFERS_FROM_DIAG_INDEX"] += 1
        checks["raw_per_ring_equals_phase_4j" if f["raw_winding_per_ring"] == old["raw_winding_per_ring"]
               else "RAW_PER_RING_DIFFERS"] += 1
        checks["h_h2_equal_phase_4j" if (f["h_winding_parity"], f["h2_per_ring_unit"]) ==
               (old["h_winding_parity"], old["h2_per_ring_unit"]) else "H_H2_DIFFER"] += 1
        checks["h2_true" if f["h2_per_ring_unit"] else "h2_false"] += 1
        if (n + 1) % 500 == 0:
            log(f"engine compare: {n + 1}/{len(pairs)}")
    reader.close()
    return {"started_at": datetime.now(timezone.utc).isoformat(), "pairs": len(pairs), "status": dict(statuses),
            "checks": dict(checks), "failed": sorted(k for k in checks if k.isupper()),
            "timing_ms_per_pair": _dist(ms), "chunks_read": _dist(chunks), "ray_segments_read": _dist(segs),
            "memory": {"rss_before_open_bytes": rss0, "rss_after_open_bytes": rss1, "peak_rss_bytes": _rss()},
            "diag_index_bytes": Path(diag_index).stat().st_size,
            "program": {"python": platform.python_version(), "machine": platform.machine(), "system": platform.system()}}


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m hererisk.research.engine_compare")
    ap.add_argument("--diag-index", type=Path, required=True)
    ap.add_argument("--study", type=Path, required=True)
    ap.add_argument("--report-dir", type=Path)
    args = ap.parse_args(argv)
    rep = run(args.diag_index, args.study, log=lambda m: sys.stderr.write(m + "\n"))
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    if args.report_dir:
        out = Path(args.report_dir) / f"polygon-engine-compare-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        out.mkdir(parents=True, exist_ok=False)
        (out / "summary.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"report: {out}")
    return 1 if rep["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
