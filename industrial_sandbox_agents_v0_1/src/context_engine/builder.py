"""Build minimal context slices from enriched anomaly events."""

from __future__ import annotations

from typing import Any

from src.context_engine.contracts import validate_context_slice
from src.event_bus.schemas import validate_enriched_anomaly_event
from src.event_bus.testing import build_sample_enriched_anomaly_event

DEFAULT_MAX_TOKENS = 4000


def build_context_slice(event: dict[str, Any], max_tokens: int = DEFAULT_MAX_TOKENS) -> dict[str, Any]:
    """Project an enriched anomaly event into a minimal context slice."""

    validate_enriched_anomaly_event(event)

    primary_service = event["primary_service"]
    related_services = [service for service in event["services_observed"] if service != primary_service]
    correlation_engine = event["correlation_engine"]
    anomalous_services = [
        {
            "service_name": service,
            "anomaly_score": event["iforest_scores"].get(service),
            "label": label,
        }
        for service, label in event["iforest_labels"].items()
        if label == "anomalous"
    ]

    topology_summary = _build_topology_summary(primary_service, related_services)
    propagation_summary = _build_propagation_summary(correlation_engine)
    estimated_tokens = min(
        max_tokens,
        700 + (len(related_services) * 120) + (len(anomalous_services) * 80),
    )

    context_slice = {
        "schema_version": "context_slice_v0_1",
        "event_id": event["event_id"],
        "primary_service": primary_service,
        "related_services": related_services,
        "topology_summary": topology_summary,
        "propagation_summary": propagation_summary,
        "recent_anomalies": anomalous_services,
        "runbook_refs": [],
        "policy_refs": [],
        "token_budget": {
            "max_tokens": int(max_tokens),
            "estimated_tokens": int(estimated_tokens),
        },
    }
    return validate_context_slice(context_slice)


def main() -> int:
    sample_event = build_sample_enriched_anomaly_event()
    context_slice = build_context_slice(sample_event)
    print(
        "Context engine scaffold ready for event "
        f"{context_slice['event_id']} with {len(context_slice['related_services'])} related services."
    )
    return 0


def _build_topology_summary(primary_service: str, related_services: list[str]) -> str:
    if not related_services:
        return f"Primary service {primary_service} has no related services in the current observation window."
    joined = ", ".join(related_services)
    return f"Primary service {primary_service} is connected to related services {joined} in the current slice."


def _build_propagation_summary(correlation_engine: dict[str, Any]) -> str:
    if not correlation_engine.get("propagation_detected"):
        return "No propagation signature was detected by the correlation engine for this event."

    signature_id = correlation_engine.get("propagation_signature_id") or "unknown_signature"
    lags = correlation_engine.get("lag_pattern_seconds", {})
    lag_summary = ", ".join(f"{edge}={seconds}s" for edge, seconds in lags.items()) or "no lag details"
    confidence = correlation_engine.get("confidence", 0.0)
    return (
        f"Propagation detected via {signature_id} "
        f"with confidence {confidence:.2f} and lag pattern {lag_summary}."
    )
