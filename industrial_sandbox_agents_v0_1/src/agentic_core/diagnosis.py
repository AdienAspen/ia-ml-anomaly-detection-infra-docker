"""Diagnosis stage for the Block 1C reasoning flow."""

from __future__ import annotations

from typing import Any

from src.context_engine.contracts import validate_context_slice


def build_diagnosis(context_slice: dict[str, Any], triage_record: dict[str, Any]) -> dict[str, Any]:
    """Produce a diagnosis hypothesis from the prepared context."""

    validate_context_slice(context_slice)

    primary_service = context_slice["primary_service"]
    related_services = context_slice.get("related_services", [])
    propagation_detected = bool(triage_record.get("propagation_detected"))

    if propagation_detected:
        summary = (
            f"Likely downstream propagation originating near {primary_service} and affecting "
            f"{', '.join(related_services) if related_services else 'adjacent services'}."
        )
        suspected_scope = "multi_service_propagation"
        probable_cause = "shared_dependency_pressure_or_downstream_cascade"
    else:
        summary = f"Likely localized degradation centered on {primary_service}."
        suspected_scope = "service_localized_degradation"
        probable_cause = "service_specific_anomaly"

    evidence_summary = context_slice["propagation_summary"]
    return {
        "event_id": context_slice["event_id"],
        "summary": summary,
        "suspected_scope": suspected_scope,
        "probable_cause": probable_cause,
        "evidence_summary": evidence_summary,
    }
