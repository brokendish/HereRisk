"""Phase 4-N.2 measurement: memory and time of the Location Resolver against N03Municipalities.

    python -m hererisk.research.resolver_measure synth --template <N03 ZIP> --count 47 --out-dir DIR
        (synthetic prefectures for the growth test: the template's features shifted onto a grid, codes and
         names rewritten; measurement only, never registered as data)
    python -m hererisk.research.resolver_measure run --mode resolver|n03 --regions <regions.json>
        [--admin-index <admin.sqlite>] --points <points.jsonl> [--threads 8,32]

One mode per process (run it in a container with a memory limit). Points: JSON lines {lon, lat}
(``resolver_compare --dump-points`` or ``synth``). Research only.
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import platform
import random
import resource
import time
import zipfile
from pathlib import Path
from typing import Any


def _peak() -> int:
    v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(v if platform.system() == "Darwin" else v * 1024)


def _cur() -> int | None:
    try:
        for line in open("/proc/self/status"):
            if line.startswith("VmRSS"):
                return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


def _stats(v: list[float]) -> dict[str, float] | None:
    if not v:
        return None
    s = sorted(v)
    return {"n": len(s), "median": round(s[len(s) // 2], 4), "p95": round(s[int(0.95 * (len(s) - 1))], 4),
            "max": round(s[-1], 4)}


def synth(template: Path, count: int, out_dir: Path, points_per: int = 200) -> None:
    """``count`` synthetic prefectures 01.. from one N03 ZIP (shifted 1.0 deg in lon, 0.7 deg in lat on a grid)."""
    import re
    with zipfile.ZipFile(template) as z:
        name = next(n for n in z.namelist() if re.search(r"N03-\d{8}_\d{2}\.geojson\Z", n))
        doc = json.loads(z.read(name))
    src_pref = re.search(r"_(\d{2})\.geojson\Z", name).group(1)
    out_dir.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(20261103)
    regions, pts = [], []
    for k in range(count):
        pref = f"{k + 1:02d}"
        dx, dy = (k % 8) * 1.0, (k // 8) * 0.7

        def shift(c):
            return [shift(v) for v in c] if isinstance(c[0], list) else [c[0] + dx, c[1] + dy]
        feats = []
        for f in doc["features"]:
            p = dict(f["properties"])
            p["N03_007"] = pref + p["N03_007"][2:]
            p["N03_001"] = f"合成{pref}"
            feats.append({"type": "Feature", "properties": p,
                          "geometry": {"type": f["geometry"]["type"], "coordinates": shift(f["geometry"]["coordinates"])}})
        path = out_dir / f"N03-20260101_{pref}_GML.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(f"N03-20260101_{pref}.geojson", json.dumps({"type": "FeatureCollection", "features": feats}))
        regions.append({"prefecture_code": pref, "address_isj": "unused.csv", "address_n03": path.name})
        for f in rnd.sample(feats, min(points_per, len(feats))):
            ring = f["geometry"]["coordinates"][0] if f["geometry"]["type"] == "Polygon" else f["geometry"]["coordinates"][0][0]
            x, y = ring[rnd.randrange(len(ring) - 1)]
            pts.append({"lon": x + rnd.uniform(-0.002, 0.002), "lat": y + rnd.uniform(-0.002, 0.002), "kind": f"synth_{pref}"})
    for n in sorted({1, 10, count}):
        (out_dir / f"regions-{n}.json").write_text(json.dumps({"regions": regions[:n]}), encoding="utf-8")
        with open(out_dir / f"points-{n}.jsonl", "w", encoding="utf-8") as fh:
            for p in pts:
                if int(p["kind"][-2:]) <= n:
                    fh.write(json.dumps(p) + "\n")
    print(json.dumps({"template_prefecture": src_pref, "features_per_prefecture": len(doc["features"]), "count": count}))


def run(mode: str, regions: Path, admin_index: Path | None, points: Path, threads: list[int]) -> dict[str, Any]:
    pts = [json.loads(line) for line in points.read_text("utf-8").splitlines() if line.strip()]
    rss0 = _cur()
    t0 = time.perf_counter()
    if mode == "resolver":
        from hererisk.location.resolver import LocationResolver
        res = LocationResolver(admin_index, regions_file=regions)

        def call(lat, lon):
            v = res.resolve(lat, lon).view()
            return "failed:" + v.get("reason", "") if v["status"] == "failed" else json.dumps(v, sort_keys=True)
    else:
        from hererisk.location.address_regions import load_regions
        from hererisk.location.n03_municipality import N03Municipalities
        n03 = N03Municipalities([(r["prefecture_code"], r["address_n03"]) for r in load_regions(regions)])
        call = lambda lat, lon: json.dumps(n03.locate(lat, lon))   # noqa: E731
    start_s = time.perf_counter() - t0
    rss1 = _cur()
    ms = []
    first = []
    for p in pts:
        t = time.perf_counter()
        first.append(hash(call(p["lat"], p["lon"])))      # a hash only: the results are not kept
        ms.append((time.perf_counter() - t) * 1000)
    rss2 = _cur()
    par = {}
    for n in threads:
        t = time.perf_counter()
        with cf.ThreadPoolExecutor(max_workers=n) as pool:
            raw = pool.map(lambda p: call(p["lat"], p["lon"]), pts)
            again, failed = [], {}
            for r in raw:
                if r.startswith("failed:"):
                    failed[r] = failed.get(r, 0) + 1
                again.append(hash(r))
        par[str(n)] = {"identical": sum(1 for a, b in zip(first, again) if a == b), "points": len(pts), "failed": failed,
                       "seconds": round(time.perf_counter() - t, 2), "rss_after_bytes": _cur()}
    return {"mode": mode, "points": len(pts), "start_s": round(start_s, 3), "rss_before_bytes": rss0,
            "rss_after_start_bytes": rss1, "rss_after_search_bytes": rss2, "peak_rss_bytes": _peak(),
            "search_ms": _stats(ms), "parallel": par, "platform": platform.platform()}


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="python -m hererisk.research.resolver_measure")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("synth")
    s.add_argument("--template", type=Path, required=True)
    s.add_argument("--count", type=int, default=47)
    s.add_argument("--out-dir", type=Path, required=True)
    r = sub.add_parser("run")
    r.add_argument("--mode", choices=("resolver", "n03"), required=True)
    r.add_argument("--regions", type=Path, required=True)
    r.add_argument("--admin-index", type=Path)
    r.add_argument("--points", type=Path, required=True)
    r.add_argument("--threads", default="8,32")
    args = p.parse_args(argv)
    if args.cmd == "synth":
        synth(args.template, args.count, args.out_dir)
        return 0
    print(json.dumps(run(args.mode, args.regions, args.admin_index, args.points,
                         [int(t) for t in args.threads.split(",") if t])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
