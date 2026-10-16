"""Pipeline execution result contract (Phase 1-A contract section 4.2).

Libraries return :class:`ModuleResult`; only the CLI converts it to an exit code.
Messages are fixed, safe strings: never exception text, URLs, secrets or paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Status(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


# error_code -> (status, CLI exit code). The single source for this mapping.
ERROR_CODES: dict[str, tuple[Status, int]] = {
    # BLOCKED: preconditions missing, nothing transferred.
    "TARGET_UNCONFIGURED": (Status.BLOCKED, 3),
    "APPROVAL_REQUIRED": (Status.BLOCKED, 3),
    "TARGET_BUSY": (Status.BLOCKED, 3),
    "RECOVERY_REQUIRED": (Status.BLOCKED, 3),
    # FAILED: input / configuration.
    "INVALID_INPUT": (Status.FAILED, 2),
    "INVALID_CONFIGURATION": (Status.FAILED, 2),
    # FAILED: transport (HTTP codes are reserved for a future HTTP transport).
    "HTTP_404": (Status.FAILED, 10),
    "HTTP_403": (Status.FAILED, 10),
    "HTTP_429": (Status.FAILED, 10),
    "HTTP_5XX": (Status.FAILED, 10),
    "HTTP_UNEXPECTED": (Status.FAILED, 10),
    "TIMEOUT": (Status.FAILED, 10),
    "TRANSFER_INTERRUPTED": (Status.FAILED, 10),
    "REDIRECT_REJECTED": (Status.FAILED, 10),
    "TLS_FAILED": (Status.FAILED, 10),
    # FAILED: representation.
    "CONTENT_TYPE_INVALID": (Status.FAILED, 11),
    "SIZE_INVALID": (Status.FAILED, 11),
    "PNG_INVALID": (Status.FAILED, 11),
    # FAILED: storage / hash.
    "STORAGE_FULL": (Status.FAILED, 12),
    "PERMISSION_DENIED": (Status.FAILED, 12),
    "HASH_FAILED": (Status.FAILED, 12),
    "STORAGE_INTEGRITY_FAILED": (Status.FAILED, 12),
    # FAILED: record commit.
    "RECORD_COMMIT_FAILED": (Status.FAILED, 13),
    # FAILED: other.
    "INTERNAL_ERROR": (Status.FAILED, 14),
}

MESSAGES: dict[str | None, str] = {
    None: "Acquisition committed",
    "TARGET_UNCONFIGURED": "Requested target is not configured for acquisition",
    "APPROVAL_REQUIRED": "Required acquisition approvals are missing",
    "TARGET_BUSY": "Another acquisition for the same target is running",
    "RECOVERY_REQUIRED": "Uncommitted or inconsistent artifacts require recovery",
    "INVALID_INPUT": "Request input is invalid",
    "INVALID_CONFIGURATION": "Configuration is invalid",
    "HTTP_404": "Source object was not found",
    "TRANSFER_INTERRUPTED": "Transfer was interrupted",
    "CONTENT_TYPE_INVALID": "Content type is invalid",
    "SIZE_INVALID": "Content size is invalid",
    "PNG_INVALID": "PNG container is invalid",
    "STORAGE_FULL": "Storage is full",
    "PERMISSION_DENIED": "Storage permission denied",
    "HASH_FAILED": "Hash could not be computed",
    "STORAGE_INTEGRITY_FAILED": "Stored artifact failed integrity verification",
    "RECORD_COMMIT_FAILED": "Acquisition record could not be committed",
    "INTERNAL_ERROR": "Internal error",
}


def message_for(error_code: str | None) -> str:
    return MESSAGES.get(error_code, "Acquisition failed")


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    acquisition_id: str
    record_ref: str
    sha256: str
    size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "acquisition_id": self.acquisition_id,
            "record_ref": self.record_ref,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class ModuleResult:
    run_id: str
    module: str
    status: Status
    error_code: str | None
    message: str
    artifacts: tuple[Artifact, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.status is Status.SUCCESS:
            if self.error_code is not None:
                raise ValueError("SUCCESS must not carry an error_code")
        else:
            if self.error_code not in ERROR_CODES:
                raise ValueError(f"unknown error_code {self.error_code!r}")
            if ERROR_CODES[self.error_code][0] is not self.status:
                raise ValueError("error_code does not match status")
            if self.status is Status.BLOCKED and self.artifacts:
                raise ValueError("BLOCKED results carry no artifacts")

    @classmethod
    def success(cls, run_id: str, module: str, artifacts: tuple[Artifact, ...]) -> ModuleResult:
        return cls(run_id, module, Status.SUCCESS, None, message_for(None), artifacts)

    @classmethod
    def error(
        cls, run_id: str, module: str, error_code: str, artifacts: tuple[Artifact, ...] = ()
    ) -> ModuleResult:
        status = ERROR_CODES[error_code][0]
        return cls(run_id, module, status, error_code, message_for(error_code), artifacts)

    @property
    def exit_code(self) -> int:
        if self.status is Status.SUCCESS:
            return 0
        return ERROR_CODES[self.error_code][1]  # type: ignore[index]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "module": self.module,
            "status": self.status.value,
            "artifacts": [a.to_dict() for a in self.artifacts],
            "error_code": self.error_code,
            "message": self.message,
        }


class PipelineError(Exception):
    """Raised inside a module to end processing with a contract error_code.

    The exception text is never exposed to users; only ``error_code`` is.
    """

    def __init__(self, error_code: str, detail: str = "") -> None:
        if error_code not in ERROR_CODES:
            raise ValueError(f"unknown error_code {error_code!r}")
        super().__init__(f"{error_code}: {detail}" if detail else error_code)
        self.error_code = error_code
