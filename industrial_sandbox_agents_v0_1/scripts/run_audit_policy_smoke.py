"""Smoke test for the Layer 5 audit and policy bundle."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agentic_core.runtime import run_reasoning_flow
from src.audit_policy.audit import build_audit_trace, write_audit_bundle
from src.audit_policy.policy import evaluate_policy
from src.context_engine.builder import build_context_slice
from src.event_bus.testing import build_sample_enriched_anomaly_event
from src.tool_layer.registry import load_tool_registry


def main() -> int:
    registry = load_tool_registry()
    event = build_sample_enriched_anomaly_event()
    context_slice = build_context_slice(event)
    reasoning = run_reasoning_flow(context_slice)
    tool_invocations = [
        registry.execute_skill("read_metrics", service_name=event["primary_service"], limit=2),
        registry.execute_skill("query_service_topology", service_name=event["primary_service"]),
        registry.execute_skill(
            "query_propagation_signatures",
            signature_id=event["correlation_engine"]["propagation_signature_id"],
        ),
    ]

    policy_evaluation = evaluate_policy(
        confidence_vector=reasoning["confidence_vector"],
        recommendation=reasoning["recommendation"],
        tool_invocations=tool_invocations,
    )
    audit_trace = build_audit_trace(
        context_slice=context_slice,
        confidence_vector=reasoning["confidence_vector"],
        incident_card=reasoning["incident_card"],
        recommendation=reasoning["recommendation"],
        policy_evaluation=policy_evaluation,
        tool_invocations=tool_invocations,
    )
    bundle = write_audit_bundle(
        audit_trace=audit_trace,
        incident_card=reasoning["incident_card"],
        confidence_vector=reasoning["confidence_vector"],
        recommendation=reasoning["recommendation"],
    )

    print(
        "Audit policy smoke OK: "
        f"status={policy_evaluation['status']} "
        f"tools={len(audit_trace['tools_used'])} "
        f"files_written={len(bundle['written_files'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
