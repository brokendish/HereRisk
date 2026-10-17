"""Development/test-only CLI for the pipeline Orchestrator.

Composition root: wires the common Orchestrator to API Download modules.
There is no other entry point that runs Download directly.

    python -m hererisk.cli init-fixture-root --data-root /path/to/empty-tmp-dir
    python -m hererisk.cli download --api elevation --region 13 \
        --source fixture-dem-png-tokyo --fixture tests/fixtures/elevation-fixture \
        --data-root /path/to/empty-tmp-dir
    python -m hererisk.cli pipeline --api elevation --region 13 \
        --source fixture-dem-png-tokyo --fixture tests/fixtures/elevation-fixture \
        --data-root /path/to/empty-tmp-dir

    python -m hererisk.cli elevation --run-id <run_id> --lat 35.68 --lon 139.76 \
        --zoom 14 --data-root /path/to/fixture-data-root

``elevation`` (read only) returns the stored elevation of the pixel containing
(lat, lon) at ``zoom`` from a validated fixture run, via
``read_point_elevation``. It always prints one JSON object with the same keys;
coordinates are never echoed. Exit 0 only on a successful read (a no-data
pixel is a successful read with ``nodata: true``).

    python -m hererisk.cli gsi-fetch-poc --lat 35.68 --lon 139.76 --zoom 14 \
        --output-dir /path/to/dedicated-poc-dir [--allow-network]

``gsi-fetch-poc`` (Phase 1-D.1, admin only) prints the plan for the single
GSI DEM10B tile containing the point; only with ``--allow-network`` does it
perform that one HTTPS request and save PNG + evidence in the PoC directory.
PoC files are not pipeline input and not approved for publication.

    python -m hererisk.cli gsi-elevation-poc --lat 35.681236 --lon 139.767125 \
        --zoom 14 --poc-dir /path/to/dedicated-poc-dir

``gsi-elevation-poc`` (Phase 1-D.2, read only, no network) returns the stored
value of a PoC-fetched GSI tile after re-checking evidence, size, SHA-256,
decode and statistics. PoC values are not approved for publication.

``pipeline`` (fixture only; ``--fixture`` is required) runs Download ->
Normalize -> Validate through ``Orchestrator.run_fixture_pipeline`` and prints
``{"run_id", "status", "error_code", "results": [ModuleResult...]}``. It
succeeds (exit 0) only if all three stages ran and returned SUCCESS; otherwise
status / error_code / exit code are those of the stage that stopped.

``pipeline --production`` uses the production context. It is BLOCKED unless
``--approval-root`` names an administrator-managed approval store holding a
matching record for every stage (``ProductionAuthorizer``); the GSI HTTPS
transport is wired only with ``--allow-network``.

    python -m hererisk.cli approval-check --api elevation --region 13 \
        --source gsi-dem10b-candidate --approval-root /path/to/approval-store [--publish]

``approval-check`` (admin pre-check / dry run) evaluates the production
authorization of every pipeline operation against the current Source
Definition. No network access, no data root, nothing is written.

    python -m hererisk.cli approval-digest --record /path/to/record.json

``approval-digest`` prints the ``record_sha256`` of a hand-written record (read
only; it never writes or completes a record).
Result: one JSON line on stdout. Logs: JSON lines on stderr. Exit code from
the result contract. Argument errors print a fixed message (never the
offending values) and exit 2.

Configuration and Schemas are always read from the repository that contains
this package (``api/<api>/conf``); the CLI has no option to point elsewhere.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import NoReturn, Sequence

from hererisk.common.authorization import ExecutionContext, FixtureAuthorizer, ProductionAuthorizer
from hererisk.common.config import ConfigurationManager
from hererisk.common.logging import StructuredLogger
from hererisk.common.orchestrator import DownloadRequest, Orchestrator, new_run_id
from hererisk.common.result import ERROR_CODES, ModuleResult, PipelineError, Status, message_for
from hererisk.common.storage import ApiDataArea, StorageError, init_fixture_data_root, is_within
from hererisk.elevation.download.download import ElevationDownload
from hererisk.elevation.download.transport import FixtureTransport, UnavailableTransport
from hererisk.elevation.lookup.reader import INVALID_COORDINATES, ReadRejected, read_point_elevation
from hererisk.elevation.normalize.stage import NormalizeStage
from hererisk.elevation.publish.stage import PublishStage
from hererisk.elevation.validate.stage import ValidateStage

REPO_ROOT = Path(__file__).resolve().parents[2]
EXIT_USAGE = 2
USAGE_ERROR = "hererisk-pipeline: invalid arguments (see --help)\n"


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse messages may echo user-supplied values or paths: never print them.
        sys.stderr.write(USAGE_ERROR)
        raise SystemExit(EXIT_USAGE)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="hererisk-pipeline", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)
    dl = sub.add_parser("download", help="request a download via the Orchestrator")
    dl.add_argument("--api", required=True, help="API identifier (e.g. elevation)")
    dl.add_argument("--region", required=True, action="append", dest="regions",
                    help="prefecture code 01-47; repeatable")
    dl.add_argument("--source", required=True, help="source_ref in the Source Definition")
    dl.add_argument("--data-root", required=True, type=Path,
                    help="data root (fixture runs: an initialised fixture root)")
    dl.add_argument("--fixture", type=Path, metavar="FIXTURE_ROOT",
                    help="run in fixture context using this fixture tree")
    dl.add_argument("--resume-run-id", help="re-run an existing run_id (same configuration)")
    pl = sub.add_parser("pipeline", help="fixture only: Download -> Normalize -> Validate")
    pl.add_argument("--api", required=True, help="API identifier (e.g. elevation)")
    pl.add_argument("--region", required=True, action="append", dest="regions",
                    help="prefecture code 01-47; repeatable")
    pl.add_argument("--source", required=True, help="source_ref in the Source Definition")
    pl.add_argument("--data-root", required=True, type=Path,
                    help="an initialised fixture data root")
    target = pl.add_mutually_exclusive_group(required=True)
    target.add_argument("--fixture", type=Path, metavar="FIXTURE_ROOT",
                        help="fixture tree (fixture context)")
    target.add_argument("--production", action="store_true",
                        help="production context (BLOCKED without a matching approval record)")
    pl.add_argument("--approval-root", type=Path,
                    help="production only: administrator-managed approval store")
    pl.add_argument("--allow-network", action="store_true",
                    help="production only: wire the GSI HTTPS transport")
    pl.add_argument("--publish", action="store_true",
                    help="also run Publish after Validate (4 stages)")
    pl.add_argument("--resume-run-id", help="re-run an existing run_id (same configuration)")
    el = sub.add_parser("elevation", help="read only: stored elevation at a point")
    # Values are parsed by the command (not argparse) so that malformed values
    # yield the fixed JSON error instead of a usage message.
    el.add_argument("--run-id", required=True, help="validated fixture run_id")
    el.add_argument("--lat", required=True, help="latitude in degrees")
    el.add_argument("--lon", required=True, help="longitude in degrees")
    el.add_argument("--zoom", required=True, help="XYZ zoom level 0-30")
    el.add_argument("--data-root", required=True, type=Path, help="fixture data root")
    poc = sub.add_parser("gsi-fetch-poc",
                         help="admin PoC: plan / fetch one GSI DEM10B tile (explicit network flag)")
    poc.add_argument("--lat", required=True, help="latitude in degrees")
    poc.add_argument("--lon", required=True, help="longitude in degrees")
    poc.add_argument("--zoom", required=True, help="must be the DEM10B source zoom (14)")
    poc.add_argument("--output-dir", required=True, type=Path,
                     help="dedicated PoC directory (empty or already a PoC directory)")
    poc.add_argument("--allow-network", action="store_true",
                     help="actually perform the single HTTPS request (otherwise plan only)")
    gev = sub.add_parser("gsi-elevation-poc",
                         help="read only: point elevation from a GSI PoC directory (no network)")
    gev.add_argument("--lat", required=True, help="latitude in degrees")
    gev.add_argument("--lon", required=True, help="longitude in degrees")
    gev.add_argument("--zoom", required=True, help="XYZ zoom level 0-30")
    gev.add_argument("--poc-dir", required=True, type=Path, help="GSI PoC directory (Phase 1-D.1)")
    ac = sub.add_parser("approval-check",
                        help="admin pre-check: production authorization of every operation")
    ac.add_argument("--api", required=True)
    ac.add_argument("--region", required=True, action="append", dest="regions")
    ac.add_argument("--source", required=True)
    ac.add_argument("--approval-root", required=True, type=Path)
    ac.add_argument("--publish", action="store_true", help="also check the publish operation")
    ad = sub.add_parser("approval-digest", help="print record_sha256 of an approval record")
    ad.add_argument("--record", required=True, type=Path)
    init = sub.add_parser("init-fixture-root",
                          help="mark an existing empty directory as a fixture data root")
    init.add_argument("--data-root", required=True, type=Path)
    return parser


def build_orchestrator(args: argparse.Namespace, logger: StructuredLogger) -> Orchestrator:
    if args.fixture is not None:
        fixture_root = args.fixture.resolve()
        config = ConfigurationManager(definition_root=fixture_root, schema_root=REPO_ROOT)
        authorizer = FixtureAuthorizer(
            fixture_root / "authorization" / "download.json",
            production_definition_root=REPO_ROOT,
        )
        transport = FixtureTransport(fixture_root / "tiles")
    else:
        config = ConfigurationManager(definition_root=REPO_ROOT, schema_root=REPO_ROOT)
        # Deny by default: without --approval-root nothing is ever granted.
        authorizer = ProductionAuthorizer(getattr(args, "approval_root", None),
                                          protected_roots=(REPO_ROOT,))
        if getattr(args, "production", False) and getattr(args, "allow_network", False):
            from hererisk.elevation.download.gsi_transport import GsiHttpTransport

            transport = GsiHttpTransport()
        else:
            transport = UnavailableTransport()
    modules = {"elevation": ElevationDownload(transport)}
    later = (NormalizeStage(), ValidateStage())
    if getattr(args, "publish", False):
        later = (*later, PublishStage())
    stages = {"elevation": later} if args.command == "pipeline" else None
    return Orchestrator(
        config_manager=config,
        authorizer=authorizer,
        modules=modules,
        data_root=args.data_root,
        logger=logger,
        stages=stages,
    )


PIPELINE_STAGES = ("download", "normalize", "validate")
PUBLISH_STAGES = (*PIPELINE_STAGES, "publish")


def pipeline_summary(results: Sequence[ModuleResult],
                     expected: Sequence[str] = PIPELINE_STAGES) -> tuple[dict, int]:
    """Overall JSON document and exit code for a pipeline run."""
    complete = [r.module for r in results] == list(expected) and all(
        r.status is Status.SUCCESS for r in results)
    if complete:
        final = None
    elif results and results[-1].status is not Status.SUCCESS:
        final = results[-1]
    else:  # stopped without a failing result: never report success
        final = ModuleResult.error(results[0].run_id if results else new_run_id(),
                                   "pipeline", "INTERNAL_ERROR")
    document = {
        "run_id": results[0].run_id if results else final.run_id,  # type: ignore[union-attr]
        "status": "SUCCESS" if final is None else final.status.value,
        "error_code": None if final is None else final.error_code,
        "results": [r.to_dict() for r in results],
    }
    return document, 0 if final is None else final.exit_code


def _init_fixture_root(data_root: Path) -> int:
    if is_within(data_root, REPO_ROOT):
        sys.stderr.write("hererisk-pipeline: fixture root must be outside the repository\n")
        return EXIT_USAGE
    try:
        init_fixture_data_root(data_root, protected_roots=(REPO_ROOT,))
    except (StorageError, OSError):
        sys.stderr.write(
            "hererisk-pipeline: fixture root must be an existing, empty, non-production directory\n"
        )
        return EXIT_USAGE
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "init-fixture-root":
        return _init_fixture_root(args.data_root)
    logger = StructuredLogger()
    if args.command == "pipeline":
        return _run_pipeline(args, logger)
    if args.command == "elevation":
        return _read_elevation(args, logger)
    if args.command == "gsi-fetch-poc":
        return _gsi_fetch_poc(args, logger)
    if args.command == "gsi-elevation-poc":
        return _gsi_elevation_poc(args, logger)
    if args.command == "approval-check":
        return _approval_check(args)
    if args.command == "approval-digest":
        return _approval_digest(args.record)
    request = DownloadRequest(
        api_id=args.api,
        region_codes=tuple(args.regions),
        source_ref=args.source,
        resume_run_id=args.resume_run_id,
    )
    try:
        result = build_orchestrator(args, logger).run_download(request)
    except Exception:  # noqa: BLE001 - never leak exception text
        result = ModuleResult.error(new_run_id(), "download", "INTERNAL_ERROR")
    sys.stdout.write(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    sys.stdout.flush()
    return result.exit_code


def _run_pipeline(args: argparse.Namespace, logger: StructuredLogger) -> int:
    request = DownloadRequest(
        api_id=args.api,
        region_codes=tuple(args.regions),
        source_ref=args.source,
        resume_run_id=args.resume_run_id,
    )
    if (args.allow_network or args.approval_root is not None) and not args.production:
        results = (ModuleResult.error(new_run_id(), "download", "INVALID_INPUT"),)
    else:
        context = ExecutionContext.PRODUCTION if args.production else ExecutionContext.FIXTURE
        try:
            results = build_orchestrator(args, logger).run_pipeline(request, context=context)
        except Exception:  # noqa: BLE001 - never leak exception text
            results = (ModuleResult.error(new_run_id(), "download", "INTERNAL_ERROR"),)
    document, code = pipeline_summary(results, PUBLISH_STAGES if args.publish else PIPELINE_STAGES)
    sys.stdout.write(json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n")
    sys.stdout.flush()
    return code


def _approval_check(args: argparse.Namespace) -> int:
    """Evaluate every operation's production authorization; print one JSON line."""
    operations = ["download", "normalize", "validate"] + (["publish"] if args.publish else [])
    doc: dict = {"status": "BLOCKED", "definition_revision": None, "definition_raw_sha256": None,
                 "operations": []}
    try:
        definition = ConfigurationManager(REPO_ROOT, REPO_ROOT).load("api", args.api, "sources")
    except Exception:  # noqa: BLE001 - never leak exception text
        doc["error_code"] = "INVALID_CONFIGURATION"
        sys.stdout.write(json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n")
        return 2
    doc["definition_revision"] = definition.data.get("definition_revision")
    doc["definition_raw_sha256"] = definition.raw_sha256
    authorizer = ProductionAuthorizer(args.approval_root, protected_roots=(REPO_ROOT,))
    for operation in operations:
        entry = {"operation": operation, "decision": "BLOCKED", "authorization_ref": None,
                 "reason": None}
        try:
            grant = authorizer.authorize(api_id=args.api, operation=operation,
                                         source_ref=args.source,
                                         region_codes=tuple(sorted(args.regions)),
                                         definition=definition)
            entry.update(decision="GRANTED", authorization_ref=grant.authorization_ref)
        except PipelineError as exc:
            entry["reason"] = str(exc).partition(": ")[2] or exc.error_code  # fixed texts only
        doc["operations"].append(entry)
    granted = all(e["decision"] == "GRANTED" for e in doc["operations"])
    doc["status"] = "GRANTED" if granted else "BLOCKED"
    doc["error_code"] = None if granted else "APPROVAL_REQUIRED"
    sys.stdout.write(json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n")
    return 0 if granted else 3


def _approval_digest(path: Path) -> int:
    from hererisk.common.approval_store import MAX_RECORD_BYTES, record_digest
    from hererisk.common.config import parse_strict_json

    try:
        data = path.read_bytes()
        if len(data) > MAX_RECORD_BYTES:
            raise ValueError("too large")
        record = parse_strict_json(data)
        if not isinstance(record, dict):
            raise ValueError("not an object")
        digest = record_digest(record)
    except Exception:  # noqa: BLE001 - never leak paths / exception text
        sys.stdout.write(json.dumps({"record_sha256": None, "error_code": "INVALID_INPUT"}) + "\n")
        return 2
    sys.stdout.write(json.dumps({"record_sha256": digest, "error_code": None}) + "\n")
    return 0


_ZOOM_RE = re.compile(r"^[0-9]{1,2}$")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
ELEVATION_SUCCESS_MESSAGE = "Elevation read"


def _elevation_document(point=None, *, run_id=None, error_code=None, reason=None) -> dict:
    """Fixed-key JSON document for the ``elevation`` command."""
    if point is not None:
        doc = point.to_dict()
        return {"status": "SUCCESS", "error_code": None, "reason": None,
                "message": ELEVATION_SUCCESS_MESSAGE, **doc}
    status = ERROR_CODES[error_code][0].value
    return {
        "status": status, "error_code": error_code, "reason": reason,
        "message": message_for(error_code),
        # Echo the run_id only if it is a well-formed UUID; never echo coordinates.
        "run_id": run_id if isinstance(run_id, str) and _UUID_RE.match(run_id) else None,
        "acquisition_id": None, "candidate_sha256": None, "tile": None, "pixel": None,
        "elevation_cm": None, "nodata": None,
    }


def _read_elevation(args: argparse.Namespace, logger: StructuredLogger) -> int:
    run_id = args.run_id
    log = logger.bind(module="elevation-lookup", api_id="elevation",
                      run_id=run_id if _UUID_RE.match(run_id) else None)
    code, reason, point = None, None, None
    try:
        try:
            lat, lon = float(args.lat), float(args.lon)
        except ValueError as exc:
            raise ReadRejected("INVALID_INPUT", INVALID_COORDINATES, "not a number") from exc
        if not _ZOOM_RE.match(args.zoom):
            raise ReadRejected("INVALID_INPUT", INVALID_COORDINATES, "zoom not an integer")
        with ApiDataArea(args.data_root, "elevation") as area:
            point = read_point_elevation(area, run_id, lat, lon, int(args.zoom))
    except ReadRejected as exc:
        code, reason = exc.error_code, exc.reason
    except StorageError as exc:
        code = exc.error_code
    except Exception:  # noqa: BLE001 - never leak exception text or paths
        code = "INTERNAL_ERROR"
    if point is not None:
        document, exit_code = _elevation_document(point), 0
        log.info("Elevation read")
    else:
        document = _elevation_document(run_id=run_id, error_code=code, reason=reason)
        exit_code = ERROR_CODES[code][1]
        log.log("WARNING" if document["status"] == "BLOCKED" else "ERROR",
                "Elevation read refused", error_code=code)
    sys.stdout.write(json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n")
    sys.stdout.flush()
    return exit_code


def _gsi_fetch_poc(args: argparse.Namespace, logger: StructuredLogger,
                  connection_factory=None) -> int:
    from hererisk.elevation.gsi_poc import http_fetch, poc  # only this command loads network code

    log = logger.bind(module="gsi-fetch-poc", api_id="elevation", run_id=None)
    document: dict = {"status": None, "error_code": None, "message": None, "mode": None,
                      "network_used": False, "url": None, "tile": None, "files": None,
                      "evidence": None}
    try:
        try:
            lat, lon = float(args.lat), float(args.lon)
        except ValueError as exc:
            raise PipelineError("INVALID_INPUT", "coordinates not numbers") from exc
        if not _ZOOM_RE.match(args.zoom):
            raise PipelineError("INVALID_INPUT", "zoom not an integer")
        plan = poc.plan_fetch(lat, lon, int(args.zoom), repo_root=REPO_ROOT)
        outcome = poc.run_fetch_poc(
            plan, args.output_dir, allow_network=bool(args.allow_network),
            protected_roots=(REPO_ROOT,),
            connection_factory=connection_factory or http_fetch.default_connection_factory)
        document.update(outcome, status="SUCCESS", message=(
            "Tile fetched (PoC only)" if outcome["network_used"] else "Plan only; no network used"))
        code = 0
        log.info(document["message"])
    except PipelineError as exc:
        status, code = ERROR_CODES[exc.error_code]
        document.update(status=status.value, error_code=exc.error_code,
                        message=message_for(exc.error_code))
        log.error("GSI PoC fetch refused", error_code=exc.error_code)
    except Exception:  # noqa: BLE001 - never leak exception text or paths
        status, code = ERROR_CODES["INTERNAL_ERROR"]
        document.update(status=status.value, error_code="INTERNAL_ERROR",
                        message=message_for("INTERNAL_ERROR"))
        log.error("GSI PoC fetch failed", error_code="INTERNAL_ERROR")
    sys.stdout.write(json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n")
    sys.stdout.flush()
    return code


def _gsi_elevation_poc(args: argparse.Namespace, logger: StructuredLogger) -> int:
    from hererisk.elevation.gsi_poc.reader import read_poc_elevation  # network-free module

    log = logger.bind(module="gsi-elevation-poc", api_id="elevation", run_id=None)
    document: dict = {"status": None, "error_code": None, "reason": None, "message": None,
                      "tile": None, "pixel": None, "elevation_cm": None, "elevation_m": None,
                      "nodata": None, "poc_only": True, "source": None}
    try:
        try:
            lat, lon = float(args.lat), float(args.lon)
        except ValueError as exc:
            raise ReadRejected("INVALID_INPUT", INVALID_COORDINATES, "not a number") from exc
        if not _ZOOM_RE.match(args.zoom):
            raise ReadRejected("INVALID_INPUT", INVALID_COORDINATES, "zoom not an integer")
        point = read_poc_elevation(args.poc_dir, lat, lon, int(args.zoom))
        document.update(point.to_dict(), status="SUCCESS",
                        message="Elevation read from GSI PoC data (not approved for publication)")
        code = 0
        log.info("GSI PoC elevation read")
    except ReadRejected as exc:
        status, code = ERROR_CODES[exc.error_code]
        document.update(status=status.value, error_code=exc.error_code, reason=exc.reason,
                        message=message_for(exc.error_code))
        log.log("WARNING" if status is Status.BLOCKED else "ERROR",
                "GSI PoC elevation read refused", error_code=exc.error_code)
    except Exception:  # noqa: BLE001 - never leak exception text, paths or coordinates
        status, code = ERROR_CODES["INTERNAL_ERROR"]
        document.update(status=status.value, error_code="INTERNAL_ERROR",
                        message=message_for("INTERNAL_ERROR"))
        log.error("GSI PoC elevation read failed", error_code="INTERNAL_ERROR")
    sys.stdout.write(json.dumps(document, ensure_ascii=False, sort_keys=True) + "\n")
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
