"""Elevation Download core.

Per tile (contract 6, 確定手順案):
  1. receive bytes from the Transport into ``work/download/<run>/<acq>/original.part``
  2. confirm complete receipt (length, size limit), flush + fsync
  3. re-read the part file (bounded) and compare size / SHA-256 with the streamed values
  4. check the PNG container
  5. finalise to ``work/acquisitions/<run>/<acq>/original.png`` (same-FS, no-clobber)
  6. commit the Acquisition Record ``records/acquisitions/<run>/<acq>.json``
  7. commit the marker ``records/commits/<acq>.json``
  8. verify marker <-> record <-> artifact <-> fixed plan before counting the tile

Verification (step 8 and resume) rebuilds the Record expected from the fixed
plan (definition hash, effective configuration, source, URL, tile, regions,
pipeline, usage) and requires an exact match; only ``acquired_at`` comes from
the Record and must be a valid UTC timestamp. Hashes detect accidental or
partial corruption; they do NOT authenticate. Anyone able to write the API's
``records`` and ``work`` areas can forge a consistent set, so those areas must
be writable only by the pipeline management user (see usage doc, trust model).

SUCCESS only when every requested tile passed step 8. Download never touches
``dl/``, ``rel/`` or any Registry and never invokes a later stage.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

from hererisk.common.authorization import ExecutionContext
from hererisk.common.config import ConfigurationError, parse_strict_json, thaw
from hererisk.common.logging import StructuredLogger
from hererisk.common.orchestrator import DownloadPlan
from hererisk.common.result import Artifact, ModuleResult, PipelineError
from hererisk.common.storage import ApiDataArea, StorageError, storage_error_code
from hererisk.elevation.download import record as rec
from hererisk.elevation.download.png import check_png
from hererisk.elevation.download.transport import Transport

MODULE = "download"
PIPELINE_ID = "elevation-download"
PIPELINE_VERSION = "fixture-0.1"  # fixture transport
PRODUCTION_PIPELINE_VERSION = "0.1"  # GSI HTTPS transport (Phase 1-D.3)


def pipeline_for(context: ExecutionContext) -> tuple[str, str]:
    """Pipeline identity actually executed in a context (recorded in Records)."""
    if context in (ExecutionContext.PRODUCTION, ExecutionContext.PRIVATE_EXPERIMENT):
        return PIPELINE_ID, PRODUCTION_PIPELINE_VERSION  # real-data pipeline
    return PIPELINE_ID, PIPELINE_VERSION

# GSI elevation PNG tile format (demtile spec): defined in elevation.tile_format.
from hererisk.elevation.tile_format import (  # noqa: E402,F401 - re-exported
    TILE_BIT_DEPTH,
    TILE_COLOR_TYPE,
    TILE_HEIGHT,
    TILE_WIDTH,
)

PART_NAME = "original.part"
ARTIFACT_NAME = "original.png"

# Read limits for committed evidence (bytes). Records are ~2 KiB, markers ~0.5 KiB.
MAX_RECORD_BYTES = 64 * 1024
MAX_MARKER_BYTES = 16 * 1024

TileKey = tuple[int, int, int]

# API-wide lock serialising capacity checks + reservations across all sources.
QUOTA_LOCK = ("work", "locks", "download-quota.lock")
_ID = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_JSON_RE = re.compile(rf"^(?P<id>{_ID})\.json$")
_TMP_RE = re.compile(rf"^\.(?P<id>{_ID})\.json\.tmp-[0-9a-f]{{32}}$")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _rfc3339(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tile_url(template: str, z: int, x: int, y: int) -> str:
    return template.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))


def plan_tiles(plan: DownloadPlan) -> list[TileKey]:
    acquisition = plan.source["acquisition"]
    return sorted((acquisition["zoom"], t["x"], t["y"]) for t in acquisition["tiles"])


class ElevationDownload:
    api_id = "elevation"

    def __init__(
        self,
        transport: Transport,
        *,
        id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._transport = transport
        self._id_factory = id_factory
        self._clock = clock

    @property
    def transport_context(self):
        return self._transport.context

    @property
    def pipeline(self) -> tuple[str, str]:
        return pipeline_for(self._transport.context)

    # -- preflight (no I/O) -------------------------------------------
    def preflight(self, plan: DownloadPlan) -> None:
        acquisition = plan.source["acquisition"]
        tiles = acquisition["tiles"]
        if tiles is None:
            raise PipelineError("TARGET_UNCONFIGURED", "tiles not configured")
        if acquisition["method"] != "xyz_png":
            raise PipelineError("INVALID_CONFIGURATION", "unsupported method")
        z = acquisition["zoom"]
        limit = 1 << z
        keys = {(t["x"], t["y"]) for t in tiles}
        if len(keys) != len(tiles) or any(not (0 <= x < limit and 0 <= y < limit) for x, y in keys):
            raise PipelineError("INVALID_CONFIGURATION", "tile out of range or duplicated")
        if len(tiles) > plan.authorization.policy["max_tiles_per_request"]:
            raise PipelineError("INVALID_CONFIGURATION", "too many tiles for policy")
        template = acquisition["url_template"]
        parts = urlsplit(template)
        if parts.username or parts.password or parts.query or parts.fragment:
            raise PipelineError("INVALID_CONFIGURATION", "URL template not allowed")
        for x, y in keys:
            if not self._transport.accepts(tile_url(template, z, x, y)):
                raise PipelineError("INVALID_CONFIGURATION", "URL not allowed for transport")
        # Source aliases resolving to the same acquisition target are rejected.
        mine = {tile_url(template, z, x, y) for x, y in keys}
        for ref, other in plan.definition.data["sources"].items():
            if ref == plan.source_ref or other["acquisition"]["tiles"] is None:
                continue
            oa = other["acquisition"]
            theirs = {tile_url(oa["url_template"], oa["zoom"], t["x"], t["y"]) for t in oa["tiles"]}
            if mine & theirs:
                raise PipelineError("INVALID_CONFIGURATION", "source alias overlaps")

    # -- execution -----------------------------------------------------
    def reserve_capacity(self, plan: DownloadPlan, area: ApiDataArea) -> str:
        """Reserve one uncommitted-acquisition slot under the API-wide quota lock.

        Counts every uncommitted acquisition in the data area by id (see
        :func:`pending_acquisitions`). At or above the fixture policy's
        ``max_pending_acquisitions`` nothing is created and RECOVERY_REQUIRED is
        raised. Otherwise the slot is taken by creating
        ``work/download/<run>/<acq>`` before the lock is released, so concurrent
        runs of any source_ref cannot exceed the limit together.
        """
        limit = plan.authorization.policy["max_pending_acquisitions"]
        with area.exclusive_lock(area.path(*QUOTA_LOCK), blocking=True):
            try:
                pending = pending_acquisitions(area)
            except StorageError as exc:
                raise PipelineError("RECOVERY_REQUIRED", "pending area unreadable") from exc
            if len(pending) >= limit:
                raise PipelineError("RECOVERY_REQUIRED", "too many uncommitted acquisitions")
            acquisition_id = self._id_factory()
            area.ensure_dir(area.path("work", "download", plan.run_id, acquisition_id))
        return acquisition_id

    def execute(
        self,
        plan: DownloadPlan,
        area: ApiDataArea,
        logger: StructuredLogger,
        *,
        reserved_acquisition_id: str | None = None,
    ) -> ModuleResult:
        log = logger.bind(module=MODULE)
        # Artifacts are always reported in tile order, reused or newly acquired.
        committed: dict[TileKey, Artifact] = {}
        keys = plan_tiles(plan)
        reserved = reserved_acquisition_id
        try:
            if plan.resume:
                committed.update(reconcile_run(area, plan))
            for key in keys:
                if key in committed:
                    continue
                acquisition_id = reserved or self.reserve_capacity(plan, area)
                reserved = None
                committed[key] = self._acquire(plan, area, acquisition_id, *key)
                log.info("Acquisition committed")
        except (PipelineError, StorageError) as exc:
            log.error("Acquisition stopped", error_code=exc.error_code)
            ordered = [committed[k] for k in keys if k in committed]
            return self._error(plan, exc.error_code, ordered)
        return ModuleResult.success(plan.run_id, MODULE, tuple(committed[k] for k in keys))

    @staticmethod
    def _error(plan: DownloadPlan, code: str, committed: list[Artifact]) -> ModuleResult:
        # BLOCKED results carry no artifacts (contract 4.2).
        artifacts = () if code == "RECOVERY_REQUIRED" else tuple(committed)
        return ModuleResult.error(plan.run_id, MODULE, code, artifacts)

    def _acquire(
        self, plan: DownloadPlan, area: ApiDataArea, acquisition_id: str, z: int, x: int, y: int
    ) -> Artifact:
        run_id = plan.run_id
        url = tile_url(plan.source["acquisition"]["url_template"], z, x, y)
        max_bytes = plan.authorization.policy["max_tile_bytes"]

        download_dir = area.path("work", "download", run_id, acquisition_id)
        area.ensure_dir(download_dir)
        part = download_dir / PART_NAME

        response = self._transport.fetch(url)
        if response.effective_url != url:
            raise PipelineError("REDIRECT_REJECTED")
        if response.content_type != "image/png":
            raise PipelineError("CONTENT_TYPE_INVALID")
        if response.content_length is not None and response.content_length > max_bytes:
            raise PipelineError("SIZE_INVALID", "declared length over limit")

        hasher = hashlib.sha256()
        size = 0
        handle = area.open_exclusive(part)
        try:
            for chunk in response.chunks:
                size += len(chunk)
                if size > max_bytes:
                    raise PipelineError("SIZE_INVALID", "body over limit")
                hasher.update(chunk)
                try:
                    handle.write(chunk)
                except OSError as exc:
                    raise StorageError(storage_error_code(exc)) from exc
        except BaseException:
            handle.close()
            raise
        area.finish_file(handle)
        acquired_at = _rfc3339(self._clock())
        if size == 0:
            raise PipelineError("SIZE_INVALID", "empty body")
        if response.content_length is not None and response.content_length != size:
            raise PipelineError("TRANSFER_INTERRUPTED", "length mismatch")
        sha256 = hasher.hexdigest()

        stored = area.read_bytes(part, max_bytes)
        if len(stored) != size or hashlib.sha256(stored).hexdigest() != sha256:
            raise PipelineError("STORAGE_INTEGRITY_FAILED", "re-read mismatch")
        check_png(
            stored,
            width=TILE_WIDTH,
            height=TILE_HEIGHT,
            bit_depth=TILE_BIT_DEPTH,
            color_type=TILE_COLOR_TYPE,
        )

        artifact = area.path("work", "acquisitions", run_id, acquisition_id, ARTIFACT_NAME)
        area.link_no_clobber(part, artifact)
        area.remove_empty_dir(download_dir)

        record_bytes = rec.to_bytes(build_record(plan, acquisition_id, (z, x, y), acquired_at,
                                                 size, sha256))
        record_loc = area.path("records", "acquisitions", run_id, f"{acquisition_id}.json")
        try:
            area.write_new(record_loc, record_bytes)
        except StorageError as exc:
            raise PipelineError("RECORD_COMMIT_FAILED", "record") from exc
        marker = {
            "schema_version": rec.MARKER_SCHEMA_VERSION,
            "acquisition_id": acquisition_id,
            "record_ref": area.relative(record_loc, "records"),
            "record_sha256": hashlib.sha256(record_bytes).hexdigest(),
            "artifact_ref": area.relative(artifact, "work"),
            "artifact_sha256": sha256,
        }
        rec.validate_marker(marker)
        try:
            area.write_new(area.path("records", "commits", f"{acquisition_id}.json"),
                           rec.to_bytes(marker))
        except StorageError as exc:
            raise PipelineError("RECORD_COMMIT_FAILED", "marker") from exc

        try:
            artifact_entry, key = verify_commit(area, plan, acquisition_id)
        except PipelineError as exc:
            raise PipelineError("STORAGE_INTEGRITY_FAILED", "post-commit verification") from exc
        if key != (z, x, y):
            raise PipelineError("STORAGE_INTEGRITY_FAILED", "post-commit tile mismatch")
        return artifact_entry


def build_record(
    plan: DownloadPlan,
    acquisition_id: str,
    tile: TileKey,
    acquired_at: str,
    size: int,
    sha256: str,
) -> dict[str, Any]:
    """The Record fully determined by the fixed plan plus the acquisition facts."""
    z, x, y = tile
    source = plan.source
    data = plan.definition.data
    url = tile_url(source["acquisition"]["url_template"], z, x, y)
    record = {
        "record_schema_version": rec.RECORD_SCHEMA_VERSION,
        "acquisition_id": acquisition_id,
        "run_id": plan.run_id,
        "api_id": plan.api_id,
        "provider": thaw(source["provider"]),
        "data_name": source["name"],
        "data_type": "elevation_png",
        # Redirects are rejected, so the effective URL is always the requested one.
        "requested_url": url,
        "effective_url": url,
        "official_page_url": source["official_page_url"],
        "acquired_at": acquired_at,
        "management_prefectures": list(plan.region_codes),
        "tile": {"z": z, "x": x, "y": y},
        "size_bytes": size,
        "sha256": sha256,
        "source_definition": {
            "schema_version": data["schema_version"],
            "definition_revision": data["definition_revision"],
            "source_ref": plan.source_ref,
            "raw_sha256": plan.definition.raw_sha256,
        },
        "effective_configuration": {
            "snapshot_ref": plan.effective_configuration_ref,
            "sha256": plan.effective_configuration_sha256,
        },
        "pipeline": dict(zip(("id", "version"), pipeline_for(plan.authorization.context))),
        # Provider version / reference date are unknown for fixtures: null,
        # never inferred from acquisition time.
        "original_version": None,
        "data_reference_date": None,
        "source_metadata_evidence": None,
        "usage_snapshot": {
            "terms_url": source["usage"]["terms_url"],
            "attribution_text": source["usage"]["attribution_text"],
            "review_ref": source["usage"]["review_ref"],
            "approval_ref": source["approval_ref"],
        },
    }
    try:
        rec.validate_record(record)
    except ConfigurationError as exc:
        raise PipelineError("INTERNAL_ERROR", "record failed own schema") from exc
    return record


def verify_commit(area: ApiDataArea, plan: DownloadPlan, acquisition_id: str) -> tuple[Artifact, TileKey]:
    """Check one acquisition against marker, Record, artifact and the fixed plan.

    Raises ``PipelineError("RECOVERY_REQUIRED")`` on any inconsistency.
    """

    def fail(reason: str) -> PipelineError:
        return PipelineError("RECOVERY_REQUIRED", reason)

    try:
        if str(uuid.UUID(acquisition_id)) != acquisition_id:
            raise ValueError
    except ValueError as exc:
        raise fail("malformed acquisition id") from exc
    run_id = plan.run_id
    record_loc = area.path("records", "acquisitions", run_id, f"{acquisition_id}.json")
    artifact_dir = area.path("work", "acquisitions", run_id, acquisition_id)
    artifact_loc = artifact_dir / ARTIFACT_NAME
    try:
        marker = parse_strict_json(
            area.read_bytes(area.path("records", "commits", f"{acquisition_id}.json"),
                            MAX_MARKER_BYTES)
        )
        rec.validate_marker(marker)
        if (
            marker["acquisition_id"] != acquisition_id
            or marker["record_ref"] != area.relative(record_loc, "records")
            or marker["artifact_ref"] != area.relative(artifact_loc, "work")
        ):
            raise fail("marker references mismatch")
        record_bytes = area.read_bytes(record_loc, MAX_RECORD_BYTES)
        if hashlib.sha256(record_bytes).hexdigest() != marker["record_sha256"]:
            raise fail("record hash mismatch")
        record = parse_strict_json(record_bytes)
        rec.validate_record(record)
        tile = record["tile"]
        key = (tile["z"], tile["x"], tile["y"])
        if key not in plan_tiles(plan):
            raise fail("tile not in plan")
        if area.list_dir(artifact_dir) != [ARTIFACT_NAME]:
            raise fail("unexpected entries beside artifact")
        sha256, size = area.hash_file(artifact_loc, plan.authorization.policy["max_tile_bytes"])
    except (StorageError, ConfigurationError) as exc:
        raise fail("unreadable or invalid evidence") from exc
    if sha256 != marker["artifact_sha256"]:
        raise fail("artifact hash mismatch")
    expected = build_record(plan, acquisition_id, key, record["acquired_at"], size, sha256)
    if record != expected:
        raise fail("record does not match the fixed plan")
    artifact = Artifact(
        artifact_id=acquisition_id,
        acquisition_id=acquisition_id,
        record_ref=marker["record_ref"],
        sha256=sha256,
        size_bytes=size,
    )
    return artifact, key


def _markers_for_run(area: ApiDataArea, run_id: str) -> set[str]:
    """All acquisition ids whose marker points into ``run_id`` (strict scan)."""
    prefix = f"acquisitions/{run_id}/"
    found: set[str] = set()
    for name in area.list_dir(area.path("records", "commits")):
        stem, dot, ext = name.rpartition(".")
        if name.startswith(".") or not dot or ext != "json":
            raise PipelineError("RECOVERY_REQUIRED", "unexpected entry in commits")
        try:
            marker = parse_strict_json(
                area.read_bytes(area.path("records", "commits", name), MAX_MARKER_BYTES)
            )
            rec.validate_marker(marker)
        except (StorageError, ConfigurationError) as exc:
            raise PipelineError("RECOVERY_REQUIRED", "unreadable marker") from exc
        if marker["acquisition_id"] != stem:
            raise PipelineError("RECOVERY_REQUIRED", "marker name mismatch")
        if marker["record_ref"].startswith(prefix) or marker["artifact_ref"].startswith(prefix):
            found.add(stem)
    return found


def reconcile_run(area: ApiDataArea, plan: DownloadPlan) -> dict[TileKey, Artifact]:
    """Verify everything a previous attempt of this run left behind.

    The sets of acquisition ids found via markers, Records and artifacts must be
    identical and fully verified; any uncommitted leftover (``.part``, Record or
    artifact without marker, marker without Record/artifact, temp files) makes
    the run RECOVERY_REQUIRED. Nothing is deleted, moved or overwritten here.
    """
    run_id = plan.run_id
    try:
        if area.list_dir(area.path("work", "download", run_id)):
            raise PipelineError("RECOVERY_REQUIRED", "uncommitted part data")
        artifact_ids = set(area.list_dir(area.path("work", "acquisitions", run_id)))
        record_ids = set()
        for name in area.list_dir(area.path("records", "acquisitions", run_id)):
            stem, dot, ext = name.rpartition(".")
            if name.startswith(".") or not dot or ext != "json":
                raise PipelineError("RECOVERY_REQUIRED", "unexpected record entry")
            record_ids.add(stem)
        marker_ids = _markers_for_run(area, run_id)
    except StorageError as exc:
        raise PipelineError("RECOVERY_REQUIRED", "run evidence unreadable") from exc
    if not artifact_ids == record_ids == marker_ids:
        raise PipelineError("RECOVERY_REQUIRED", "evidence sets differ")

    done: dict[TileKey, Artifact] = {}
    for acquisition_id in sorted(marker_ids):
        artifact, key = verify_commit(area, plan, acquisition_id)
        if key in done:
            raise PipelineError("RECOVERY_REQUIRED", "duplicate acquisition for tile")
        done[key] = artifact
    return done


def _classify(names: list[str], ids: set[str], temps: set[str], unknown: set[str],
              where: str) -> None:
    for name in names:
        if m := _JSON_RE.match(name):
            ids.add(m["id"])
        elif m := _TMP_RE.match(name):
            temps.add(m["id"])
        else:
            unknown.add(f"{where}/{name}")


def pending_acquisitions(area: ApiDataArea) -> set[str]:
    """Ids of every uncommitted acquisition in the API data area (R1-02).

    An acquisition counts as committed only when its marker, Record and artifact
    directory all exist and no part directory or temporary file remains for it.
    Everything else is pending, whatever the stage it stopped at: reserved or
    partial (``work/download``), artifact only, Record only, marker only,
    interrupted temp files. Each id is counted once. Unrecognised entries are
    counted individually (conservative). Nothing is deleted.
    """
    parts: set[str] = set()
    artifacts: set[str] = set()
    records: set[str] = set()
    markers: set[str] = set()
    temps: set[str] = set()
    unknown: set[str] = set()
    for run in area.list_dir(area.path("work", "download")):
        parts.update(area.list_dir(area.path("work", "download", run)))
    for run in area.list_dir(area.path("work", "acquisitions")):
        artifacts.update(area.list_dir(area.path("work", "acquisitions", run)))
    for run in area.list_dir(area.path("records", "acquisitions")):
        names = area.list_dir(area.path("records", "acquisitions", run))
        _classify(names, records, temps, unknown, f"records/acquisitions/{run}")
    _classify(area.list_dir(area.path("records", "commits")), markers, temps, unknown,
              "records/commits")
    committed = (markers & records & artifacts) - parts - temps
    return (parts | artifacts | records | markers | temps | unknown) - committed
