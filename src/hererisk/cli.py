"""Development/test-only CLI for the pipeline Orchestrator.

Composition root: wires the common Orchestrator to API Download modules.
There is no other entry point that runs Download directly.

    python -m hererisk.cli download --api elevation --region 13 \
        --source fixture-dem-png-tokyo --fixture tests/fixtures/elevation-fixture \
        --data-root /path/to/tmp-data-root

Without ``--fixture`` the production context is used; since no production
approval mechanism or network transport exists, it ends BLOCKED.
Result: one JSON line on stdout. Logs: JSON lines on stderr. Exit code from
the result contract.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from hererisk.common.authorization import FixtureAuthorizer, ProductionAuthorizer
from hererisk.common.config import ConfigurationManager
from hererisk.common.logging import StructuredLogger
from hererisk.common.orchestrator import DownloadRequest, Orchestrator, new_run_id
from hererisk.common.result import ModuleResult
from hererisk.elevation.download.download import ElevationDownload
from hererisk.elevation.download.transport import FixtureTransport, UnavailableTransport

PRODUCTION_DATA_ROOT = Path("/data")
EXIT_USAGE = 2


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # usage errors -> exit 2, message on stderr
        self.print_usage(sys.stderr)
        sys.stderr.write(f"{self.prog}: error: {message}\n")
        raise SystemExit(EXIT_USAGE)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="hererisk-pipeline", description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    dl = sub.add_parser("download", help="request a download via the Orchestrator")
    dl.add_argument("--api", required=True, help="API identifier (e.g. elevation)")
    dl.add_argument("--region", required=True, action="append", dest="regions",
                    help="prefecture code 01-47; repeatable")
    dl.add_argument("--source", required=True, help="source_ref in the Source Definition")
    dl.add_argument("--data-root", required=True, type=Path,
                    help="data root (fixture runs must not use /data)")
    dl.add_argument("--fixture", type=Path, metavar="FIXTURE_ROOT",
                    help="run in fixture context using this fixture tree")
    dl.add_argument("--config-root", type=Path, default=Path.cwd(),
                    help="repository root holding api/<api>/conf (default: cwd)")
    dl.add_argument("--resume-run-id", help="re-run an existing run_id (same configuration)")
    return parser


def _is_under(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    return resolved == root or resolved.is_relative_to(root)


def build_orchestrator(args: argparse.Namespace, logger: StructuredLogger) -> Orchestrator:
    config_root = args.config_root.resolve()
    if args.fixture is not None:
        fixture_root = args.fixture.resolve()
        config = ConfigurationManager(definition_root=fixture_root, schema_root=config_root)
        authorizer = FixtureAuthorizer(
            fixture_root / "authorization" / "download.json",
            production_definition_root=config_root,
        )
        transport = FixtureTransport(fixture_root / "tiles")
    else:
        config = ConfigurationManager(definition_root=config_root, schema_root=config_root)
        authorizer = ProductionAuthorizer()
        transport = UnavailableTransport()
    modules = {"elevation": ElevationDownload(transport)}
    return Orchestrator(
        config_manager=config,
        authorizer=authorizer,
        modules=modules,
        data_root=args.data_root,
        logger=logger,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logger = StructuredLogger()
    if args.fixture is not None and _is_under(args.data_root, PRODUCTION_DATA_ROOT):
        result = ModuleResult.error(new_run_id(), "download", "INVALID_INPUT")
    elif args.fixture is not None and _is_under(args.data_root, args.config_root.resolve()):
        # Keep fixture output out of the repository tree.
        result = ModuleResult.error(new_run_id(), "download", "INVALID_INPUT")
    else:
        request = DownloadRequest(
            api_id=args.api,
            region_codes=tuple(args.regions),
            source_ref=args.source,
            resume_run_id=args.resume_run_id,
        )
        result = build_orchestrator(args, logger).run_download(request)
    sys.stdout.write(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    sys.stdout.flush()
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
