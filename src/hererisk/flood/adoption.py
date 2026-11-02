"""Classification of a flood diagnosis result (Phase 4-E): candidate / undetermined / rejected.

Diagnosis only. ``candidate`` means "meets the conditions defined here"; it is NOT a promotion to an
official inundation zone, never changes the Location API answer and is not a depth. Several readings
agreeing is a necessary condition here, not a sufficient one for official use. No distance threshold
in this module claims correctness. Pure functions: no shapely, no numpy, no I/O.

Inputs (``classify``):

* ``context``: the diagnosis index state (``status``), whether it belongs to the flood index the
  Provider serves (``identity_ok``), the component's ``zone_ref`` is one of the Provider's
  ``unknowns`` for this source (``in_provider_unknowns``), the source's ``service_region_relation``
* ``component``: the prepared component (``reason``; ``None`` when the zone_ref is not prepared)
* ``analysis``: ``DiagIndex.analyze`` (staged) and ``defect_within_max`` = (distance m, kind) of the
  nearest defect within the largest radius, or ``None``

Rules (every applicable reason code is listed; the first group that applies decides the class):

rejected (a required condition is not met; the result is not used at all)
    diag_index_not_complete, diag_index_identity_mismatch, zone_ref_not_in_provider_unknowns,
    zone_ref_not_in_diag_index, outside_service_region
undetermined (the shape or the position does not settle it)
    service_region_boundary, feature_level_invalidity_not_analyzed,
    on_boundary                       the point is on the ring (Phase 4-D case A: GEOS contains and the
                                      even-odd ray split here; not a GPS accuracy statement)
    defect_within_decision_radius     a defect inside the radius where the local reading would be made
    no_local_boundary                 no ring within the largest radius (the far winding alone is not used)
    ambiguous_nearest, orientation_unknown, defect_location_unknown,
    local_far_disagree                the nearest-boundary side and the whole-ring winding number differ
    even_odd_winding_disagree         the even-odd parity and the winding number read differently
    defect_within_max_radius          decided at a smaller radius, a defect within the largest radius
                                      (Phase 4-D case B: the first reading is not kept unconditionally)
candidate
    the local reading is inside/outside, equals the whole-ring winding number (holes included) and the
    even-odd parity, the point is not on the ring, no defect within the largest radius, and every
    rejected condition is clear. ``make_valid`` agreement is an offline check (not available here);
    ``exterior_only`` ignores holes and is never a reference
"""

from __future__ import annotations

from typing import Any

ADOPTION_VERSION = "flood-diagnosis-adoption-v1"
CANDIDATE, UNDETERMINED, REJECTED = "candidate", "undetermined", "rejected"
LOCAL_UNDETERMINED = {"on_boundary": "on_boundary", "defect_within_radius": "defect_within_decision_radius",
                      "no_boundary_within_max_radius": "no_local_boundary", "ambiguous_nearest": "ambiguous_nearest",
                      "orientation_unknown": "orientation_unknown", "defect_location_unknown": "defect_location_unknown",
                      "inconsistent_winding": "local_far_disagree"}
REASONS = {
    REJECTED: ("diag_index_not_complete", "diag_index_identity_mismatch", "zone_ref_not_in_provider_unknowns",
               "zone_ref_not_in_diag_index", "outside_service_region"),
    UNDETERMINED: ("service_region_boundary", "feature_level_invalidity_not_analyzed", *LOCAL_UNDETERMINED.values(),
                   "even_odd_winding_disagree", "defect_within_max_radius"),
}


def classify(context: dict[str, Any], component: dict[str, Any] | None,
             analysis: dict[str, Any] | None) -> dict[str, Any]:
    rejected = [code for code, hit in (
        ("diag_index_not_complete", context.get("status") != "complete"),
        ("diag_index_identity_mismatch", not context.get("identity_ok")),
        ("zone_ref_not_in_provider_unknowns", not context.get("in_provider_unknowns")),
        ("zone_ref_not_in_diag_index", component is None),
        ("outside_service_region", context.get("service_region_relation") not in ("inside", "boundary"))) if hit]
    out: dict[str, Any] = {"adoption_version": ADOPTION_VERSION, "relation": None}
    if rejected:
        return {**out, "classification": REJECTED, "reasons": rejected}
    local = (analysis or {}).get("local") or {}
    decided = local.get("outcome") in ("inside", "outside")
    evidence = {"local_outcome": local.get("outcome"), "stopped_at_m": local.get("radius_m"),
                "decided_at_m": local.get("radius_m") if decided else None,
                "edge_m": local.get("edge_m"), "winding": local.get("winding"),
                "parity_inside": local.get("parity_inside"), "rings": component.get("ring_count"),
                "holes_in_winding": True}
    dmax = (analysis or {}).get("defect_within_max")
    if dmax is not None:
        evidence["defect_within_max_m"], evidence["defect_kind"] = round(dmax[0], 2), dmax[1]
    reasons = []
    if context["service_region_relation"] == "boundary":
        reasons.append("service_region_boundary")
    if component.get("reason") != "invalid_geometry":
        reasons.append("feature_level_invalidity_not_analyzed")
    outcome = local.get("outcome")
    if outcome in LOCAL_UNDETERMINED:
        reasons.append(LOCAL_UNDETERMINED[outcome])
    elif outcome in ("inside", "outside"):
        inside = outcome == "inside"
        evidence["reading"] = outcome                  # recorded, not adopted while undetermined
        if local.get("parity_inside") is not inside:
            reasons.append("even_odd_winding_disagree")
        if local.get("winding") != (1 if inside else 0):
            reasons.append("local_far_disagree")
        if dmax is not None:
            reasons.append("defect_within_max_radius")
    else:
        reasons.append("no_local_boundary" if outcome is None else "defect_location_unknown")
    if reasons:
        return {**out, "classification": UNDETERMINED, "reasons": reasons, "evidence": evidence}
    return {**out, "classification": CANDIDATE, "relation": outcome, "reasons": ["all_conditions_met"],
            "evidence": evidence}
