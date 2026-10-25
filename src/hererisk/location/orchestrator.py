"""Location Orchestrator: call every provider independently and assemble the response.

* each provider runs in its own worker with a shared deadline; a failure or timeout of one
  provider becomes that provider's ``error`` section and never removes the other sections
* provider sections are passed through after the shape check (model.check_section); hazard
  classes are not interpreted, ranked, merged or reduced to a maximum / representative value
* exception text, paths and tracebacks never reach the response
"""

from __future__ import annotations

import concurrent.futures as cf
import time
from datetime import datetime, timezone
from typing import Any, Mapping

from hererisk.location.model import HAZARDS, check_section, error_section
from hererisk.location.providers import Provider

SCHEMA_VERSION = "location-v0.1"
DEFAULT_TIMEOUT_S = 2.0
SERVICE_NOTICE = "公式情報の提示です。HereRiskは安全・危険を判定しません。"


class Orchestrator:
    def __init__(self, providers: Mapping[str, Provider], *, mode: str, allow_synthetic: bool,
                 timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        missing = {"address", "elevation", *HAZARDS} - set(providers)
        if missing:
            raise ValueError(f"providers missing: {sorted(missing)}")
        self._providers = dict(providers)
        self._mode = mode
        self._allow_synthetic = allow_synthetic
        self._timeout_s = timeout_s

    def locate(self, lat: float, lon: float) -> dict[str, Any]:
        sections = self._run_all(lat, lon)
        return {
            "schema_version": SCHEMA_VERSION,
            "mode": self._mode,
            "location": {"lat": lat, "lon": lon},
            "address": sections["address"],
            "elevation": sections["elevation"],
            "hazards": {h: sections[h] for h in HAZARDS},
            "notice": SERVICE_NOTICE,
            "evaluated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def _run_all(self, lat: float, lon: float) -> dict[str, dict[str, Any]]:
        pool = cf.ThreadPoolExecutor(max_workers=len(self._providers))
        try:
            futures = {kind: pool.submit(p.lookup, lat, lon) for kind, p in self._providers.items()}
            deadline = time.monotonic() + self._timeout_s
            out = {}
            for kind, fut in futures.items():
                pid = getattr(self._providers[kind], "id", kind)
                try:
                    raw = fut.result(timeout=max(0.0, deadline - time.monotonic()))
                except cf.TimeoutError:
                    out[kind] = error_section(pid, "timeout")
                    continue
                except Exception:  # noqa: BLE001 - provider details never leak
                    out[kind] = error_section(pid, "provider_failed")
                    continue
                shape = "address" if kind == "address" else ("elevation" if kind == "elevation" else "hazard")
                out[kind] = check_section(shape, pid, raw, allow_synthetic=self._allow_synthetic)
            return out
        finally:
            pool.shutdown(wait=False, cancel_futures=True)   # a hung provider does not hold the response
