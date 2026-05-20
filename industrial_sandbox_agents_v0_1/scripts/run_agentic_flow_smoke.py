"""Smoke entrypoint for the agentic reasoning flow."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agentic_core.runtime import run_reasoning_flow
from src.context_engine.builder import build_context_slice
from src.event_bus.testing import build_sample_enriched_anomaly_event


def main() -> int:
    context_slice = build_context_slice(build_sample_enriched_anomaly_event("evt-agentic-smoke-001"))
    outputs = run_reasoning_flow(context_slice)

    if outputs["incident_card"]["event_id"] != "evt-agentic-smoke-001":
        return 1
    if outputs["recommendation"]["recommendation_type"] not in {"observe", "investigate", "escalate"}:
        return 1

    print(
        "Agentic reasoning smoke passed for "
        f"{outputs['incident_card']['event_id']} -> {outputs['recommendation']['recommendation_type']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
