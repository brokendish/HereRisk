"""Phase 4-M measurement: memory and time of the tsunami provider alone and beside the flood provider.

    python -m hererisk.research.tsunami_measure --regions <regions with flood_sources and tsunami_sources>
        --tsunami-index <t.sqlite> [--flood-index <f.sqlite>] --mode tsunami|flood|both|server
        [--baseline <flood-local-analysis-* dir>] [--sample 2000]

One mode per process (run it in a container with the memory limit to measure). ``server`` builds the
whole Location API (address + flood + tsunami) as ``location-api-tsunami`` does, without serving.
Points: the Phase 4-C flood points (mainland) and bounding-box centres of sampled tsunami components
(islands). Research only; nothing is adopted.
"""

from __future__ import annotations

import json
import os
import platform
import random
import resource
import sqlite3
import time
from pathlib import Path
from typing import Any


def _rss() -> int:
    v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(v if platform.system() == "Darwin" else v * 1024)


def _stats(ms: list[float]) -> dict[str, Any] | None:
    if not ms:
        return None
    s = sorted(ms)
    return {"n": len(s), "median_ms": round(s[len(s) // 2], 4), "p95_ms": round(s[int(0.95 * (len(s) - 1))], 4),
            "max_ms": round(s[-1], 4)}


def run(mode: str, regions: Path, tsunami_index: Path, flood_index: Path | None, baseline: Path | None,
        sample: int) -> dict[str, Any]:
    rss0 = _rss()
    t0 = time.perf_counter()
    providers: dict[str, Any] = {}
    if mode == "server":
        from hererisk.location import server
        srv = server.build_server("127.0.0.1", 0, address_regions=regions, flood_index=flood_index,
                                  tsunami_index=tsunami_index)
        lookup = lambda lat, lon: srv.location_api.handle("GET", "/api/v1/location", f"lat={lat}&lon={lon}").json()   # noqa: E731
    else:
        if mode in ("tsunami", "both"):
            from hererisk.location.tsunami_provider import TsunamiProvider
            providers["tsunami"] = TsunamiProvider(regions, tsunami_index)
        if mode in ("flood", "both"):
            from hererisk.location.flood_provider import FloodProvider
            providers["flood"] = FloodProvider(regions, flood_index)
        lookup = lambda lat, lon: {k: p.lookup(lat, lon) for k, p in providers.items()}   # noqa: E731
    start_s = time.perf_counter() - t0
    rss1 = _rss()
    pts = []
    if baseline:
        pts += [(p["lat"], p["lon"], "flood_points") for p in
                (json.loads(line) for line in (Path(baseline) / "points.jsonl").read_text("utf-8").splitlines() if line.strip())]
    db = sqlite3.connect(f"file:{tsunami_index}?mode=ro", uri=True)
    boxes = db.execute("SELECT minx, miny, maxx, maxy FROM components").fetchall()
    db.close()
    for minx, miny, maxx, maxy in random.Random(20261103).sample(boxes, min(sample, len(boxes))):
        pts.append(((miny + maxy) / 2, (minx + maxx) / 2, "tsunami_points"))
    times: dict[str, list[float]] = {}
    statuses: dict[str, int] = {}
    for lat, lon, kind in pts:
        t = time.perf_counter()
        out = lookup(lat, lon)
        times.setdefault(kind, []).append((time.perf_counter() - t) * 1000)
        sec = out["hazards"]["tsunami"] if mode == "server" else out.get("tsunami")
        if sec is not None:
            key = f"{kind}:tsunami:{sec['status']}"
            statuses[key] = statuses.get(key, 0) + 1
    return {"mode": mode, "start_s": round(start_s, 2), "rss_before_bytes": rss0, "rss_after_start_bytes": rss1,
            "peak_rss_bytes": _rss(), "tsunami_index_bytes": os.path.getsize(tsunami_index),
            "lookup": {k: _stats(v) for k, v in times.items()}, "statuses": dict(sorted(statuses.items())),
            "platform": platform.platform()}


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="python -m hererisk.research.tsunami_measure")
    p.add_argument("--regions", type=Path, required=True)
    p.add_argument("--tsunami-index", type=Path, required=True)
    p.add_argument("--flood-index", type=Path)
    p.add_argument("--mode", choices=("tsunami", "flood", "both", "server"), required=True)
    p.add_argument("--baseline", type=Path)
    p.add_argument("--sample", type=int, default=2000)
    args = p.parse_args(argv)
    print(json.dumps(run(args.mode, args.regions, args.tsunami_index, args.flood_index, args.baseline, args.sample),
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
