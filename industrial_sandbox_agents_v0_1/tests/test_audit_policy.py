"""Tests for the Layer 5 audit and policy bundle."""

from __future__ import annotations

import tempfile
import unittest

from src.agentic_core.runtime import run_reasoning_flow
from src.audit_policy.audit import build_audit_trace, write_audit_bundle
from src.audit_policy.policy import evaluate_policy
from src.context_engine.builder import build_context_slice
from src.event_bus.testing import build_sample_enriched_anomaly_event
from src.tool_layer.registry import load_tool_registry


class AuditPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = load_tool_registry()
        self.event = build_sample_enriched_anomaly_event()
        self.context_slice = build_context_slice(self.event)
        self.reasoning = run_reasoning_flow(self.context_slice)
        self.tool_invocations = [
            self.registry.execute_skill("read_metrics", service_name=self.event["primary_service"], limit=2),
            self.registry.execute_skill("query_service_topology", service_name=self.event["primary_service"]),
            self.registry.execute_skill(
                "query_propagation_signatures",
                signature_id=self.event["correlation_engine"]["propagation_signature_id"],
            ),
        ]

    def test_evaluate_policy_returns_warning_for_mvp_context(self) -> None:
        result = evaluate_policy(
            confidence_vector=self.reasoning["confidence_vector"],
            recommendation=self.reasoning["recommendation"],
            tool_invocations=self.tool_invocations,
        )

        self.assertEqual(result["schema_version"], "policy_evaluation_v0_1")
        self.assertIn(result["status"], {"warning", "pass"})
        self.assertTrue(result["human_approval_required"])

    def test_build_audit_trace_emits_required_contract(self) -> None:
        policy_evaluation = evaluate_policy(
            confidence_vector=self.reasoning["confidence_vector"],
            recommendation=self.reasoning["recommendation"],
            tool_invocations=self.tool_invocations,
        )

        audit_trace = build_audit_trace(
            context_slice=self.context_slice,
            confidence_vector=self.reasoning["confidence_vector"],
            incident_card=self.reasoning["incident_card"],
            recommendation=self.reasoning["recommendation"],
            policy_evaluation=policy_evaluation,
            tool_invocations=self.tool_invocations,
        )

        self.assertEqual(audit_trace["schema_version"], "audit_trace_v0_1")
        self.assertEqual(audit_trace["event_id"], self.event["event_id"])
        self.assertIn("policy_evaluation", audit_trace)
        self.assertEqual(audit_trace["tools_used"][0]["tool_name"], "metrics_query_tool")

    def test_write_audit_bundle_persists_outputs(self) -> None:
        policy_evaluation = evaluate_policy(
            confidence_vector=self.reasoning["confidence_vector"],
            recommendation=self.reasoning["recommendation"],
            tool_invocations=self.tool_invocations,
        )
        audit_trace = build_audit_trace(
            context_slice=self.context_slice,
            confidence_vector=self.reasoning["confidence_vector"],
            incident_card=self.reasoning["incident_card"],
            recommendation=self.reasoning["recommendation"],
            policy_evaluation=policy_evaluation,
            tool_invocations=self.tool_invocations,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            result = write_audit_bundle(
                audit_trace=audit_trace,
                incident_card=self.reasoning["incident_card"],
                confidence_vector=self.reasoning["confidence_vector"],
                recommendation=self.reasoning["recommendation"],
                output_dir=temp_dir,
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(result["written_files"]), 5)


if __name__ == "__main__":
    unittest.main()
