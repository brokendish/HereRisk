"""Common Orchestrator (minimal: download operation only).

Responsibilities implemented here: run_id issuance, receipt of the validated
configuration, target (api / region / source_ref) checks, authorization and
execution-context checks, per-``(api_id, source_ref)`` exclusion, persisting the
fixed configuration snapshot, invoking the API's Download module and returning
its result.

This Orchestrator never starts Normalize / Validate / Publish / Generation; the
next stage is decided by a caller only when the result is SUCCESS.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from hererisk.common.authorization import Authorization, Authorizer, ExecutionContext
from hererisk.common.config import (
    MAX_CONFIG_BYTES,
    PREFECTURE_CODES,
    ConfigSnapshot,
    ConfigurationError,
    ConfigurationManager,
    assert_persistable,
    sha256_hex,
    thaw,
)
from hererisk.common.logging import StructuredLogger
from hererisk.common.result import ModuleResult, PipelineError
from hererisk.common.storage import (
    DOWNLOAD_AREAS,
    PRODUCTION_DATA_ROOT,
    ApiDataArea,
    StorageError,
    is_within,
)

MODULE = "download"
OPERATION = "download"
EFFECTIVE_SCHEMA_VERSION = "0.1"
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_SOURCE_REF_RE = re.compile(r"^[a-z][a-z0-9-]*$")


@dataclass(frozen=True)
class DownloadRequest:
    """Management request: only target identification is accepted."""

    api_id: str
    region_codes: tuple[str, ...]
    source_ref: str
    resume_run_id: str | None = None


@dataclass(frozen=True)
class DownloadPlan:
    """Fixed input handed to an API Download module (contract 4.1)."""

    run_id: str
    api_id: str
    source_ref: str
    region_codes: tuple[str, ...]
    definition: ConfigSnapshot
    effective_configuration_ref: str
    effective_configuration_sha256: str
    authorization: Authorization
    resume: bool

    @property
    def source(self) -> Mapping[str, Any]:
        return self.definition.data["sources"][self.source_ref]


class DownloadModule(Protocol):
    api_id: str
    pipeline: tuple[str, str]
    transport_context: ExecutionContext

    def preflight(self, plan: DownloadPlan) -> None:
        """Validate acquisition-specific preconditions without any I/O."""

    def reserve_capacity(self, plan: DownloadPlan, area: ApiDataArea) -> str:
        """Reserve one acquisition slot (or raise) before a new run persists anything."""

    def execute(
        self,
        plan: DownloadPlan,
        area: ApiDataArea,
        logger: StructuredLogger,
        *,
        reserved_acquisition_id: str | None = None,
    ) -> ModuleResult: ...


def new_run_id() -> str:
    return str(uuid.uuid4())


def _canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


class Orchestrator:
    def __init__(
        self,
        *,
        config_manager: ConfigurationManager,
        authorizer: Authorizer,
        modules: Mapping[str, DownloadModule],
        data_root: Path,
        logger: StructuredLogger,
        id_factory: Callable[[], str] = new_run_id,
        area_factory: Callable[[Path, str], ApiDataArea] = ApiDataArea,
    ) -> None:
        self._config = config_manager
        self._authorizer = authorizer
        self._modules = dict(modules)
        self._data_root = Path(data_root)
        self._logger = logger
        self._id_factory = id_factory
        self._area_factory = area_factory

    def run_download(self, request: DownloadRequest) -> ModuleResult:
        run_id = self._id_factory()
        if request.resume_run_id is not None:
            if not _UUID_RE.match(request.resume_run_id):
                return self._finish(run_id, request.api_id, "INVALID_INPUT")
            run_id = request.resume_run_id
        log = self._logger.bind(module=MODULE, api_id=self._log_api(request.api_id), run_id=run_id)
        log.info("Download requested")
        try:
            module = self._check_request(request)
            definition = self._load_definition(request.api_id)
            self._check_target(request, definition, module)
            authorization = self._authorize(request, definition, module)
            self._check_data_root(authorization)
            effective_doc = self._effective_document(
                run_id, request, definition, authorization, module
            )
            try:
                # Nothing is persisted unless every saved value is allowed (F08).
                assert_persistable(effective_doc)
            except ConfigurationError as exc:
                raise PipelineError("INVALID_CONFIGURATION", "not persistable") from exc
            effective = _canonical_json(effective_doc)
            area = self._area_factory(self._data_root, request.api_id)
            with area:
                self._check_pinned_root(area, authorization)
                self._prepare_area(area)
                result = self._run_locked(area, run_id, request, definition, authorization,
                                          module, effective, log)
        except (PipelineError, StorageError) as exc:
            return self._finish(run_id, request.api_id, exc.error_code)
        except Exception:  # noqa: BLE001 - never leak exception text to users
            return self._finish(run_id, request.api_id, "INTERNAL_ERROR")
        self._log_result(log, result)
        return result

    def _run_locked(
        self,
        area: ApiDataArea,
        run_id: str,
        request: DownloadRequest,
        definition: ConfigSnapshot,
        authorization: Authorization,
        module: DownloadModule,
        effective: bytes,
        log: StructuredLogger,
    ) -> ModuleResult:
        plan = DownloadPlan(
            run_id=run_id,
            api_id=request.api_id,
            source_ref=request.source_ref,
            region_codes=tuple(sorted(request.region_codes)),
            definition=definition,
            effective_configuration_ref=f"configurations/{run_id}/effective.json",
            effective_configuration_sha256=sha256_hex(effective),
            authorization=authorization,
            resume=request.resume_run_id is not None,
        )
        module.preflight(plan)
        lock = area.path("work", "locks", f"{OPERATION}-{request.source_ref}.lock")
        with area.exclusive_lock(lock):
            # Capacity is checked and a slot reserved before anything is
            # persisted for a new run (R1-02); resumes persist nothing new.
            reserved = None if plan.resume else module.reserve_capacity(plan, area)
            self._persist_snapshot(area, plan, effective)
            return module.execute(plan, area, log, reserved_acquisition_id=reserved)

    # -- steps ---------------------------------------------------------
    def _check_request(self, request: DownloadRequest) -> DownloadModule:
        module = self._modules.get(request.api_id)
        if module is None or module.api_id != request.api_id:
            raise PipelineError("INVALID_INPUT", "unknown api_id")
        codes = request.region_codes
        if (
            not codes
            or len(set(codes)) != len(codes)
            or any(c not in PREFECTURE_CODES for c in codes)
        ):
            raise PipelineError("INVALID_INPUT", "region codes")
        if not _SOURCE_REF_RE.match(request.source_ref):
            raise PipelineError("INVALID_INPUT", "source_ref")
        return module

    def _load_definition(self, api_id: str) -> ConfigSnapshot:
        try:
            return self._config.load("api", api_id, "sources")
        except ConfigurationError as exc:
            raise PipelineError("INVALID_CONFIGURATION", str(exc)) from exc

    @staticmethod
    def _check_target(
        request: DownloadRequest, definition: ConfigSnapshot, module: DownloadModule
    ) -> None:
        sources = definition.data["sources"]
        if request.source_ref not in sources:
            raise PipelineError("INVALID_INPUT", "source_ref not defined")
        # Any unconfigured region blocks the whole request (no silent trimming).
        for code in request.region_codes:
            region = definition.data["prefectures"][code]
            if not region["targeted"] or request.source_ref not in region["source_refs"]:
                raise PipelineError("TARGET_UNCONFIGURED", "region not targeted for source")
        source = sources[request.source_ref]
        required = (
            source["approval_ref"],
            source["vertical_reference"],
            source["pipeline"],
            source["usage"]["attribution_text"],
            source["usage"]["review_ref"],
        )
        if any(value is None for value in required):
            raise PipelineError("APPROVAL_REQUIRED", "source not approved")
        pipeline = source["pipeline"]
        if (pipeline["id"], pipeline["version"]) != module.pipeline:
            raise PipelineError("APPROVAL_REQUIRED", "pipeline version not implemented")

    def _authorize(
        self, request: DownloadRequest, definition: ConfigSnapshot, module: DownloadModule
    ) -> Authorization:
        authorization = self._authorizer.authorize(
            api_id=request.api_id,
            operation=OPERATION,
            source_ref=request.source_ref,
            region_codes=tuple(sorted(request.region_codes)),
            definition=definition,
        )
        if authorization.context is not module.transport_context:
            raise PipelineError("APPROVAL_REQUIRED", "transport context mismatch")
        return authorization

    def _protected_roots(self) -> tuple[Path, ...]:
        return (PRODUCTION_DATA_ROOT, self._config.schema_root, self._config.definition_root)

    def _check_data_root(self, authorization: Authorization) -> None:
        """Cheap lexical pre-check (fail fast). Not the security decision:
        :meth:`_check_pinned_root` decides on the pinned root fd."""
        if authorization.context is not ExecutionContext.FIXTURE:
            return
        if any(is_within(self._data_root, root) for root in self._protected_roots()):
            raise PipelineError("INVALID_INPUT", "fixture data root not allowed")

    def _check_pinned_root(self, area: ApiDataArea, authorization: Authorization) -> None:
        """Fixture runs may only write to a dedicated, explicitly marked root (F12, R1-01).

        The root is pinned first (fd opened from ``/`` without following any
        symlink); the protected-root decision and the marker check are then made
        on that same pinned directory, and all later I/O goes through it. The
        marker only records the operator's intent to use the directory as a
        disposable fixture root; it is not an authentication credential.
        """
        area.pin()
        if authorization.context is not ExecutionContext.FIXTURE:
            return
        if area.root_within(self._protected_roots()):
            raise PipelineError("INVALID_INPUT", "fixture data root not allowed")
        if not area.has_fixture_marker():
            raise PipelineError("INVALID_INPUT", "data root is not a fixture root")

    @staticmethod
    def _prepare_area(area: ApiDataArea) -> None:
        dirs = [area.path(*parts) for parts in sorted(DOWNLOAD_AREAS)]
        for directory in dirs:
            area.ensure_dir(directory)
        # Finalisation relies on same-filesystem link/rename; verify it.
        if not area.same_filesystem(*dirs):
            raise StorageError("STORAGE_INTEGRITY_FAILED", "areas on different filesystems")

    @staticmethod
    def _effective_document(
        run_id: str,
        request: DownloadRequest,
        definition: ConfigSnapshot,
        authorization: Authorization,
        module: DownloadModule,
    ) -> dict[str, Any]:
        data = definition.data
        return {
                "effective_configuration_schema_version": EFFECTIVE_SCHEMA_VERSION,
                "run_id": run_id,
                "api_id": request.api_id,
                "operation": OPERATION,
                "execution_context": authorization.context.value,
                "authorization_ref": authorization.authorization_ref,
                "source_definition": {
                    "schema_version": data["schema_version"],
                    "definition_revision": data["definition_revision"],
                    "source_ref": request.source_ref,
                    "raw_sha256": definition.raw_sha256,
                },
                "source": thaw(data["sources"][request.source_ref]),
                "region_codes": sorted(request.region_codes),
                "policy": thaw(authorization.policy),
                "pipeline": {"id": module.pipeline[0], "version": module.pipeline[1]},
            }

    @staticmethod
    def _persist_snapshot(area: ApiDataArea, plan: DownloadPlan, effective: bytes) -> None:
        directory = area.path("records", "configurations", plan.run_id)
        source_path = directory / "source.json"
        effective_path = directory / "effective.json"
        if plan.resume:
            # Same run_id is only accepted with byte-identical configuration.
            if not area.dir_exists(directory):
                raise PipelineError("INVALID_INPUT", "unknown run_id")
            names = set(area.list_dir(directory))
            if names != {"source.json", "effective.json"}:
                raise PipelineError("RECOVERY_REQUIRED", "incomplete configuration snapshot")
            try:
                same = (
                    area.read_bytes(source_path, MAX_CONFIG_BYTES) == plan.definition.raw_bytes
                    and area.read_bytes(effective_path, MAX_CONFIG_BYTES) == effective
                )
            except StorageError as exc:
                raise PipelineError("RECOVERY_REQUIRED", "snapshot unreadable") from exc
            if not same:
                raise PipelineError("INVALID_INPUT", "configuration differs for run_id")
            return
        if area.dir_exists(directory):
            raise PipelineError("INTERNAL_ERROR", "run_id collision")
        area.ensure_dir(directory)
        area.write_new(source_path, plan.definition.raw_bytes)
        area.write_new(effective_path, effective)

    # -- results -------------------------------------------------------
    def _log_api(self, api_id: str) -> str | None:
        # Never echo unvalidated request text into logs.
        return api_id if api_id in self._modules else None

    def _finish(self, run_id: str, api_id: str, error_code: str) -> ModuleResult:
        result = ModuleResult.error(run_id, MODULE, error_code)
        log = self._logger.bind(module=MODULE, api_id=self._log_api(api_id), run_id=run_id)
        self._log_result(log, result)
        return result

    @staticmethod
    def _log_result(log: StructuredLogger, result: ModuleResult) -> None:
        if result.status.value == "SUCCESS":
            log.info("Download finished")
        elif result.status.value == "BLOCKED":
            log.warning("Download blocked", error_code=result.error_code)
        else:
            log.error("Download failed", error_code=result.error_code)
