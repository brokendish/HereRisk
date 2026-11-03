"""N03 administrative-area index for the Location Resolver (Phase 4-N.2).

    python -m hererisk.location.admin_index build --regions <regions.json> --output <admin.sqlite>
    python -m hererisk.location.admin_index resolve --index <admin.sqlite> --regions <regions.json> --point LAT,LON

Build (``build_index``): every registered prefecture's N03 ZIP is read with the existing reader
(``n03_municipality._read_file``: one GeoJSON member, 5-digit ``N03_007`` in the file's prefecture, a
polygon per feature) and every feature is stored **as it is** (WKB of the parsed geometry, its exact
bounding box and an R-tree entry). Features of one municipality are not merged, nothing is repaired or
simplified. The SHA-256 of each ZIP, the N03 reference date and the registration are recorded. The file
is written under a temporary name and renamed only when complete (``meta.status``); a failed build
leaves an existing index untouched.

A local verification artifact, not a Publish / Dataset Registry entry.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import shapely

from hererisk.location.address_provider import AddressDataError
from hererisk.location.address_regions import load_regions
from hererisk.location.n03_municipality import UNASSIGNED_CODE_SUFFIX, _read_file

INDEX_FORMAT = "hererisk-admin-index-v0.1"
PREFECTURE_CODES = tuple(f"{i:02d}" for i in range(1, 48))      # JIS X 0401: "national" = all of them

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE areas (id INTEGER PRIMARY KEY, prefecture_code TEXT NOT NULL, municipality_code TEXT NOT NULL,
  feature_index INTEGER NOT NULL, unassigned INTEGER NOT NULL, prefecture_name TEXT NOT NULL,
  municipality_name TEXT NOT NULL, minx REAL NOT NULL, miny REAL NOT NULL, maxx REAL NOT NULL, maxy REAL NOT NULL,
  vertices INTEGER NOT NULL, wkb BLOB NOT NULL);
CREATE VIRTUAL TABLE area_rtree USING rtree(id, minx, maxx, miny, maxy);
"""


class AdminIndexError(AddressDataError):
    """The administrative-area index is missing, incomplete or does not match. Fixed messages."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def registration(regions_file: Path) -> list[dict[str, Any]]:
    """[{prefecture_code, path}] of the regions file, in file order."""
    return [{"prefecture_code": r["prefecture_code"], "path": Path(r["address_n03"])} for r in load_regions(regions_file)]


def build_index(regions_file: Path, output: Path, *, log=None) -> dict[str, Any]:
    log = log or (lambda msg: None)
    regs = registration(regions_file)
    output = Path(output)
    tmp = output.with_name(output.name + f".tmp-{os.getpid()}")
    if tmp.exists():
        raise AdminIndexError("a temporary index file already exists")
    db = sqlite3.connect(tmp)
    try:
        db.executescript(SCHEMA)
        files, n = {}, 0
        for reg in regs:
            log(f"N03 {reg['prefecture_code']}")
            meta, items = _read_file(reg["path"], reg["prefecture_code"])
            rows = []
            for fi, (code, geom, names) in enumerate(items):
                n += 1
                rows.append((n, reg["prefecture_code"], code, fi, int(code.endswith(UNASSIGNED_CODE_SUFFIX)),
                             names["prefecture"], names["municipality"], *geom.bounds,
                             int(shapely.get_num_coordinates(geom)), shapely.to_wkb(geom)))
            db.executemany("INSERT INTO areas VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            db.executemany("INSERT INTO area_rtree VALUES (?,?,?,?,?)", [(r[0], r[7], r[9], r[8], r[10]) for r in rows])
            files[reg["prefecture_code"]] = {**meta, "file_name": reg["path"].name, "sha256": sha256_file(reg["path"])}
        prefs = [r["prefecture_code"] for r in regs]
        meta = {"index_format": INDEX_FORMAT, "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "dataset": "N03", "prefectures": prefs, "files": files,
                "coverage": "national" if set(prefs) == set(PREFECTURE_CODES) else "partial",
                "features": n, "max_vertices": db.execute("SELECT max(vertices) FROM areas").fetchone()[0],
                "max_wkb_bytes": db.execute("SELECT max(length(wkb)) FROM areas").fetchone()[0]}
        if db.execute("SELECT count(*) FROM area_rtree").fetchone()[0] != n:
            raise AdminIndexError("R-tree rows do not match the areas")
        meta["status"] = "complete"                      # renamed into place only when complete
        db.executemany("INSERT INTO meta VALUES (?, ?)", [(k, json.dumps(v, ensure_ascii=False)) for k, v in meta.items()])
        db.commit()
    except BaseException:
        db.close()
        tmp.unlink(missing_ok=True)
        raise
    db.close()
    os.replace(tmp, output)
    return {k: meta[k] for k in ("prefectures", "coverage", "features", "max_vertices", "max_wkb_bytes")}


def read_meta(index: Path) -> dict[str, Any]:
    try:
        db = sqlite3.connect(f"file:{Path(index)}?mode=ro", uri=True)
        try:
            meta = {k: json.loads(v) for k, v in db.execute("SELECT key, value FROM meta")}
        finally:
            db.close()
    except (sqlite3.Error, ValueError) as exc:
        raise AdminIndexError("administrative-area index unreadable") from exc
    if meta.get("index_format") != INDEX_FORMAT:
        raise AdminIndexError("administrative-area index format not supported")
    if meta.get("status") != "complete":
        raise AdminIndexError("administrative-area index incomplete")
    return meta


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="python -m hererisk.location.admin_index")
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the N03 administrative-area index from the regions file")
    b.add_argument("--regions", type=Path, required=True)
    b.add_argument("--output", type=Path, required=True)
    r = sub.add_parser("resolve", help="resolve one point with the index (local check)")
    r.add_argument("--index", type=Path, required=True)
    r.add_argument("--regions", type=Path, required=True)
    r.add_argument("--point", required=True, help="LAT,LON")
    r.add_argument("--region", action="append", default=[], help="prefecture set for region_relation, e.g. 13,14")
    args = p.parse_args(argv)
    try:
        if args.cmd == "build":
            out = build_index(args.regions, args.output, log=lambda m: sys.stderr.write(f"admin index: {m}\n"))
            print(json.dumps({"status": "SUCCESS", **out}, ensure_ascii=False))
            return 0
        from hererisk.location.resolver import LocationResolver
        lat, lon = (float(v) for v in args.point.split(","))
        res = LocationResolver(args.index, regions_file=args.regions)
        try:
            loc = res.resolve(lat, lon)
            out = loc.view()
            out["region_relation"] = {s: res.region_relation(loc, set(s.split(","))) for s in args.region}
        finally:
            res.close()
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    except (AddressDataError, ValueError, OSError) as exc:
        sys.stderr.write(f"admin index: failed ({exc})\n")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
