"""Triage stage for the Block 1C reasoning flow."""

from __future__ import annotations

from typing import Any

from src.context_engine.builder import build_context_slice
from src.context_engine.contracts import validate_context_slice
from src.event_bus.testing import build_sample_enriched_anomaly_event


def build_triage_record(context_slice: dict[str, Any]) -> dict[str, Any]:
    """Summarize the incoming context into a triage-oriented record."""

    validate_context_slice(context_slice)

    propagation_detected = context_slice["propagation_summary"].startswith("Propagation detected")
    anomaly_count = len(context_slice.get("recent_anomalies", []))
    related_services_count = len(context_slice.get("related_services", []))
    severity = _derive_severity(propagation_detected, anomaly_count, related_services_count)
    routing_decision = "escalate" if severity in {"high", "critical"} else "investigate"

    return {
        "event_id": context_slice["event_id"],
        "primary_service": context_slice["primary_service"],
        "severity": severity,
        "propagation_detected": propagation_detected,
        "anomaly_count": anomaly_count,
        "related_services_count": related_services_count,
        "routing_decision": routing_decision,
    }


def main() -> int:
    context_slice = build_context_slice(build_sample_enriched_anomaly_event())
    triage = build_triage_record(context_slice)
    print(
        "Agentic triage ready for "
        f"{triage['event_id']} -> severity={triage['severity']} routing={triage['routing_decision']}."
    )
    return 0


def _derive_severity(
    propagation_detected: bool,
    anomaly_count: int,
    related_services_count: int,
) -> str:
    if propagation_detected and anomaly_count >= 1 and related_services_count >= 2:
        return "high"
    if propagation_detected or anomaly_count >= 2:
        return "medium"
    return "low"
