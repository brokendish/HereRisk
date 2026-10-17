"""Publish stage (Phase 1-D.4): validated run -> published entities -> registry switch.

Flow (data-publish-v0.1 section 6, dataset-registry-v0.1 section 5):

  1. preconditions (nothing written on failure)
     * own ``publish`` authorization of the plan's context, bound to the same
       API / source / regions; its publication terms (licence, attribution URL)
     * Validate result is module=validate, SUCCESS, same run; one management
       region (multi-registry atomic publish is out of scope)
     * the whole evidence chain is re-verified: snapshot, Download evidence
       (``reconcile_run``), Normalize record, Validate record (SUCCESS, all
       checks passed, context profile), every candidate's size / SHA-256 /
       strict JSON / ``validate_candidate`` statistics
  2. under the registry lock of the prefecture (one publisher at a time):
     * copy each validated candidate byte-for-byte to
       ``rel/versions/<publication_version>/<dataset_id>.json`` (no clobber,
       re-read check)
     * build the new registry = current datasets (other ids) + this run's
       datasets; schema / id / reference checks; every referenced entity's
       checksum verified
     * write the immutable revision ``rel/registry/<pref>/revisions/<rev>.json``
     * **atomic switch**: replace ``rel/registry/<pref>/current.json`` -
       the publication becomes visible exactly here
     * write ``records/publications/<run>.json``
  Before the switch every failure leaves the old registry and data in place
  (new files are unreferenced, not published). Names are derived from the
  run_id, so a re-run after an interruption verifies and reuses what exists.

Publication eligibility of *real* GSI data (terms, redistribution, vertical
reference) is not decided: production publish grants are never issued by the
current ``ProductionAuthorizer``. Test-only grants must not be presented as
real publication approval.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Callable

from hererisk.common.authorization import Authorization
from hererisk.common.config import (
    MAX_CONFIG_BYTES,
    ConfigurationError,
    parse_strict_json,
    validate_with_schema,
)
from hererisk.common.logging import StructuredLogger
from hererisk.common.orchestrator import DownloadPlan
from hererisk.common.result import Artifact, ModuleResult, PipelineError, Status
from hererisk.common.storage import (
    PUBLISH_AREAS,
    READABLE_AREAS,
    ApiDataArea,
    Loc,
    StorageError,
)
from hererisk.elevation.download.download import MAX_RECORD_BYTES, plan_tiles, reconcile_run
from hererisk.elevation.normalize import stage as normalize_stage
from hererisk.elevation.normalize.stage import (
    MAX_CANDIDATE_BYTES,
    MAX_NORMALIZE_RECORD_BYTES,
    NormalizeStage,
    check_stage_authorization,
)
from hererisk.elevation.publish import registry as reg
from hererisk.elevation.validate import stage as validate_stage
from hererisk.elevation.validate.core import CandidateRejected, validate_candidate
from hererisk.elevation.validate.stage import CHECKS, MAX_VALIDATE_RECORD_BYTES, profile_for

MODULE = "publish"
SUCCESS_MESSAGE = "Publication committed"
RECORD_SCHEMA_VERSION = "0.1"
PUBLISH_WRITABLE = PUBLISH_AREAS | frozenset({("work", "locks")})
PUBLISH_READABLE = READABLE_AREAS | PUBLISH_AREAS


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json(area: ApiDataArea, loc: Loc, limit: int, schema: dict | None = None) -> tuple[bytes, Any]:
    try:
        data = area.read_bytes(loc, limit)
        doc = parse_strict_json(data)
        if schema is not None:
            validate_with_schema(doc, schema)
    except (StorageError, ConfigurationError) as exc:
        raise PipelineError("RECOVERY_REQUIRED", "evidence unreadable") from exc
    return data, doc


class PublishStage:
    api_id = "elevation"
    operation = MODULE

    def __init__(self, *, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self._clock = clock

    def run(self, plan: DownloadPlan, validate_result: ModuleResult, area: ApiDataArea,
            logger: StructuredLogger, *, authorization: Authorization) -> ModuleResult:
        log = logger.bind(module=MODULE, api_id=plan.api_id, run_id=plan.run_id)
        log.info("Publish requested")
        try:
            check_stage_authorization(plan, authorization, MODULE)
            terms = dict(authorization.policy)
            if set(terms) != {"license", "attribution_url"}:
                raise PipelineError("APPROVAL_REQUIRED", "publication terms missing")
            if not isinstance(validate_result, ModuleResult) or validate_result.module != "validate" \
                    or validate_result.status is not Status.SUCCESS \
                    or validate_result.run_id != plan.run_id:
                raise PipelineError("INVALID_INPUT", "validate result not a SUCCESS of this run")
            if len(plan.region_codes) != 1:
                raise PipelineError("INVALID_INPUT", "publish supports exactly one region")
            tiles, meta = self._verified_run(plan, validate_result, area)
            published = area.with_permissions(writable=PUBLISH_WRITABLE, readable=PUBLISH_READABLE)
        except (PipelineError, StorageError) as exc:
            log.error("Publish stopped", error_code=exc.error_code)
            return ModuleResult.error(plan.run_id, MODULE, exc.error_code)
        except Exception:  # noqa: BLE001
            log.error("Publish stopped", error_code="INTERNAL_ERROR")
            return ModuleResult.error(plan.run_id, MODULE, "INTERNAL_ERROR")

        with published:
            try:
                result = self._publish(plan, authorization, terms, tiles, meta, published)
            except (PipelineError, StorageError) as exc:
                log.error("Publish failed; current registry unchanged", error_code=exc.error_code)
                return ModuleResult.error(plan.run_id, MODULE, exc.error_code)
            except Exception:  # noqa: BLE001
                log.error("Publish failed", error_code="INTERNAL_ERROR")
                return ModuleResult.error(plan.run_id, MODULE, "INTERNAL_ERROR")
        log.info("Publish committed")
        return result

    # -- evidence chain -------------------------------------------------------------
    def _verified_run(self, plan: DownloadPlan, validate_result: ModuleResult,
                      area: ApiDataArea) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        NormalizeStage._check_snapshot(plan, area)
        verified = reconcile_run(area, plan)
        keys = plan_tiles(plan)
        if sorted(verified) != keys:
            raise PipelineError("RECOVERY_REQUIRED", "download evidence incomplete")
        _, validation = _json(area, area.path("records", "validations", f"{plan.run_id}.json"),
                              MAX_VALIDATE_RECORD_BYTES, validate_stage.RECORD_SCHEMA)
        expected_cfg = {"snapshot_ref": plan.effective_configuration_ref,
                        "sha256": plan.effective_configuration_sha256}
        if (validation["status"] != "SUCCESS" or validation["error_code"] is not None
                or validation["validation"]["checks"] != {n: "passed" for n in CHECKS}
                or validation["run_id"] != plan.run_id
                or validation["profile"] != profile_for(plan.authorization.context)
                or validation["source_raw_sha256"] != plan.definition.raw_sha256
                or validation["effective_configuration"] != expected_cfg):
            raise PipelineError("RECOVERY_REQUIRED", "validate record not a SUCCESS of this plan")
        ndata, normalization = _json(
            area, area.path("records", "normalizations", f"{plan.run_id}.json"),
            MAX_NORMALIZE_RECORD_BYTES, normalize_stage.RECORD_SCHEMA)
        ids = [verified[k].acquisition_id for k in keys]
        if (hashlib.sha256(ndata).hexdigest() != validation["validation"]["normalize_record_sha256"]
                or normalization["status"] != "SUCCESS"
                or normalization["outputs"] != validation["outputs"]
                or [o["acquisition_id"] for o in normalization["outputs"]] != ids
                or [i["artifact_sha256"] for i in normalization["inputs"]]
                != [verified[k].sha256 for k in keys]
                or [t["acquisition_id"] for t in validation["validation"]["tiles"]] != ids):
            raise PipelineError("RECOVERY_REQUIRED", "normalize record does not match")
        expected = [Artifact(o["acquisition_id"], o["acquisition_id"],
                             f"validations/{plan.run_id}.json", o["candidate_sha256"],
                             o["size_bytes"]) for o in normalization["outputs"]]
        if list(validate_result.artifacts) != expected:
            raise PipelineError("RECOVERY_REQUIRED", "validate result differs from record")

        tiles = []
        for key, output, stats in zip(keys, normalization["outputs"], validation["validation"]["tiles"]):
            data = self._candidate(area, plan, output)
            z, x, y = key
            try:
                result = validate_candidate(parse_strict_json(data), expected_tile={"z": z, "x": x, "y": y})
            except (ConfigurationError, CandidateRejected) as exc:
                raise PipelineError("VALIDATION_FAILED", "candidate no longer valid") from exc
            if {"acquisition_id": output["acquisition_id"], **result.stats(),
                    "warning": result.warning} != stats:
                raise PipelineError("RECOVERY_REQUIRED", "statistics differ")
            _, record = _json(area, area.path("records", "acquisitions", plan.run_id,
                                              f"{output['acquisition_id']}.json"), MAX_RECORD_BYTES)
            tiles.append({"key": key, "output": output, "record": record})
        meta = {"validated_at": validation["completed_at"], "profile": validation["profile"],
                "pipeline": normalization["pipeline"]}
        return tiles, meta

    @staticmethod
    def _candidate(area: ApiDataArea, plan: DownloadPlan, output: dict[str, Any]) -> bytes:
        loc = area.path("work", "normalized", plan.run_id, f"{output['acquisition_id']}.json")
        try:
            data = area.read_bytes(loc, MAX_CANDIDATE_BYTES)
        except StorageError as exc:
            raise PipelineError("STORAGE_INTEGRITY_FAILED", "candidate unreadable") from exc
        if len(data) != output["size_bytes"] or \
                hashlib.sha256(data).hexdigest() != output["candidate_sha256"]:
            raise PipelineError("STORAGE_INTEGRITY_FAILED", "candidate hash mismatch")
        return data

    # -- publish ------------------------------------------------------------------------
    def _dataset(self, plan: DownloadPlan, terms: dict[str, str], tile: dict[str, Any],
                 meta: dict[str, Any], version: str, published_at: str) -> dict[str, Any]:
        z, x, y = tile["key"]
        record, output = tile["record"], tile["output"]
        dataset_id = f"{plan.source_ref}-z{z}-{x}-{y}"
        source = plan.source
        return {
            "id": dataset_id,
            "name": f"{source['name']} Z{z}/{x}/{y}",
            "hazard": "elevation",
            "coverage": {"ref": f"xyz:{z}/{x}/{y}", "mode": reg.COVERAGE_MODE,
                         "bbox": reg.tile_bbox(z, x, y),
                         "prefectures": list(plan.region_codes), "crs": "EPSG:4326"},
            "source": {"provider": record["provider"]["name"],
                       "page_url": record["official_page_url"], "format": "png",
                       "retrieved_at": record["acquired_at"], "filename": f"{y}.png"},
            "acquisition": {"method": "http", "url": record["requested_url"],
                            "parameters": {"layer": "dem_png", "z": z, "x": x, "y": y,
                                           "acquisition_id": output["acquisition_id"],
                                           "source_sha256": record["sha256"]}},
            "pipeline": {"id": meta["pipeline"]["id"],
                         "name": "標高PNG正規化（整数cm JSON）",
                         "version": meta["pipeline"]["version"]},
            "validation": {"status": "passed", "profile": meta["profile"],
                           "validated_at": meta["validated_at"]},
            "publication": {"version": version,
                            "path": f"versions/{version}/{dataset_id}.json",
                            "format": reg.ENTITY_FORMAT, "published_at": published_at,
                            "filename": f"{dataset_id}.json",
                            "checksum": "sha256:" + output["candidate_sha256"]},
            "attribution": {"text": source["usage"]["attribution_text"],
                            "license": terms["license"], "url": terms["attribution_url"]},
        }

    def _publish(self, plan: DownloadPlan, authorization: Authorization, terms: dict[str, str],
                 tiles: list[dict[str, Any]], meta: dict[str, Any], area: ApiDataArea) -> ModuleResult:
        pref = plan.region_codes[0]
        version, revision = f"pub-{plan.run_id}", f"rev-{plan.run_id}"
        record_loc = area.path("records", "publications", f"{plan.run_id}.json")
        lock = area.path("work", "locks", f"publish-registry-{pref}.lock")
        with area.exclusive_lock(lock, blocking=True):
            if area.entry_exists(record_loc):
                return self._reuse(plan, area, record_loc, pref)
            current = reg.read_current(area, pref)
            if current is not None and current.registry["registry_revision"] == revision:
                # Switched before an interruption, record missing: finish it.
                datasets = [d for d in current.registry["datasets"]
                            if d["publication"]["version"] == version]
                return self._commit_record(plan, authorization, area, record_loc, pref,
                                           current, None, datasets)
            published_at = _utc(self._clock())
            new = [self._dataset(plan, terms, t, meta, version, published_at) for t in tiles]
            for dataset, tile in zip(new, tiles):
                self._write_entity(area, plan, dataset, tile["output"])
            new_ids = {d["id"] for d in new}
            kept = [d for d in (current.registry["datasets"] if current else [])
                    if d["id"] not in new_ids]
            document = {"schema_version": reg.REGISTRY_SCHEMA_VERSION, "prefecture_code": pref,
                        "registry_revision": revision,
                        "datasets": sorted(kept + new, key=lambda d: d["id"])}
            reg.check_registry(document, pref)
            for dataset in document["datasets"]:  # every referenced entity must be intact
                reg.read_entity(area, dataset)
            data = reg.to_bytes(document)
            rev_loc = reg.revision_loc(pref, revision)
            if area.entry_exists(rev_loc):
                if area.read_bytes(rev_loc, reg.MAX_REGISTRY_BYTES) != data:
                    raise PipelineError("RECOVERY_REQUIRED", "existing revision differs")
            else:
                area.write_new(rev_loc, data)
            pointer = {"schema_version": reg.POINTER_SCHEMA_VERSION, "prefecture_code": pref,
                       "registry_revision": revision,
                       "registry_sha256": hashlib.sha256(data).hexdigest(),
                       "previous_revision": current.registry["registry_revision"] if current else None}
            # Defensive: the registry must not have moved (we hold the lock).
            again = reg.read_current(area, pref)
            if (again.pointer if again else None) != (current.pointer if current else None):
                raise PipelineError("TARGET_BUSY", "registry changed concurrently")
            area.replace_pointer(reg.pointer_loc(pref), reg.to_bytes(pointer))  # publication point
            switched = reg.read_current(area, pref)
            return self._commit_record(plan, authorization, area, record_loc, pref, switched,
                                       current, new)

    @staticmethod
    def _write_entity(area: ApiDataArea, plan: DownloadPlan, dataset: dict[str, Any],
                      output: dict[str, Any]) -> None:
        source = area.path("work", "normalized", plan.run_id, f"{output['acquisition_id']}.json")
        data = area.read_bytes(source, MAX_CANDIDATE_BYTES)
        if hashlib.sha256(data).hexdigest() != output["candidate_sha256"]:
            raise PipelineError("STORAGE_INTEGRITY_FAILED", "candidate changed")
        loc = reg.entity_loc(dataset["publication"]["path"])
        if area.entry_exists(loc):
            reg.read_entity(area, dataset)  # resume: must be the identical entity
            return
        area.write_new(loc, data)
        reg.read_entity(area, dataset)

    def _commit_record(self, plan, authorization, area, record_loc, pref, switched, previous,
                       datasets) -> ModuleResult:
        record = {
            "schema_version": RECORD_SCHEMA_VERSION,
            "module": MODULE,
            "run_id": plan.run_id,
            "api_id": plan.api_id,
            "execution_context": authorization.context.value,
            "authorization_ref": authorization.authorization_ref,
            "status": "SUCCESS",
            "prefecture_code": pref,
            "registry_revision": switched.registry["registry_revision"],
            "registry_sha256": switched.pointer["registry_sha256"],
            "previous_revision": switched.pointer["previous_revision"],
            "datasets": [{"id": d["id"], "publication_version": d["publication"]["version"],
                          "path": d["publication"]["path"],
                          "checksum": d["publication"]["checksum"]} for d in datasets],
            "completed_at": _utc(self._clock()),
        }
        try:
            area.write_new(record_loc, reg.to_bytes(record))
        except StorageError as exc:
            # The switch already happened: publication is effective; only the
            # record is missing (a re-run completes it without re-publishing).
            raise PipelineError("RECORD_COMMIT_FAILED", "publication record") from exc
        return self._result(plan, area, datasets)

    def _reuse(self, plan, area, record_loc, pref) -> ModuleResult:
        _, record = _json(area, record_loc, MAX_CONFIG_BYTES)
        if record.get("status") != "SUCCESS" or record.get("run_id") != plan.run_id:
            raise PipelineError("RECOVERY_REQUIRED", "publication record not a SUCCESS")
        revision = record["registry_revision"]
        data = area.read_bytes(reg.revision_loc(pref, revision), reg.MAX_REGISTRY_BYTES)
        if hashlib.sha256(data).hexdigest() != record["registry_sha256"]:
            raise PipelineError("RECOVERY_REQUIRED", "published revision changed")
        registry = parse_strict_json(data)
        reg.check_registry(registry, pref)
        ids = {d["id"] for d in record["datasets"]}
        datasets = [d for d in registry["datasets"] if d["id"] in ids]
        if len(datasets) != len(ids):
            raise PipelineError("RECOVERY_REQUIRED", "published datasets missing")
        for dataset in datasets:
            reg.read_entity(area, dataset)
        return self._result(plan, area, datasets)

    @staticmethod
    def _result(plan: DownloadPlan, area: ApiDataArea,
                datasets: list[dict[str, Any]]) -> ModuleResult:
        artifacts = []
        for d in sorted(datasets, key=reg.tile_of):  # plan tile order (z, x, y)
            data = reg.read_entity(area, d)  # verified against the registry checksum
            artifacts.append(Artifact(
                artifact_id=d["id"],
                acquisition_id=d["acquisition"]["parameters"]["acquisition_id"],
                record_ref=f"publications/{plan.run_id}.json",
                sha256=d["publication"]["checksum"].split(":", 1)[1],
                size_bytes=len(data)))
        return ModuleResult(plan.run_id, MODULE, Status.SUCCESS, None, SUCCESS_MESSAGE,
                            tuple(artifacts))
