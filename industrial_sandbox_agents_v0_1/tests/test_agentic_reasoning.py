import unittest

from src.agentic_core.runtime import run_reasoning_flow
from src.context_engine.builder import build_context_slice
from src.event_bus.testing import build_sample_enriched_anomaly_event


class AgenticReasoningTests(unittest.TestCase):
    def test_run_reasoning_flow_emits_required_outputs(self) -> None:
        context_slice = build_context_slice(build_sample_enriched_anomaly_event("evt-agentic-001"))
        outputs = run_reasoning_flow(context_slice)

        self.assertEqual(outputs["incident_card"]["schema_version"], "incident_card_v0_1")
        self.assertEqual(outputs["recommendation"]["schema_version"], "recommendation_v0_1")
        self.assertEqual(outputs["confidence_vector"]["schema_version"], "confidence_vector_v0_1")
        self.assertEqual(outputs["incident_card"]["event_id"], "evt-agentic-001")

    def test_confidence_vector_marks_missing_context_and_requires_review(self) -> None:
        context_slice = build_context_slice(build_sample_enriched_anomaly_event("evt-agentic-002"))
        outputs = run_reasoning_flow(context_slice)

        confidence = outputs["confidence_vector"]
        self.assertIn("runbook_refs", confidence["missing_context"])
        self.assertIn("policy_refs", confidence["missing_context"])
        self.assertTrue(confidence["human_review_required"])


if __name__ == "__main__":
    unittest.main()
