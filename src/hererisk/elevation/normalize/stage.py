"""Normalize stage: committed Download evidence -> stored candidates -> Normalize record.

Phase 1-B.3-A. Flow (contract sections 3, 6, 7):

  1. preconditions (no files written on failure):
     * the Download result is module=download, status=SUCCESS, same run_id
     * fixture execution context (production stays BLOCKED)
     * policy ``max_tile_bytes`` is a positive int (B1-F01 boundary)
     * the run's ``source.json`` / ``effective.json`` snapshot bytes equal the
       fixed plan (no re-reading of the latest configuration)
     * ``reconcile_run`` verifies marker / Record / artifact against the plan and
       its tile set equals the planned tiles exactly; the Download result's
       artifacts must equal the verified ones
     * the run has no Normalize record and no uncommitted candidates yet
       (a valid SUCCESS record is re-verified and its result returned)
  2. per tile, in plan order: read the PNG once, bounded, check that the same
     bytes have the verified size / SHA-256, ``normalize_tile``, store the
     compact UTF-8 candidate at ``work/normalized/<run>/<acq>.json`` (no
     clobber), re-read it and compare the hash
  3. store ``records/normalizations/<run>.json`` (SUCCESS) and re-read it

Failures after step 1 are recorded in the same Normalize record with
status FAILED and the candidates completed so far; such a run is then
RECOVERY_REQUIRED on re-execution. Nothing is overwritten, deleted or repaired.

The caller (later: the common Orchestrator) owns the per-source lock and runs
stages serially on a dedicated fixture root; this module takes no lock.
Downloaded originals, Acquisition Records, markers and snapshots are only read.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable

from hererisk.common.authorization import Authorization, ExecutionContext
from hererisk.common.config import ConfigurationError, MAX_CONFIG_BYTES, parse_strict_json, validate_with_schema
from hererisk.common.logging import StructuredLogger
from hererisk.common.orchestrator import DownloadPlan
from hererisk.common.result import Artifact, ModuleResult, PipelineError, Status
from hererisk.common.storage import ApiDataArea, StorageError
from hererisk.elevation.download.download import (
    ARTIFACT_NAME,
    MAX_RECORD_BYTES,
    TileKey,
    plan_tiles,
    reconcile_run,
)
from hererisk.elevation.normalize.convert import FORMAT, normalize_tile

MODULE = "normalize"
PIPELINE_ID = "elevation-normalize"
PIPELINE_VERSION = "fixture-0.1"
RECORD_SCHEMA_VERSION = "0.1"
SUCCESS_MESSAGE = "Normalization committed"
MAX_CANDIDATE_BYTES = 1024 * 1024
MAX_NORMALIZE_RECORD_BYTES = 1024 * 1024

_UUID = {"type": "string",
         "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"}
_SHA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_REL = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._/-]*$", "not": {"pattern": "\\.\\."}}
_INT = {"type": "integer", "minimum": 0}


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(props),
            "properties": props}


_TILE = _obj({"z": _INT, "x": _INT, "y": _INT})
RECORD_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    **_obj({
        "schema_version": {"const": RECORD_SCHEMA_VERSION},
        "module": {"const": MODULE},
        "run_id": _UUID,
        "api_id": {"const": "elevation"},
        "execution_context": {"enum": ["fixture", "production", "private_experiment"]},
        "authorization_ref": {"type": "string", "minLength": 1},
        "pipeline": _obj({"id": {"const": PIPELINE_ID}, "version": {"const": PIPELINE_VERSION}}),
        "profile": {"const": FORMAT},
        "source_raw_sha256": _SHA,
        "effective_configuration": _obj({"snapshot_ref": _REL, "sha256": _SHA}),
        "status": {"enum": ["SUCCESS", "FAILED"]},
        "error_code": {"type": ["string", "null"]},
        "completed_at": {"type": "string",
                         "pattern": "^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"},
        "inputs": {"type": "array", "items": _obj({
            "acquisition_id": _UUID, "record_ref": _REL, "record_sha256": _SHA,
            "artifact_sha256": _SHA, "size_bytes": {"type": "integer", "minimum": 1},
            "tile": _TILE})},
        "outputs": {"type": "array", "items": _obj({
            "acquisition_id": _UUID, "candidate_ref": _REL, "candidate_sha256": _SHA,
            "size_bytes": {"type": "integer", "minimum": 1}})},
        "validation": {"type": "null"},
    }),
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def candidate_bytes(candidate: dict[str, Any]) -> bytes:
    """Compact UTF-8 JSON in contract key order (format, tile, width, height, values_cm)."""
    return json.dumps(candidate, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _record_bytes(record: dict[str, Any]) -> bytes:
    return (json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def _max_png_bytes(plan: DownloadPlan) -> int:
    value = plan.authorization.policy.get("max_tile_bytes")
    if type(value) is not int or value <= 0:
        raise PipelineError("INVALID_CONFIGURATION", "max_tile_bytes must be a positive int")
    return value


STAGE_CONTEXTS = (ExecutionContext.FIXTURE, ExecutionContext.PRODUCTION,
                  ExecutionContext.PRIVATE_EXPERIMENT)


def check_stage_authorization(plan: DownloadPlan, authorization: Authorization,
                              operation: str) -> None:
    """The stage's own fixture authorization, bound to the same API/source/regions."""
    if not isinstance(authorization, Authorization) \
            or authorization.context is not plan.authorization.context \
            or authorization.context not in STAGE_CONTEXTS \
            or authorization.operation != operation \
            or authorization.api_id != plan.api_id \
            or authorization.source_ref != plan.source_ref \
            or tuple(sorted(authorization.region_codes)) != tuple(plan.region_codes):
        raise PipelineError("APPROVAL_REQUIRED", f"{operation} not authorized for this plan")


class NormalizeStage:
    api_id = "elevation"
    operation = MODULE
    pipeline = (PIPELINE_ID, PIPELINE_VERSION)

    def __init__(self, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock

    def run(
        self,
        plan: DownloadPlan,
        download_result: ModuleResult,
        area: ApiDataArea,
        logger: StructuredLogger,
        *,
        authorization: Authorization,
    ) -> ModuleResult:
        log = logger.bind(module=MODULE, api_id=plan.api_id, run_id=plan.run_id)
        log.info("Normalize requested")
        try:
            check_stage_authorization(plan, authorization, MODULE)
            self._authorization = authorization
            inputs, verified = self._preconditions(plan, download_result, area)
            existing = self._existing(plan, area, inputs)
            if existing is not None:
                log.info("Normalize result reused")
                return existing
        except (PipelineError, StorageError) as exc:
            log.error("Normalize stopped", error_code=exc.error_code)
            return ModuleResult.error(plan.run_id, MODULE, exc.error_code)
        except Exception:  # noqa: BLE001 - never leak exception text
            log.error("Normalize stopped", error_code="INTERNAL_ERROR")
            return ModuleResult.error(plan.run_id, MODULE, "INTERNAL_ERROR")

        outputs: list[dict[str, Any]] = []
        try:
            for key in plan_tiles(plan):
                outputs.append(self._convert_one(plan, area, key, verified[key]))
            record = self._record(plan, inputs, outputs, Status.SUCCESS, None)
            self._commit_record(plan, area, record)
        except (PipelineError, StorageError) as exc:
            code = exc.error_code
            if code != "RECORD_COMMIT_FAILED":
                code = self._record_failure(plan, area, inputs, outputs, code)
            log.error("Normalize failed", error_code=code)
            return ModuleResult.error(plan.run_id, MODULE, code)
        except Exception:  # noqa: BLE001 - never leak exception text
            code = self._record_failure(plan, area, inputs, outputs, "INTERNAL_ERROR")
            log.error("Normalize failed", error_code=code)
            return ModuleResult.error(plan.run_id, MODULE, code)
        log.info("Normalize committed")
        return self._success(plan, outputs)

    # -- preconditions -------------------------------------------------------------
    def _preconditions(
        self, plan: DownloadPlan, result: ModuleResult, area: ApiDataArea
    ) -> tuple[list[dict[str, Any]], dict[TileKey, Artifact]]:
        if plan.api_id != self.api_id:
            raise PipelineError("INVALID_INPUT", "unexpected api")
        if not isinstance(result, ModuleResult) or result.module != "download" \
                or result.status is not Status.SUCCESS or result.run_id != plan.run_id:
            raise PipelineError("INVALID_INPUT", "download result not a SUCCESS of this run")
        if plan.authorization.context not in STAGE_CONTEXTS:
            raise PipelineError("APPROVAL_REQUIRED", "unknown execution context")
        _max_png_bytes(plan)
        self._check_snapshot(plan, area)
        verified = reconcile_run(area, plan)  # marker / Record / artifact vs fixed plan
        if sorted(verified) != plan_tiles(plan):
            raise PipelineError("RECOVERY_REQUIRED", "download evidence incomplete")
        if list(result.artifacts) != [verified[k] for k in plan_tiles(plan)]:
            raise PipelineError("RECOVERY_REQUIRED", "result differs from verified evidence")
        inputs = []
        for key in plan_tiles(plan):
            art = verified[key]
            record_loc = area.path("records", "acquisitions", plan.run_id,
                                   f"{art.acquisition_id}.json")
            record_sha, _ = area.hash_file(record_loc, MAX_RECORD_BYTES)
            inputs.append({
                "acquisition_id": art.acquisition_id,
                "record_ref": art.record_ref,
                "record_sha256": record_sha,
                "artifact_sha256": art.sha256,
                "size_bytes": art.size_bytes,
                "tile": {"z": key[0], "x": key[1], "y": key[2]},
            })
        return inputs, verified

    @staticmethod
    def _check_snapshot(plan: DownloadPlan, area: ApiDataArea) -> None:
        directory = area.path("records", "configurations", plan.run_id)
        try:
            source = area.read_bytes(directory / "source.json", MAX_CONFIG_BYTES)
            effective = area.read_bytes(directory / "effective.json", MAX_CONFIG_BYTES)
        except StorageError as exc:
            raise PipelineError("RECOVERY_REQUIRED", "snapshot unreadable") from exc
        if source != plan.definition.raw_bytes or \
                hashlib.sha256(effective).hexdigest() != plan.effective_configuration_sha256:
            raise PipelineError("RECOVERY_REQUIRED", "snapshot differs from fixed plan")

    def _existing(
        self, plan: DownloadPlan, area: ApiDataArea, inputs: list[dict[str, Any]]
    ) -> ModuleResult | None:
        """Re-verify a previous attempt; None if there is none at all."""
        record_loc = area.path("records", "normalizations", f"{plan.run_id}.json")
        candidates_dir = area.path("work", "normalized", plan.run_id)
        names = area.list_dir(candidates_dir)
        if not area.entry_exists(record_loc):
            if names or any(n.startswith(f".{plan.run_id}.json") for n in
                            area.list_dir(area.path("records", "normalizations"))):
                raise PipelineError("RECOVERY_REQUIRED", "uncommitted normalize output")
            return None
        try:
            record = parse_strict_json(area.read_bytes(record_loc, MAX_NORMALIZE_RECORD_BYTES))
            validate_with_schema(record, RECORD_SCHEMA)
        except (StorageError, ConfigurationError) as exc:
            raise PipelineError("RECOVERY_REQUIRED", "normalize record invalid") from exc
        expected = self._record(plan, inputs, record["outputs"], Status.SUCCESS, None)
        expected["completed_at"] = record["completed_at"]
        if record != expected:
            raise PipelineError("RECOVERY_REQUIRED", "normalize record not a matching SUCCESS")
        outputs = record["outputs"]
        wanted = [f"{i['acquisition_id']}.json" for i in inputs]
        if sorted(names) != sorted(wanted) or [o["acquisition_id"] for o in outputs] != \
                [i["acquisition_id"] for i in inputs]:
            raise PipelineError("RECOVERY_REQUIRED", "candidate set differs from record")
        for out in outputs:
            loc = area.path("work", "normalized", plan.run_id, f"{out['acquisition_id']}.json")
            if out["candidate_ref"] != area.relative(loc, "work"):
                raise PipelineError("RECOVERY_REQUIRED", "candidate reference mismatch")
            try:
                sha, size = area.hash_file(loc, MAX_CANDIDATE_BYTES)
            except StorageError as exc:
                raise PipelineError("RECOVERY_REQUIRED", "candidate unreadable") from exc
            if (sha, size) != (out["candidate_sha256"], out["size_bytes"]):
                raise PipelineError("RECOVERY_REQUIRED", "candidate hash mismatch")
        return self._success(plan, outputs)

    # -- conversion ------------------------------------------------------------------
    def _convert_one(
        self, plan: DownloadPlan, area: ApiDataArea, key: TileKey, artifact: Artifact
    ) -> dict[str, Any]:
        max_png = _max_png_bytes(plan)
        acq = artifact.acquisition_id
        png_loc = area.path("work", "acquisitions", plan.run_id, acq, ARTIFACT_NAME)
        png_bytes = area.read_bytes(png_loc, max_png)
        # Decode exactly the bytes whose identity was verified.
        if len(png_bytes) != artifact.size_bytes or \
                hashlib.sha256(png_bytes).hexdigest() != artifact.sha256:
            raise PipelineError("STORAGE_INTEGRITY_FAILED", "original changed since verification")
        z, x, y = key
        data = candidate_bytes(normalize_tile(png_bytes, {"z": z, "x": x, "y": y},
                                              max_png_bytes=max_png))
        if len(data) > MAX_CANDIDATE_BYTES:
            raise PipelineError("SIZE_INVALID", "candidate over size limit")
        loc = area.path("work", "normalized", plan.run_id, f"{acq}.json")
        area.write_new(loc, data)
        sha = hashlib.sha256(data).hexdigest()
        if area.hash_file(loc, MAX_CANDIDATE_BYTES) != (sha, len(data)):
            raise PipelineError("STORAGE_INTEGRITY_FAILED", "candidate re-read mismatch")
        return {"acquisition_id": acq, "candidate_ref": area.relative(loc, "work"),
                "candidate_sha256": sha, "size_bytes": len(data)}

    # -- record ------------------------------------------------------------------------
    def _record(self, plan: DownloadPlan, inputs: list[dict[str, Any]],
                outputs: list[dict[str, Any]], status: Status, error_code: str | None) -> dict:
        record = {
            "schema_version": RECORD_SCHEMA_VERSION,
            "module": MODULE,
            "run_id": plan.run_id,
            "api_id": plan.api_id,
            "execution_context": plan.authorization.context.value,
            "authorization_ref": self._authorization.authorization_ref,
            "pipeline": {"id": PIPELINE_ID, "version": PIPELINE_VERSION},
            "profile": FORMAT,
            "source_raw_sha256": plan.definition.raw_sha256,
            "effective_configuration": {
                "snapshot_ref": plan.effective_configuration_ref,
                "sha256": plan.effective_configuration_sha256,
            },
            "status": status.value,
            "error_code": error_code,
            "completed_at": self._clock().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "inputs": inputs,
            "outputs": list(outputs),
            "validation": None,
        }
        try:
            validate_with_schema(record, RECORD_SCHEMA)
        except ConfigurationError as exc:
            raise PipelineError("INTERNAL_ERROR", "normalize record failed own schema") from exc
        return record

    def _commit_record(self, plan: DownloadPlan, area: ApiDataArea, record: dict) -> None:
        loc = area.path("records", "normalizations", f"{plan.run_id}.json")
        data = _record_bytes(record)
        try:
            area.write_new(loc, data)
            if area.read_bytes(loc, MAX_NORMALIZE_RECORD_BYTES) != data:
                raise PipelineError("RECORD_COMMIT_FAILED", "record re-read mismatch")
        except StorageError as exc:
            raise PipelineError("RECORD_COMMIT_FAILED", "normalize record") from exc

    def _record_failure(self, plan, area, inputs, outputs, code: str) -> str:
        try:
            self._commit_record(plan, area, self._record(plan, inputs, outputs, Status.FAILED, code))
        except PipelineError as exc:
            return exc.error_code
        return code

    @staticmethod
    def _success(plan: DownloadPlan, outputs: list[dict[str, Any]]) -> ModuleResult:
        record_ref = f"normalizations/{plan.run_id}.json"
        artifacts = tuple(
            Artifact(artifact_id=o["acquisition_id"], acquisition_id=o["acquisition_id"],
                     record_ref=record_ref, sha256=o["candidate_sha256"],
                     size_bytes=o["size_bytes"])
            for o in outputs
        )
        return ModuleResult(plan.run_id, MODULE, Status.SUCCESS, None, SUCCESS_MESSAGE, artifacts)

