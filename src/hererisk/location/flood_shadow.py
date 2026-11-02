"""Flood diagnosis in Shadow mode (Phase 4-E): runs beside the Flood Provider, never changes its answer.

* ``ShadowFloodProvider.lookup`` returns the Flood Provider's section object unchanged (same object;
  status / results / sources / zones / unknowns / boundary_contacts / summary / reasons / limitations
  untouched). It only copies, per listed source, the source id, the service region relation and the
  ``unknowns`` zone_refs, and hands them to one diagnosis thread through a bounded queue
  (``put_nowait``; when the queue is full the diagnosis is skipped and counted, the answer never waits)
* only the Provider's unknowns are diagnosed; nothing is picked up from the diagnosis index
* the diagnosis thread owns the read-only diagnosis index connection; a SQLite progress handler
  stops a diagnosis that runs longer than ``DIAGNOSIS_BUDGET_S`` (counted as ``timeout``)
* nothing about a position is kept or logged: the thread keeps counters only (classifications,
  reason codes, decided radii, durations, errors), read with ``stats()``
  (``GET /api/v1/diagnostics/flood-shadow``, see ``hererisk.location.api``)
* start-up: the diagnosis index must be ``complete``, of the same format and method, and derived from
  the flood index the Provider serves; otherwise ``DiagIndexError`` stops the server (exit 3).
  A failure at run time sets ``state`` to ``error`` (counted, with the exception class only)
"""

from __future__ import annotations

import queue
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any

from hererisk.flood.adoption import ADOPTION_VERSION
from hererisk.flood.diag import DiagIndex

QUEUE_SIZE = 64
DIAGNOSIS_BUDGET_S = 1.0


class ShadowFloodProvider:
    def __init__(self, provider: Any, diag_index: Path, flood_index: Path, radii: list[float]) -> None:
        self._provider = provider
        self.id = provider.id
        self._diag = DiagIndex(diag_index, flood_index=flood_index)     # raises: the server does not start
        self._radii = list(radii)
        self._queue: queue.Queue = queue.Queue(maxsize=QUEUE_SIZE)
        self._lock = threading.Lock()
        self._counts: Counter = Counter()
        self._reasons: Counter = Counter()
        self._radius: Counter = Counter()
        self._durations: list[float] = []
        self._errors: Counter = Counter()
        self._deadline = 0.0
        self._finished = 0
        self._diag.db.set_progress_handler(self._over_budget, 10000)
        self._thread = threading.Thread(target=self._run, name="flood-shadow", daemon=True)
        self._thread.start()

    def lookup(self, lat: float, lon: float) -> dict[str, Any]:
        section = self._provider.lookup(lat, lon)
        try:
            targets = [(s["source_id"], s["service_region_relation"], [u["zone_ref"] for u in s["unknowns"]])
                       for s in section.get("sources") or [] if s.get("unknowns")]
            if targets:
                self._queue.put_nowait((lat, lon, targets))
                with self._lock:
                    self._counts["queued"] += 1
        except queue.Full:
            with self._lock:
                self._counts["skipped_queue_full"] += 1
        except Exception as exc:     # noqa: BLE001 - the official answer is returned regardless
            with self._lock:
                self._errors[type(exc).__name__] += 1
        return section

    def _over_budget(self) -> int:
        return 1 if self._deadline and time.monotonic() > self._deadline else 0

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            lat, lon, targets = item
            t0 = time.monotonic()
            self._deadline = t0 + DIAGNOSIS_BUDGET_S
            try:
                records = self._diag.diagnose(lat, lon, self._radii, targets, identity_ok=True)
            except Exception as exc:     # noqa: BLE001 - counted; the official answer was already returned
                with self._lock:
                    self._errors["timeout" if "interrupt" in str(exc).lower() else type(exc).__name__] += 1
                continue
            finally:
                self._deadline = 0.0
                del item, lat, lon               # no position is kept
                with self._lock:
                    self._finished += 1
            with self._lock:
                self._counts["diagnosed_points"] += 1
                self._durations.append(time.monotonic() - t0)
                del self._durations[:-1000]
                for r in records:
                    self._counts[r["classification"]] += 1
                    self._reasons.update(f"{r['classification']}:{c}" for c in r["reasons"])
                    if r.get("evidence", {}).get("decided_at_m") is not None:
                        self._radius[str(r["evidence"]["decided_at_m"])] += 1

    def drain(self, timeout_s: float = 5.0) -> None:
        """Wait until the queue is processed (tests and the verification CLI)."""
        end = time.monotonic() + timeout_s
        while time.monotonic() < end:
            with self._lock:
                if self._finished >= self._counts["queued"]:
                    return
            time.sleep(0.005)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            d = sorted(self._durations)
            state = "error" if self._errors else "active"
            return {"state": state, "diagnosis_only": True, "official_answer_changed": False,
                    "method": self._diag.meta["method"], "adoption_version": ADOPTION_VERSION,
                    "diag_index": {"built_at": self._diag.meta["built_at"], "status": self._diag.meta["status"],
                                   "derived_from": self._diag.meta["derived_from"]["flood_index"]["built_at"]},
                    "radii_m": self._radii, "counts": dict(self._counts), "reasons": dict(self._reasons),
                    "decided_at_m": dict(self._radius), "errors": dict(self._errors),
                    "duration_ms": None if not d else {"n": len(d), "median": round(d[len(d) // 2] * 1000, 3),
                                                       "max": round(d[-1] * 1000, 3)},
                    "positions_kept": False}

