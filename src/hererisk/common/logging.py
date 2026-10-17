"""Common structured logging.

Each log entry is a flat JSON object with the minimum fields
timestamp, level, module, api_id, run_id, error_code, message.
Output goes to a pluggable *sink* so that syslog/journald can be attached later
without changing callers. The default sink writes JSON lines to stderr, keeping
logs separate from the CLI result on stdout.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

LEVELS = ("INFO", "WARNING", "ERROR")


class LogSink(Protocol):
    def __call__(self, entry: dict[str, Any]) -> None: ...


def stderr_sink(entry: dict[str, Any]) -> None:
    sys.stderr.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    sys.stderr.flush()


class ListSink:
    """In-memory sink for tests."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def __call__(self, entry: dict[str, Any]) -> None:
        self.entries.append(entry)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class StructuredLogger:
    """Logger bound to module / api_id / run_id.

    Messages must be fixed strings. Do not pass exception text, URLs, user
    locations, secrets or physical paths.
    """

    def __init__(
        self,
        sink: LogSink = stderr_sink,
        *,
        module: str = "pipeline",
        api_id: str | None = None,
        run_id: str | None = None,
        request_id: str | None = None,
        clock: Callable[[], str] = _utc_now,
    ) -> None:
        self._sink = sink
        self._clock = clock
        self.module = module
        self.api_id = api_id
        self.run_id = run_id
        # Public API requests only (server-generated); never a pipeline run_id.
        self.request_id = request_id

    def bind(self, **fields: str | None) -> StructuredLogger:
        return StructuredLogger(
            self._sink,
            module=fields.get("module", self.module) or self.module,
            api_id=fields.get("api_id", self.api_id),
            run_id=fields.get("run_id", self.run_id),
            request_id=fields.get("request_id", self.request_id),
            clock=self._clock,
        )

    def log(self, level: str, message: str, *, error_code: str | None = None) -> None:
        if level not in LEVELS:
            raise ValueError(f"unknown level {level!r}")
        entry = {
            "timestamp": self._clock(),
            "level": level,
            "module": self.module,
            "api_id": self.api_id,
            "run_id": self.run_id,
            "error_code": error_code,
            "message": message,
        }
        if self.request_id is not None:
            entry["request_id"] = self.request_id
        self._sink(entry)

    def info(self, message: str) -> None:
        self.log("INFO", message)

    def warning(self, message: str, *, error_code: str | None = None) -> None:
        self.log("WARNING", message, error_code=error_code)

    def error(self, message: str, *, error_code: str | None = None) -> None:
        self.log("ERROR", message, error_code=error_code)
