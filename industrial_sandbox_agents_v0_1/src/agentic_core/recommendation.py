"""Recommendation stage for the Block 1C reasoning flow."""

from __future__ import annotations

from typing import Any

from src.agentic_core.contracts import validate_incident_card, validate_recommendation


def build_recommendation(
    context_slice: dict[str, Any],
    triage_record: dict[str, Any],
    diagnosis: dict[str, Any],
    confidence_vector: dict[str, Any],
) -> dict[str, Any]:
    """Generate a recommendation after confidence validation."""

    del diagnosis

    severity = triage_record["severity"]
    confidence_score = float(confidence_vector["confidence_score"])
    recommendation_type = _pick_recommendation_type(severity, confidence_score)
    recommendation_text = _build_recommendation_text(context_slice, recommendation_type)
    payload = {
        "schema_version": "recommendation_v0_1",
        "event_id": context_slice["event_id"],
        "recommendation_type": recommendation_type,
        "priority": severity,
        "recommendation_text": recommendation_text,
        "requires_human_approval": bool(confidence_vector["human_review_required"]),
    }
    return validate_recommendation(payload)


def build_incident_card(
    context_slice: dict[str, Any],
    triage_record: dict[str, Any],
    diagnosis: dict[str, Any],
    recommendation: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the compact operator-facing incident card."""

    payload = {
        "schema_version": "incident_card_v0_1",
        "event_id": context_slice["event_id"],
        "summary": diagnosis["summary"],
        "severity": triage_record["severity"],
        "suspected_scope": diagnosis["suspected_scope"],
        "diagnosis": diagnosis["probable_cause"],
        "recommended_next_step": recommendation["recommendation_text"],
    }
    return validate_incident_card(payload)


def _pick_recommendation_type(severity: str, confidence_score: float) -> str:
    if severity in {"high", "critical"}:
        return "escalate"
    if confidence_score >= 0.6:
        return "investigate"
    return "observe"


def _build_recommendation_text(context_slice: dict[str, Any], recommendation_type: str) -> str:
    primary_service = context_slice["primary_service"]
    propagation_summary = context_slice["propagation_summary"]
    if recommendation_type == "escalate":
        return (
            f"Escalate to the owner of {primary_service} and review downstream impact. "
            f"Start from the propagation summary: {propagation_summary}"
        )
    if recommendation_type == "investigate":
        return (
            f"Investigate {primary_service} with focus on recent anomalies and service relationships. "
            f"Propagation view: {propagation_summary}"
        )
    return (
        f"Observe {primary_service} and monitor for repeat signals before escalation. "
        f"Current propagation view: {propagation_summary}"
    )
