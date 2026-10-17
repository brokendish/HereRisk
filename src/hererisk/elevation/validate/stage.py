"""Validate stage: committed Normalize output -> profile checks -> Validate record.

Phase 1-B.3-B. Flow (contract sections 5, 6, 7):

  1. preconditions (no files written on failure):
     * own fixture ``validate`` authorization bound to the plan's API/source/regions
     * Normalize result is module=normalize, SUCCESS, same run
     * snapshot bytes equal the fixed plan; Download evidence (``reconcile_run``)
       equals the planned tile set
     * the Normalize record is a SUCCESS for this run / configuration whose
       inputs equal the verified Download evidence and whose outputs equal the
       Normalize result's artifacts
     * no Validate record yet for the run (a matching SUCCESS is re-verified
       and reused; anything else is RECOVERY_REQUIRED)
  2. per tile, in plan order: read the candidate (bounded), compare size and
     SHA-256 with the Normalize record (mismatch: STORAGE_INTEGRITY_FAILED),
     strict-parse it and run ``validate_candidate`` with the plan's integer
     tile as ``expected_tile`` (B2-F01); profile violations become
     VALIDATION_FAILED; record valid/nodata counts, min/max and ALL_NODATA
  3. store ``records/validations/<run>.json`` (SUCCESS) and re-read it

Failures after step 1 are recorded in the same Validate record (FAILED, with
the checks done so far); re-execution is then RECOVERY_REQUIRED. Candidates
are only read: never copied, modified, repaired or deleted. The caller owns the
per-source lock. SUCCESS means the fixture candidates passed the fixture
profile only; it is not a statement about real terrain or publication.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Callable

from hererisk.common.authorization import Authorization, ExecutionContext
from hererisk.common.config import ConfigurationError, parse_strict_json, validate_with_schema
from hererisk.common.logging import StructuredLogger
from hererisk.common.orchestrator import DownloadPlan
from hererisk.common.result import Artifact, ModuleResult, PipelineError, Status
from hererisk.common.storage import ApiDataArea, StorageError
from hererisk.elevation.download.download import MAX_RECORD_BYTES, plan_tiles, reconcile_run
from hererisk.elevation.normalize import stage as normalize_stage
from hererisk.elevation.normalize.stage import (
    MAX_CANDIDATE_BYTES,
    MAX_NORMALIZE_RECORD_BYTES,
    NormalizeStage,
    check_stage_authorization,
)
from hererisk.elevation.validate.core import PROFILE_ID, CandidateRejected, validate_candidate

MODULE = "validate"
# Same structural checks; the profile name records which data class was checked.
PRODUCTION_PROFILE_ID = "elevation-normalized-v0.1"


def profile_for(context: ExecutionContext) -> str:
    return PRODUCTION_PROFILE_ID if context is ExecutionContext.PRODUCTION else PROFILE_ID
PIPELINE_ID = "elevation-validate"
PIPELINE_VERSION = "fixture-0.1"
RECORD_SCHEMA_VERSION = "0.1"
SUCCESS_MESSAGE = "Validation committed"
MAX_VALIDATE_RECORD_BYTES = 1024 * 1024
# Contract section 5 check names, in order.
CHECKS = ("normalize_success", "input_correspondence", "candidate_integrity",
          "json_format", "tile_position", "values_nodata", "counts_stats")

_SHA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
_STATS_INT = {"type": "integer", "minimum": 0}
_CM = {"type": ["integer", "null"]}


def _obj(props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": list(props),
            "properties": props}


# Shares the common record header with the Normalize record; only module /
# pipeline / profile / validation differ.
_BASE = normalize_stage.RECORD_SCHEMA["properties"]
RECORD_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    **_obj({
        **{k: v for k, v in _BASE.items()},
        "module": {"const": MODULE},
        "pipeline": _obj({"id": {"const": PIPELINE_ID}, "version": {"const": PIPELINE_VERSION}}),
        "profile": {"enum": [PROFILE_ID, PRODUCTION_PROFILE_ID]},
        "validation": _obj({
            "normalize_record_ref": {"type": "string", "minLength": 1},
            "normalize_record_sha256": _SHA,
            "checks": _obj({name: {"enum": ["passed", "failed", "not_run"]} for name in CHECKS}),
            "tiles": {"type": "array", "items": _obj({
                "acquisition_id": _BASE["run_id"],
                "valid_count": _STATS_INT,
                "nodata_count": _STATS_INT,
                "min_cm": _CM,
                "max_cm": _CM,
                "warning": {"enum": [None, "ALL_NODATA"]},
            })},
        }),
    }),
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _record_bytes(record: dict[str, Any]) -> bytes:
    return (json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


class ValidateStage:
    api_id = "elevation"
    operation = MODULE
    pipeline = (PIPELINE_ID, PIPELINE_VERSION)

    def __init__(self, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._clock = clock

    def run(
        self,
        plan: DownloadPlan,
        normalize_result: ModuleResult,
        area: ApiDataArea,
        logger: StructuredLogger,
        *,
        authorization: Authorization,
    ) -> ModuleResult:
        log = logger.bind(module=MODULE, api_id=plan.api_id, run_id=plan.run_id)
        log.info("Validate requested")
        checks = {name: "not_run" for name in CHECKS}
        try:
            check_stage_authorization(plan, authorization, MODULE)
            ctx = self._preconditions(plan, normalize_result, area, authorization)
            checks["normalize_success"] = checks["input_correspondence"] = "passed"
            existing = self._existing(plan, area, ctx)
            if existing is not None:
                log.info("Validate result reused")
                return existing
        except (PipelineError, StorageError) as exc:
            log.error("Validate stopped", error_code=exc.error_code)
            return ModuleResult.error(plan.run_id, MODULE, exc.error_code)
        except Exception:  # noqa: BLE001 - never leak exception text
            log.error("Validate stopped", error_code="INTERNAL_ERROR")
            return ModuleResult.error(plan.run_id, MODULE, "INTERNAL_ERROR")

        tiles: list[dict[str, Any]] = []
        try:
            for key, out in zip(plan_tiles(plan), ctx["outputs"]):
                tiles.append(self._check_one(area, plan, key, out, checks))
            for name in CHECKS:
                checks[name] = "passed"
            record = self._record(plan, ctx, checks, tiles, Status.SUCCESS, None)
            self._commit_record(plan, area, record)
        except (PipelineError, StorageError) as exc:
            code = exc.error_code
            if code != "RECORD_COMMIT_FAILED":
                code = self._record_failure(plan, area, ctx, checks, tiles, code)
            log.error("Validate failed", error_code=code)
            return ModuleResult.error(plan.run_id, MODULE, code)
        except Exception:  # noqa: BLE001 - never leak exception text
            code = self._record_failure(plan, area, ctx, checks, tiles, "INTERNAL_ERROR")
            log.error("Validate failed", error_code=code)
            return ModuleResult.error(plan.run_id, MODULE, code)
        for tile in tiles:
            if tile["warning"]:
                log.warning("Tile has no valid elevation values")
        log.info("Validate committed")
        return self._success(plan, ctx["outputs"])

    # -- preconditions -------------------------------------------------------------
    def _preconditions(self, plan: DownloadPlan, result: ModuleResult, area: ApiDataArea,
                       authorization: Authorization) -> dict[str, Any]:
        if not isinstance(result, ModuleResult) or result.module != "normalize" \
                or result.status is not Status.SUCCESS or result.run_id != plan.run_id:
            raise PipelineError("INVALID_INPUT", "normalize result not a SUCCESS of this run")
        NormalizeStage._check_snapshot(plan, area)
        verified = reconcile_run(area, plan)
        if sorted(verified) != plan_tiles(plan):
            raise PipelineError("RECOVERY_REQUIRED", "download evidence incomplete")

        loc = area.path("records", "normalizations", f"{plan.run_id}.json")
        try:
            data = area.read_bytes(loc, MAX_NORMALIZE_RECORD_BYTES)
            record = parse_strict_json(data)
            validate_with_schema(record, normalize_stage.RECORD_SCHEMA)
        except (StorageError, ConfigurationError) as exc:
            raise PipelineError("RECOVERY_REQUIRED", "normalize record unreadable") from exc
        if (
            record["status"] != "SUCCESS"
            or record["run_id"] != plan.run_id
            or record["source_raw_sha256"] != plan.definition.raw_sha256
            or record["effective_configuration"] != {
                "snapshot_ref": plan.effective_configuration_ref,
                "sha256": plan.effective_configuration_sha256}
        ):
            raise PipelineError("RECOVERY_REQUIRED", "normalize record not for this plan")
        for key, entry in zip(plan_tiles(plan), record["inputs"], strict=False):
            art = verified[key]
            record_sha, _ = area.hash_file(
                area.path("records", "acquisitions", plan.run_id, f"{art.acquisition_id}.json"),
                MAX_RECORD_BYTES)
            if entry != {"acquisition_id": art.acquisition_id, "record_ref": art.record_ref,
                         "record_sha256": record_sha, "artifact_sha256": art.sha256,
                         "size_bytes": art.size_bytes,
                         "tile": {"z": key[0], "x": key[1], "y": key[2]}}:
                raise PipelineError("RECOVERY_REQUIRED", "normalize inputs differ from evidence")
        outputs = record["outputs"]
        ids = [verified[k].acquisition_id for k in plan_tiles(plan)]
        if len(record["inputs"]) != len(ids) or [o["acquisition_id"] for o in outputs] != ids:
            raise PipelineError("RECOVERY_REQUIRED", "normalize outputs differ from plan")
        expected_artifacts = [
            Artifact(o["acquisition_id"], o["acquisition_id"],
                     f"normalizations/{plan.run_id}.json", o["candidate_sha256"], o["size_bytes"])
            for o in outputs]
        if list(result.artifacts) != expected_artifacts:
            raise PipelineError("RECOVERY_REQUIRED", "normalize result differs from record")
        return {"authorization": authorization, "outputs": outputs,
                "normalize_record_ref": f"normalizations/{plan.run_id}.json",
                "normalize_record_sha256": hashlib.sha256(data).hexdigest()}

    def _existing(self, plan: DownloadPlan, area: ApiDataArea,
                  ctx: dict[str, Any]) -> ModuleResult | None:
        loc = area.path("records", "validations", f"{plan.run_id}.json")
        if not area.entry_exists(loc):
            if any(n.startswith(f".{plan.run_id}.json")
                   for n in area.list_dir(area.path("records", "validations"))):
                raise PipelineError("RECOVERY_REQUIRED", "uncommitted validate record")
            return None
        try:
            record = parse_strict_json(area.read_bytes(loc, MAX_VALIDATE_RECORD_BYTES))
            validate_with_schema(record, RECORD_SCHEMA)
        except (StorageError, ConfigurationError) as exc:
            raise PipelineError("RECOVERY_REQUIRED", "validate record invalid") from exc
        expected = self._record(plan, ctx, {n: "passed" for n in CHECKS},
                                record["validation"]["tiles"], Status.SUCCESS, None)
        expected["completed_at"] = record["completed_at"]
        if record != expected or len(record["validation"]["tiles"]) != len(ctx["outputs"]):
            raise PipelineError("RECOVERY_REQUIRED", "validate record not a matching SUCCESS")
        # Re-check candidate integrity and statistics; never trust stored stats alone.
        checks = {n: "not_run" for n in CHECKS}
        for key, out, stored in zip(plan_tiles(plan), ctx["outputs"], record["validation"]["tiles"]):
            if self._check_one(area, plan, key, out, checks) != stored:
                raise PipelineError("RECOVERY_REQUIRED", "validate statistics differ")
        return self._success(plan, ctx["outputs"])

    # -- per tile ----------------------------------------------------------------------
    @staticmethod
    def _check_one(area: ApiDataArea, plan: DownloadPlan, key, out: dict[str, Any],
                   checks: dict[str, str]) -> dict[str, Any]:
        loc = area.path("work", "normalized", plan.run_id, f"{out['acquisition_id']}.json")
        if out["candidate_ref"] != area.relative(loc, "work"):
            raise PipelineError("RECOVERY_REQUIRED", "candidate reference mismatch")
        try:
            data = area.read_bytes(loc, MAX_CANDIDATE_BYTES)
        except StorageError as exc:
            checks["candidate_integrity"] = "failed"
            raise PipelineError("STORAGE_INTEGRITY_FAILED", "candidate unreadable") from exc
        if len(data) != out["size_bytes"] or hashlib.sha256(data).hexdigest() != out["candidate_sha256"]:
            checks["candidate_integrity"] = "failed"
            raise PipelineError("STORAGE_INTEGRITY_FAILED", "candidate hash mismatch")
        try:
            candidate = parse_strict_json(data)
        except ConfigurationError as exc:
            checks["json_format"] = "failed"
            raise PipelineError("VALIDATION_FAILED", "candidate JSON invalid") from exc
        z, x, y = key  # integers from the verified fixed plan (B2-F01)
        try:
            result = validate_candidate(candidate, expected_tile={"z": z, "x": x, "y": y})
        except CandidateRejected as exc:
            checks[{"keys": "json_format", "format": "json_format", "dimensions": "json_format",
                    "tile": "tile_position", "values": "values_nodata"}.get(exc.check,
                                                                           "json_format")] = "failed"
            raise PipelineError("VALIDATION_FAILED", f"profile check {exc.check}") from exc
        stats = result.stats()
        if stats["valid_count"] + stats["nodata_count"] != 65536:
            checks["counts_stats"] = "failed"
            raise PipelineError("VALIDATION_FAILED", "counts do not add up")
        return {"acquisition_id": out["acquisition_id"], **stats, "warning": result.warning}

    # -- record -------------------------------------------------------------------------
    def _record(self, plan: DownloadPlan, ctx: dict[str, Any], checks: dict[str, str],
                tiles: list[dict[str, Any]], status: Status, error_code: str | None) -> dict:
        done = {t["acquisition_id"] for t in tiles}
        record = {
            "schema_version": RECORD_SCHEMA_VERSION,
            "module": MODULE,
            "run_id": plan.run_id,
            "api_id": plan.api_id,
            "execution_context": ctx["authorization"].context.value,
            "authorization_ref": ctx["authorization"].authorization_ref,
            "pipeline": {"id": PIPELINE_ID, "version": PIPELINE_VERSION},
            "profile": profile_for(plan.authorization.context),
            "source_raw_sha256": plan.definition.raw_sha256,
            "effective_configuration": {
                "snapshot_ref": plan.effective_configuration_ref,
                "sha256": plan.effective_configuration_sha256,
            },
            "status": status.value,
            "error_code": error_code,
            "completed_at": self._clock().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "inputs": [],  # Download inputs are referenced through the Normalize record
            "outputs": [o for o in ctx["outputs"] if o["acquisition_id"] in done],
            "validation": {
                "normalize_record_ref": ctx["normalize_record_ref"],
                "normalize_record_sha256": ctx["normalize_record_sha256"],
                "checks": dict(checks),
                "tiles": list(tiles),
            },
        }
        try:
            validate_with_schema(record, RECORD_SCHEMA)
        except ConfigurationError as exc:
            raise PipelineError("INTERNAL_ERROR", "validate record failed own schema") from exc
        return record

    def _commit_record(self, plan: DownloadPlan, area: ApiDataArea, record: dict) -> None:
        loc = area.path("records", "validations", f"{plan.run_id}.json")
        data = _record_bytes(record)
        try:
            area.write_new(loc, data)
            if area.read_bytes(loc, MAX_VALIDATE_RECORD_BYTES) != data:
                raise PipelineError("RECORD_COMMIT_FAILED", "record re-read mismatch")
        except StorageError as exc:
            raise PipelineError("RECORD_COMMIT_FAILED", "validate record") from exc

    def _record_failure(self, plan, area, ctx, checks, tiles, code: str) -> str:
        try:
            self._commit_record(plan, area,
                                self._record(plan, ctx, checks, tiles, Status.FAILED, code))
        except PipelineError as exc:
            return exc.error_code
        return code

    @staticmethod
    def _success(plan: DownloadPlan, outputs: list[dict[str, Any]]) -> ModuleResult:
        record_ref = f"validations/{plan.run_id}.json"
        artifacts = tuple(
            Artifact(o["acquisition_id"], o["acquisition_id"], record_ref,
                     o["candidate_sha256"], o["size_bytes"])
            for o in outputs)
        return ModuleResult(plan.run_id, MODULE, Status.SUCCESS, None, SUCCESS_MESSAGE, artifacts)
