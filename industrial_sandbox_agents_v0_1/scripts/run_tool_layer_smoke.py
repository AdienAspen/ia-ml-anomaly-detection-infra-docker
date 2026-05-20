"""Smoke test for the Layer 4 tool/skill registry."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agentic_core.runtime import run_reasoning_flow
from src.context_engine.builder import build_context_slice
from src.event_bus.testing import build_sample_enriched_anomaly_event
from src.tool_layer.registry import load_tool_registry


def main() -> int:
    registry = load_tool_registry()
    event = build_sample_enriched_anomaly_event()
    context_slice = build_context_slice(event)
    reasoning = run_reasoning_flow(context_slice)

    metrics = registry.execute_skill("read_metrics", service_name=event["primary_service"], limit=2)
    propagation = registry.execute_skill(
        "query_propagation_signatures",
        signature_id=event["correlation_engine"]["propagation_signature_id"],
    )
    topology = registry.execute_skill("query_service_topology", service_name=event["primary_service"])
    artifacts = registry.execute_skill(
        "generate_report",
        event_id=event["event_id"],
        incident_card=reasoning["incident_card"],
        confidence_vector=reasoning["confidence_vector"],
        recommendation=reasoning["recommendation"],
    )

    print(
        "Tool layer smoke OK: "
        f"metrics={metrics['records_found']} "
        f"propagation_matched={propagation['matched']} "
        f"topology_service={topology.get('normalized_service_name', 'graph')} "
        f"files_written={len(artifacts['written_files'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
