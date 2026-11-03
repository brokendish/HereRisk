"""Local tsunami search index (Phase 4-M): built once from the registered A40 ZIPs, read by the
Location API tsunami provider. A local verification artifact, not a Publish / Dataset Registry entry.

    python -m hererisk.tsunami build --regions <regions.json> --output <index.sqlite>
    python -m hererisk.tsunami trace --index <index.sqlite> --zone-ref <loc-tz-...>
    python -m hererisk.tsunami verify ...   (hererisk.tsunami.verify: independent check against the GML)

Build (``build_index``), per registered source and file:

1. SHA-256 of the ZIP (and whether it equals the Official Source Ledger's download record); product
   specification edition from the metadata
2. every feature of the GeoJSON is read (``hererisk.tsunami.a40``); none is skipped, none is selected
   by region (every feature is indexed)
3. each component polygon is classified by the shared ``hererisk.common.polygon.validity``
   (``valid`` / ``invalid_geometry`` / ``feature_invalid_component`` / ``unverified``)
4. nothing is repaired; geometries are stored as parsed (WKB); ``A40_003`` is stored as in the source
5. the file is written under a temporary name and renamed only when complete (``meta.status``)

Limitations (in the index and the API section): one validator (GEOS); coordinates read as JSON floats;
no Source Fidelity / Integrated Validate records; no assessed extent in the source.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import shapely

from hererisk.common.polygon import validity
from hererisk.tsunami import a40
from hererisk.tsunami.errors import A40FormatError, TsunamiIndexError
from hererisk.tsunami.registry import DEFAULT_LEDGER, load_ledger, load_tsunami_sources, registration_view

INDEX_FORMAT = "hererisk-tsunami-index-v0.1"
LIMITATIONS = ["single_geometry_validator", "coordinates_as_float", "no_integrated_validate_record",
               "no_assessed_extent_in_source"]

SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE components (zone_ref TEXT PRIMARY KEY, source_id TEXT NOT NULL, file_name TEXT NOT NULL,
  zip_sha256 TEXT NOT NULL, member TEXT NOT NULL, feature_index INTEGER NOT NULL, fid INTEGER NOT NULL,
  polygon_index INTEGER NOT NULL, validity TEXT NOT NULL, detail TEXT, kind TEXT,
  minx REAL NOT NULL, miny REAL NOT NULL, maxx REAL NOT NULL, maxy REAL NOT NULL,
  prefecture_name TEXT NOT NULL, prefecture_code TEXT NOT NULL, depth_label TEXT NOT NULL, wkb BLOB NOT NULL);
"""


def zone_ref(zip_sha256: str, member: str, feature_index: int, polygon_index: int) -> str:
    """Content-derived, per component; another file, feature or component gives another reference."""
    doc = {"domain": "hererisk-tsunami-zone-ref-local-v0", "polygon_index": polygon_index,
           "record_key": {"feature_index": feature_index, "zip_member": member, "zip_sha256": zip_sha256}}
    raw = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return "loc-tz-" + hashlib.sha256(raw).hexdigest()[:20]


def _ledger_sha(ledger: dict[str, Any], entry: str) -> str | None:
    return (((ledger.get(entry) or {}).get("availability") or {}).get("download_verification") or {}).get("sha256")


def build_index(regions_file: Path, output: Path, *, ledger_file: Path = DEFAULT_LEDGER, log=None) -> dict[str, Any]:
    log = log or (lambda msg: None)
    sources = load_tsunami_sources(regions_file)
    if not sources:
        raise TsunamiIndexError("the regions file has no tsunami_sources")
    ledger = load_ledger(ledger_file)
    output = Path(output)
    tmp = output.with_name(output.name + f".tmp-{os.getpid()}")
    if tmp.exists():
        raise TsunamiIndexError("a temporary index file already exists")
    db = sqlite3.connect(tmp)
    try:
        db.executescript(SCHEMA)
        summary: dict[str, Any] = {"sources": []}
        files_meta = {}
        for src in sources:
            s_sum = {"source_id": src["source_id"], "features": 0, "components": 0, "validity": Counter(),
                     "depth_labels": Counter(), "not_valid_by_depth_label": Counter(), "multipolygon_features": 0,
                     "holes": 0}
            for f in src["files"]:
                log(f"{src['source_id']}: {f['file_name']}")
                sha = a40.sha256_file(f["path"])
                z, m = a40.open_zip(f["path"])
                with z:
                    edition = a40.spec_edition(z, m)
                    _build_file(db, z, m, src, f, sha, s_sum)
                files_meta[f["file_name"]] = {"sha256": sha, "member": m["geojson"], "spec_edition": edition,
                                              "ledger_entry": f["ledger_entry"],
                                              "ledger_sha256_match": _ledger_sha(ledger, f["ledger_entry"]) == sha}
            summary["sources"].append({k: dict(v) if isinstance(v, Counter) else v for k, v in s_sum.items()})
        meta = {"index_format": INDEX_FORMAT,
                "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "registration": [registration_view(s) for s in sources], "files": files_meta,
                "validator": validity.VALIDATOR, "limitations": LIMITATIONS, "summary": summary}
        n = db.execute("SELECT count(*) FROM components").fetchone()[0]
        if n != sum(s["components"] for s in summary["sources"]):
            raise TsunamiIndexError("component rows do not match the count read")
        meta["status"] = "complete"                     # the index is only renamed into place when complete
        db.executemany("INSERT INTO meta VALUES (?, ?)", [(k, json.dumps(v, ensure_ascii=False)) for k, v in meta.items()])
        db.commit()
    except BaseException:
        db.close()
        tmp.unlink(missing_ok=True)
        raise
    db.close()
    os.replace(tmp, output)
    return summary


def _build_file(db, z, m, src, f, sha, s_sum) -> None:
    rows = []
    for feat in a40.read_features(z, m, src["prefecture_code"]):
        try:
            comps = validity.classify_components(feat["polygons"])
        except validity.GeometryInputError as exc:
            raise TsunamiIndexError(f"a feature geometry is refused ({exc})") from exc
        s_sum["features"] += 1
        s_sum["multipolygon_features"] += len(comps) > 1
        s_sum["depth_labels"][feat["depth_label"]] += 1
        for c in comps:
            s_sum["components"] += 1
            s_sum["validity"][c.validity] += 1
            s_sum["holes"] += len(c.geometry.interiors)
            if not c.usable:
                s_sum["not_valid_by_depth_label"][feat["depth_label"]] += 1
            rows.append((zone_ref(sha, m["geojson"], feat["feature_index"], c.polygon_index), src["source_id"],
                         f["file_name"], sha, m["geojson"], feat["feature_index"], feat["fid"], c.polygon_index,
                         c.validity, c.detail, c.kind, *c.geometry.bounds, feat["prefecture_name"],
                         feat["prefecture_code"], feat["depth_label"], shapely.to_wkb(c.geometry)))
        if len(rows) >= 2000:
            db.executemany("INSERT INTO components VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            rows.clear()
    if rows:
        db.executemany("INSERT INTO components VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)


def read_meta(index: Path) -> dict[str, Any]:
    try:
        db = sqlite3.connect(f"file:{Path(index)}?mode=ro", uri=True)
        try:
            meta = {k: json.loads(v) for k, v in db.execute("SELECT key, value FROM meta")}
        finally:
            db.close()
    except (sqlite3.Error, ValueError) as exc:
        raise TsunamiIndexError("tsunami index unreadable") from exc
    if meta.get("index_format") != INDEX_FORMAT:
        raise TsunamiIndexError("tsunami index format not supported")
    if meta.get("status") != "complete":
        raise TsunamiIndexError("tsunami index incomplete")
    return meta


def trace(index: Path, ref: str) -> dict[str, Any] | None:
    """Internal trace of one zone_ref back to the official file (never part of an API response)."""
    db = sqlite3.connect(f"file:{Path(index)}?mode=ro", uri=True)
    try:
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT zone_ref, source_id, file_name, zip_sha256, member, feature_index, fid, polygon_index, "
                         "validity, detail, kind, prefecture_name, prefecture_code, depth_label, minx, miny, maxx, maxy "
                         "FROM components WHERE zone_ref = ?", (ref,)).fetchone()
    finally:
        db.close()
    if row is None:
        return None
    out = dict(row)
    out["bbox"] = [out.pop(k) for k in ("minx", "miny", "maxx", "maxy")]
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["verify"]:
        from hererisk.tsunami.verify import main as verify_main   # kept apart from the builder on purpose
        return verify_main(argv[1:])
    parser = argparse.ArgumentParser(prog="python -m hererisk.tsunami")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="build the local tsunami search index from the registered A40 ZIPs")
    b.add_argument("--regions", type=Path, required=True)
    b.add_argument("--output", type=Path, required=True)
    t = sub.add_parser("trace", help="internal trace of a zone_ref to the official file")
    t.add_argument("--index", type=Path, required=True)
    t.add_argument("--zone-ref", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "trace":
        out = trace(args.index, args.zone_ref)
        print(json.dumps(out, ensure_ascii=False, indent=1) if out else "not found")
        return 0 if out else 1
    try:
        summary = build_index(args.regions, args.output, log=lambda m: sys.stderr.write(f"tsunami index: {m}\n"))
    except (TsunamiIndexError, A40FormatError, ValueError, OSError) as exc:
        sys.stderr.write(f"tsunami index: not built ({exc})\n")
        return 3
    print(json.dumps({"status": "SUCCESS", "summary": summary}, ensure_ascii=False))
    return 0
