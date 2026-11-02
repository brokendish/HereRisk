"""Flood Provider settings (Phase 4-C / 4-E): the ``local_analysis`` and ``diagnosis`` blocks, checked here.

    {"local_analysis": {"enabled": false, "initial_radius_m": 5,
                        "expansion_radii_m": [10, 25, 50, 100], "max_radius_m": 100},
     "diagnosis": {"shadow_enabled": false}}

``diagnosis`` is optional (a Phase 4-C file without it still loads; the default is off).
``local_analysis.enabled`` would put the local analysis into the official answer and is refused;
``diagnosis.shadow_enabled`` only runs the diagnosis beside the official answer (Phase 4-E Shadow:
``hererisk.location.flood_shadow``), never changes it, and is allowed.

Diagnosis only in this version: the Flood Provider does not read these settings and its responses do
not change. ``enabled: true`` is refused until the local analysis is adopted (an OWNER decision).
``describe()`` lists the fields, types and limits so a future Data Manager screen can show and edit
them from this one definition. No shapely import: this module stays light.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MAX_RADIUS_LIMIT_M = 1000.0
DEFAULT_LOCAL_ANALYSIS: dict[str, Any] = {"enabled": False, "initial_radius_m": 5,
                                          "expansion_radii_m": [10, 25, 50, 100], "max_radius_m": 100}
FIELDS = {
    "enabled": {"type": "boolean", "label": "局所解析を有効にする", "editable": False,
                "note": "PoC段階では false のみ（Flood Providerは参照しない）"},
    "initial_radius_m": {"type": "number", "label": "初期半径（m）", "min_exclusive": 0, "max": MAX_RADIUS_LIMIT_M},
    "expansion_radii_m": {"type": "array<number>", "label": "拡大半径（m、昇順）", "min_items": 0, "max_items": 10},
    "max_radius_m": {"type": "number", "label": "最大半径（m）", "min_exclusive": 0, "max": MAX_RADIUS_LIMIT_M},
}


DEFAULT_DIAGNOSIS: dict[str, Any] = {"shadow_enabled": False}
DIAGNOSIS_FIELDS = {
    "shadow_enabled": {"type": "boolean", "label": "診断をShadowで並行実行する", "editable": True,
                       "note": "診断専用。正式な洪水判定・Location APIの応答は変えない"},
}


class FloodSettingsError(ValueError):
    """The flood settings are malformed. Fixed messages (no paths)."""


def _number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def check_local_analysis(block: Any) -> dict[str, Any]:
    """The checked block (a copy). Every key is required; unknown keys are refused."""
    if not isinstance(block, dict) or set(block) != set(FIELDS):
        raise FloodSettingsError(f"local_analysis keys must be {sorted(FIELDS)}")
    if not isinstance(block["enabled"], bool):
        raise FloodSettingsError("local_analysis.enabled must be true or false")
    if block["enabled"]:
        raise FloodSettingsError("local_analysis.enabled: true is not supported yet (diagnosis only)")
    first, radii, top = block["initial_radius_m"], block["expansion_radii_m"], block["max_radius_m"]
    if not _number(first) or not 0 < first <= MAX_RADIUS_LIMIT_M:
        raise FloodSettingsError(f"local_analysis.initial_radius_m must be a number in (0, {MAX_RADIUS_LIMIT_M:g}]")
    if not _number(top) or not 0 < top <= MAX_RADIUS_LIMIT_M:
        raise FloodSettingsError(f"local_analysis.max_radius_m must be a number in (0, {MAX_RADIUS_LIMIT_M:g}]")
    if not isinstance(radii, list) or len(radii) > FIELDS["expansion_radii_m"]["max_items"] \
            or not all(_number(r) for r in radii):
        raise FloodSettingsError("local_analysis.expansion_radii_m must be a list of at most 10 numbers")
    steps = [first, *radii]
    if any(b <= a for a, b in zip(steps, steps[1:])):
        raise FloodSettingsError("local_analysis.expansion_radii_m must increase and start above initial_radius_m")
    if steps[-1] != top:
        raise FloodSettingsError("local_analysis.max_radius_m must equal the last radius")
    return {"enabled": False, "initial_radius_m": first, "expansion_radii_m": list(radii), "max_radius_m": top}


def radii(block: dict[str, Any]) -> list[float]:
    """The radii to try, smallest first."""
    return [block["initial_radius_m"], *block["expansion_radii_m"]]


def check_diagnosis(block: Any) -> dict[str, Any]:
    if not isinstance(block, dict) or set(block) != set(DIAGNOSIS_FIELDS):
        raise FloodSettingsError(f"diagnosis keys must be {sorted(DIAGNOSIS_FIELDS)}")
    if not isinstance(block["shadow_enabled"], bool):
        raise FloodSettingsError("diagnosis.shadow_enabled must be true or false")
    return {"shadow_enabled": block["shadow_enabled"]}


def load_settings(path: Path | None) -> dict[str, Any]:
    """{"local_analysis": checked block, "diagnosis": checked block}; the defaults when ``path`` is None."""
    if path is None:
        return {"local_analysis": check_local_analysis(dict(DEFAULT_LOCAL_ANALYSIS)),
                "diagnosis": dict(DEFAULT_DIAGNOSIS)}
    try:
        doc = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FloodSettingsError("flood settings file cannot be read as JSON") from exc
    if not isinstance(doc, dict) or "local_analysis" not in doc or not set(doc) <= {"local_analysis", "diagnosis"}:
        raise FloodSettingsError("flood settings must hold {\"local_analysis\": {...}} and optionally {\"diagnosis\": {...}}")
    return {"local_analysis": check_local_analysis(doc["local_analysis"]),
            "diagnosis": check_diagnosis(doc.get("diagnosis", dict(DEFAULT_DIAGNOSIS)))}


def describe() -> dict[str, Any]:
    """Field definitions and defaults for a settings screen (read only here)."""
    return {"local_analysis": {"fields": FIELDS, "defaults": DEFAULT_LOCAL_ANALYSIS,
                               "rules": ["every key is required", "radii increase strictly",
                                         "max_radius_m equals the last radius", "enabled is false in this version"],
                               "used_by": "diagnosis (python -m hererisk.flood local-analysis / diag) only"},
            "diagnosis": {"fields": DIAGNOSIS_FIELDS, "defaults": DEFAULT_DIAGNOSIS,
                          "rules": ["optional block", "shadow_enabled never changes the official answer",
                                    "shadow_enabled needs a complete diagnosis index of the same flood index"],
                          "used_by": "Location API --flood-settings (Shadow)"}}
