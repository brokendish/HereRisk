"""Elevation Download core.

Per tile (contract 6, 確定手順案):
  1. receive bytes from the Transport into ``work/download/<run>/<acq>/original.part``
  2. confirm complete receipt (length, size limit), flush + fsync
  3. re-read the part file and compare size / SHA-256 with the streamed values
  4. check the PNG container
  5. finalise to ``work/acquisitions/<run>/<acq>/original.png`` (same-FS, no-clobber)
  6. commit the Acquisition Record ``records/acquisitions/<run>/<acq>.json``
  7. commit the marker ``records/commits/<acq>.json``
  8. re-verify marker <-> record <-> artifact before counting the tile as done

SUCCESS only when every requested tile passed step 8. Download never touches
``dl/``, ``rel/`` or any Registry and never invokes a later stage.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

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
PIPELINE_VERSION = "fixture-0.1"  # The only implemented version: fixture transport only.

# GSI elevation PNG tile format (demtile spec: 256x256, 24-bit RGB).
TILE_WIDTH = 256
TILE_HEIGHT = 256
TILE_BIT_DEPTH = 8
TILE_COLOR_TYPE = 2  # truecolour RGB

PART_NAME = "original.part"
ARTIFACT_NAME = "original.png"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _rfc3339(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tile_url(template: str, z: int, x: int, y: int) -> str:
    return template.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))


class ElevationDownload:
    api_id = "elevation"
    pipeline = (PIPELINE_ID, PIPELINE_VERSION)

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
    def execute(
        self, plan: DownloadPlan, area: ApiDataArea, logger: StructuredLogger
    ) -> ModuleResult:
        log = logger.bind(module=MODULE)
        # Artifacts are always reported in tile order, reused or newly acquired.
        committed: dict[tuple[int, int, int], Artifact] = {}
        acquisition = plan.source["acquisition"]
        keys = sorted((acquisition["zoom"], t["x"], t["y"]) for t in acquisition["tiles"])
        try:
            if plan.resume:
                committed.update(self._inspect_existing(plan, area))
            for key in keys:
                if key in committed:
                    continue
                committed[key] = self._acquire(plan, area, *key)
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

    def _acquire(self, plan: DownloadPlan, area: ApiDataArea, z: int, x: int, y: int) -> Artifact:
        acquisition_id = self._id_factory()
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

        stored = area.read_bytes(part)
        if len(stored) != size or hashlib.sha256(stored).hexdigest() != sha256:
            raise PipelineError("STORAGE_INTEGRITY_FAILED", "re-read mismatch")
        check_png(
            stored,
            width=TILE_WIDTH,
            height=TILE_HEIGHT,
            bit_depth=TILE_BIT_DEPTH,
            color_type=TILE_COLOR_TYPE,
        )

        artifact_dir = area.path("work", "acquisitions", run_id, acquisition_id)
        area.ensure_dir(artifact_dir)
        artifact_path = artifact_dir / ARTIFACT_NAME
        area.link_no_clobber(part, artifact_path)
        area.remove_empty_dir(download_dir)
        final = area.read_bytes(artifact_path)
        if len(final) != size or hashlib.sha256(final).hexdigest() != sha256:
            raise PipelineError("STORAGE_INTEGRITY_FAILED", "final mismatch")

        record = self._build_record(plan, acquisition_id, url, response.effective_url,
                                    acquired_at, z, x, y, size, sha256)
        record_bytes = rec.to_bytes(record)
        record_dir = area.path("records", "acquisitions", run_id)
        record_path = record_dir / f"{acquisition_id}.json"
        marker_path = area.path("records", "commits", f"{acquisition_id}.json")
        try:
            area.ensure_dir(record_dir)
            area.write_new(record_path, record_bytes)
        except StorageError as exc:
            raise PipelineError("RECORD_COMMIT_FAILED", "record") from exc
        marker = {
            "schema_version": rec.MARKER_SCHEMA_VERSION,
            "acquisition_id": acquisition_id,
            "record_ref": area.relative(record_path, "records"),
            "record_sha256": hashlib.sha256(record_bytes).hexdigest(),
            "artifact_ref": area.relative(artifact_path, "work"),
            "artifact_sha256": sha256,
        }
        rec.validate_marker(marker)
        try:
            area.write_new(marker_path, rec.to_bytes(marker))
        except StorageError as exc:
            raise PipelineError("RECORD_COMMIT_FAILED", "marker") from exc

        try:
            return verify_commit(area, run_id, acquisition_id)
        except PipelineError as exc:
            raise PipelineError("STORAGE_INTEGRITY_FAILED", "post-commit verification") from exc

    @staticmethod
    def _build_record(
        plan: DownloadPlan,
        acquisition_id: str,
        requested_url: str,
        effective_url: str,
        acquired_at: str,
        z: int,
        x: int,
        y: int,
        size: int,
        sha256: str,
    ) -> dict[str, Any]:
        source = plan.source
        data = plan.definition.data
        record = {
            "record_schema_version": rec.RECORD_SCHEMA_VERSION,
            "acquisition_id": acquisition_id,
            "run_id": plan.run_id,
            "api_id": plan.api_id,
            "provider": thaw(source["provider"]),
            "data_name": source["name"],
            "data_type": "elevation_png",
            "requested_url": requested_url,
            "effective_url": effective_url,
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
            "pipeline": {"id": PIPELINE_ID, "version": PIPELINE_VERSION},
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

    # -- resume ----------------------------------------------------------
    def _inspect_existing(
        self, plan: DownloadPlan, area: ApiDataArea
    ) -> dict[tuple[int, int, int], Artifact]:
        """Classify what a previous attempt of this run left behind.

        Committed acquisitions (marker + record + artifact consistent) are reused
        without transfer. Anything uncommitted or inconsistent blocks the run as
        RECOVERY_REQUIRED; nothing is deleted or overwritten here.
        """
        run_id = plan.run_id
        acquisition_ids: set[str] = set()
        for parts in (("work", "download"), ("work", "acquisitions")):
            directory = area.path(*parts, run_id)
            if directory.exists():
                acquisition_ids.update(p.name for p in directory.iterdir())
        record_dir = area.path("records", "acquisitions", run_id)
        if record_dir.exists():
            for entry in record_dir.iterdir():
                if entry.name.startswith(".") or entry.suffix != ".json":
                    raise PipelineError("RECOVERY_REQUIRED", "unexpected record entry")
                acquisition_ids.add(entry.stem)

        done: dict[tuple[int, int, int], Artifact] = {}
        for acquisition_id in sorted(acquisition_ids):
            try:
                artifact = verify_commit(area, run_id, acquisition_id)
            except (PipelineError, StorageError) as exc:
                raise PipelineError("RECOVERY_REQUIRED", "uncommitted artifact") from exc
            pending = area.path("work", "download", run_id, acquisition_id)
            if pending.exists():
                raise PipelineError("RECOVERY_REQUIRED", "leftover part directory")
            record = parse_strict_json(
                area.read_bytes(area.path("records", "acquisitions", run_id, f"{acquisition_id}.json"))
            )
            if (
                record["effective_configuration"]["sha256"] != plan.effective_configuration_sha256
                or record["source_definition"]["source_ref"] != plan.source_ref
            ):
                raise PipelineError("RECOVERY_REQUIRED", "record from different configuration")
            tile = record["tile"]
            key = (tile["z"], tile["x"], tile["y"])
            if key in done:
                raise PipelineError("RECOVERY_REQUIRED", "duplicate acquisition for tile")
            done[key] = artifact
        return done


def verify_commit(area: ApiDataArea, run_id: str, acquisition_id: str) -> Artifact:
    """Check marker <-> record <-> artifact consistency; raise if not committed."""

    def fail(reason: str) -> PipelineError:
        return PipelineError("RECOVERY_REQUIRED", reason)

    try:
        uuid.UUID(acquisition_id)
    except ValueError as exc:
        raise fail("malformed acquisition id") from exc
    marker_path = area.path("records", "commits", f"{acquisition_id}.json")
    if not marker_path.is_file():
        raise fail("marker missing")
    try:
        marker = parse_strict_json(area.read_bytes(marker_path))
        rec.validate_marker(marker)
    except ConfigurationError as exc:
        raise fail("marker invalid") from exc
    record_path = area.path("records", "acquisitions", run_id, f"{acquisition_id}.json")
    artifact_path = area.path("work", "acquisitions", run_id, acquisition_id, ARTIFACT_NAME)
    if (
        marker["acquisition_id"] != acquisition_id
        or marker["record_ref"] != area.relative(record_path, "records")
        or marker["artifact_ref"] != area.relative(artifact_path, "work")
    ):
        raise fail("marker references mismatch")
    record_bytes = area.read_bytes(record_path)
    if hashlib.sha256(record_bytes).hexdigest() != marker["record_sha256"]:
        raise fail("record hash mismatch")
    try:
        record: Mapping[str, Any] = parse_strict_json(record_bytes)
        rec.validate_record(record)
    except ConfigurationError as exc:
        raise fail("record invalid") from exc
    artifact = area.read_bytes(artifact_path)
    sha256 = hashlib.sha256(artifact).hexdigest()
    if (
        record["acquisition_id"] != acquisition_id
        or record["run_id"] != run_id
        or sha256 != marker["artifact_sha256"]
        or sha256 != record["sha256"]
        or len(artifact) != record["size_bytes"]
    ):
        raise fail("artifact mismatch")
    return Artifact(
        artifact_id=acquisition_id,
        acquisition_id=acquisition_id,
        record_ref=marker["record_ref"],
        sha256=sha256,
        size_bytes=len(artifact),
    )

