"""Orchestrate the Layer 3 agentic reasoning flow."""

from __future__ import annotations

from typing import Any

from src.agentic_core.confidence import build_confidence_vector
from src.agentic_core.diagnosis import build_diagnosis
from src.agentic_core.recommendation import build_incident_card, build_recommendation
from src.agentic_core.triage import build_triage_record
from src.context_engine.contracts import validate_context_slice


def run_reasoning_flow(context_slice: dict[str, Any]) -> dict[str, Any]:
    """Run triage, diagnosis, confidence, and recommendation on a context slice."""

    validate_context_slice(context_slice)

    triage_record = build_triage_record(context_slice)
    diagnosis = build_diagnosis(context_slice, triage_record)
    confidence_vector = build_confidence_vector(context_slice, triage_record, diagnosis)
    recommendation = build_recommendation(context_slice, triage_record, diagnosis, confidence_vector)
    incident_card = build_incident_card(context_slice, triage_record, diagnosis, recommendation)

    return {
        "triage": triage_record,
        "diagnosis": diagnosis,
        "confidence_vector": confidence_vector,
        "recommendation": recommendation,
        "incident_card": incident_card,
    }
