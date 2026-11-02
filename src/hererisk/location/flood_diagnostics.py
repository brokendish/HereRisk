"""Flood diagnostic interpretation of one point (Phase 4-G): ``GET /api/v1/diagnostics/flood?lat=&lon=``.

The official answer and HereRisk's own diagnostic interpretation are returned side by side, never mixed:

* ``official_assessment``: the Flood Provider's section for the point, unchanged and shape-checked the
  same way as ``hazards.flood`` of ``GET /api/v1/location`` (the same object; no field is added or changed)
* ``diagnostic``: one interpretation per zone_ref of the Provider's ``unknowns`` (every listed source,
  in the Provider's order). Nothing is added from the diagnosis index; nothing is merged, ranked or
  reduced across zones or sources. Classification: Phase 4-E ``DiagIndex.diagnose`` /
  ``adoption.classify`` unchanged; wording: Phase 4-F catalog (``hererisk.flood.reason_messages.interpret``)

Synchronous and bounded (the Phase 4-E Shadow stays asynchronous and separate):

* ``WORKERS`` read-only diagnosis index connections, each used by one request at a time (a free one is
  waited for at most ``ACQUIRE_TIMEOUT_S``; otherwise ``busy``). Each connection has its own SQLite
  progress handler and deadline, so stopping one diagnosis never touches another request
* at most ``MAX_TARGETS`` zone_refs per point, else ``limit_exceeded``; at most ``DIAGNOSIS_BUDGET_S``
  per point, else ``timeout``; any other failure is ``failed``. In these cases ``interpretations`` is
  ``null`` (never a partial list) and the official answer is still returned as it is
* the original ZIPs are never read; the diagnosis index must be complete and derived from the flood index
  the Provider serves (checked at start-up for every connection: ``DiagIndexError`` stops the server)
* nothing about a position is logged or kept
"""

from __future__ import annotations

import queue
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hererisk.common.polygon_reasons import resolve_reason, resolve_result
from hererisk.flood.adoption import ADOPTION_VERSION
from hererisk.flood.diag import DiagIndex
from hererisk.flood.reason_messages import HAZARD_TYPE, interpret
from hererisk.location.model import check_section, error_section

SCHEMA_VERSION = "flood-diagnostic-v0.1"
WORKERS = 2
ACQUIRE_TIMEOUT_S = 0.25
DIAGNOSIS_BUDGET_S = 1.0
MAX_TARGETS = 32


class _Timeout(Exception):
    pass


class _Slot:
    """One read-only diagnosis index connection with its own deadline."""

    def __init__(self, diag_index: Path, flood_index: Path) -> None:
        self.diag = DiagIndex(diag_index, flood_index=flood_index)
        self.deadline = 0.0
        self.diag.db.set_progress_handler(self._over_budget, 1000)

    def _over_budget(self) -> int:
        return 1 if self.deadline and time.monotonic() > self.deadline else 0


class FloodDiagnosisApi:
    def __init__(self, provider: Any, diag_index: Path, flood_index: Path, radii: list[float], *,
                 workers: int = WORKERS) -> None:
        self._provider = provider                  # the plain Flood Provider (not the Shadow wrapper)
        self._radii = list(radii)
        self._slots: queue.Queue = queue.Queue()
        slots = [_Slot(diag_index, flood_index) for _ in range(workers)]   # raises: the server does not start
        for s in slots:
            self._slots.put(s)
        meta = slots[0].diag.meta
        self._index = {"built_at": meta["built_at"], "status": meta["status"],
                       "derived_from_flood_index_built_at": meta["derived_from"]["flood_index"]["built_at"]}
        self._method = meta["method"]

    def _official(self, lat: float, lon: float) -> dict[str, Any]:
        try:
            raw = self._provider.lookup(lat, lon)
        except Exception:     # noqa: BLE001 - as the Orchestrator: no details
            return error_section(self._provider.id, "provider_failed")
        return check_section("hazard", self._provider.id, raw, allow_synthetic=False)

    def lookup(self, lat: float, lon: float) -> dict[str, Any]:
        official = self._official(lat, lon)
        targets = [(s["source_id"], s["service_region_relation"], [u["zone_ref"] for u in s["unknowns"]])
                   for s in official.get("sources") or [] if s.get("unknowns")]
        total = sum(len(refs) for _, _, refs in targets)
        status, interpretations = "no_targets", []
        if total > MAX_TARGETS:
            status, interpretations = "limit_exceeded", None
        elif total:
            status, interpretations = self._diagnose(lat, lon, targets)
        reason = {"limit_exceeded": "diagnosis_limit_exceeded", "timeout": "diagnosis_timeout",
                  "busy": "diagnosis_busy", "failed": "diagnosis_failed"}.get(status)
        notice = resolve_result("diagnostic_notice", HAZARD_TYPE)
        diagnostic = {
            "status": status, "complete": interpretations is not None, "official": False,
            "certainty": "diagnostic_only", "method": self._method, "adoption_version": ADOPTION_VERSION,
            "message_version": notice["message_version"], "diag_index": self._index, "radii_m": self._radii,
            "targets_total": total, "max_targets": MAX_TARGETS, "interpretations": interpretations,
            "reason": None if reason is None else {
                k: v for k, v in resolve_reason(reason, HAZARD_TYPE).items()
                if k in ("code", "message_ja", "detail_ja", "message_version")},
            "notice": {"message_ja": notice["message_ja"], "detail_ja": notice["detail_ja"]},
        }
        return {"schema_version": SCHEMA_VERSION, "hazard_type": HAZARD_TYPE, "location": {"lat": lat, "lon": lon},
                "official_assessment": official, "diagnostic": diagnostic,
                "evaluated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}

    def _diagnose(self, lat: float, lon: float, targets: list) -> tuple[str, list[dict[str, Any]] | None]:
        try:
            slot = self._slots.get(timeout=ACQUIRE_TIMEOUT_S)
        except queue.Empty:
            return "busy", None
        try:
            slot.deadline = time.monotonic() + DIAGNOSIS_BUDGET_S
            out = []
            for sid, relation, refs in targets:
                for ref in refs:                  # one zone at a time: the deadline is checked in between
                    if time.monotonic() > slot.deadline:
                        raise _Timeout
                    out += slot.diag.diagnose(lat, lon, self._radii, [(sid, relation, [ref])], identity_ok=True)
            if time.monotonic() > slot.deadline:
                raise _Timeout
            return "complete", [interpret(r) for r in out]
        except _Timeout:
            return "timeout", None
        except sqlite3.OperationalError as exc:
            return ("timeout" if "interrupt" in str(exc).lower() else "failed"), None
        except Exception:     # noqa: BLE001 - never a partial or guessed result
            return "failed", None
        finally:
            slot.deadline = 0.0
            self._slots.put(slot)
