"""Tests for the Layer 4 tool and skill registry."""

from __future__ import annotations

import tempfile
import unittest

from src.agentic_core.runtime import run_reasoning_flow
from src.context_engine.builder import build_context_slice
from src.event_bus.testing import build_sample_enriched_anomaly_event
from src.security.tool_allowlist import ToolAccessError, assert_tool_allowlisted
from src.tool_layer.registry import load_tool_registry


class ToolLayerTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = load_tool_registry()
        self.sample_event = build_sample_enriched_anomaly_event()
        self.context_slice = build_context_slice(self.sample_event)
        self.reasoning = run_reasoning_flow(self.context_slice)

    def test_registry_exposes_skills_and_tools(self) -> None:
        skills = {item.skill_name for item in self.registry.list_skills()}
        tools = {item.tool_name for item in self.registry.list_tools()}

        self.assertIn("read_metrics", skills)
        self.assertIn("send_notification", skills)
        self.assertIn("metrics_query_tool", tools)
        self.assertIn("incident_artifact_writer", tools)

    def test_execute_skill_reads_metrics(self) -> None:
        result = self.registry.execute_skill("read_metrics", service_name="payments-api", limit=2)

        self.assertEqual(result["tool_name"], "metrics_query_tool")
        self.assertGreaterEqual(result["records_found"], 1)

    def test_execute_tool_reads_topology(self) -> None:
        result = self.registry.execute_tool("topology_lookup_tool", service_name="checkout-api")

        self.assertEqual(result["normalized_service_name"], "checkout")
        self.assertIn("orders", result["downstream"])

    def test_incident_artifact_writer_persists_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self.registry.execute_tool(
                "incident_artifact_writer",
                event_id=self.sample_event["event_id"],
                incident_card=self.reasoning["incident_card"],
                confidence_vector=self.reasoning["confidence_vector"],
                recommendation=self.reasoning["recommendation"],
                output_dir=temp_dir,
            )

            self.assertEqual(result["status"], "ok")
            self.assertEqual(len(result["written_files"]), 4)

    def test_notification_sink_writes_intent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self.registry.execute_skill(
                "send_notification",
                event_id=self.sample_event["event_id"],
                message="Escalate to human review.",
                output_dir=temp_dir,
            )

            self.assertEqual(result["status"], "ok")
            self.assertTrue(result["output_path"].endswith("notification_intents.jsonl"))

    def test_allowlist_rejects_unknown_tool(self) -> None:
        with self.assertRaises(ToolAccessError):
            assert_tool_allowlisted("restart_services_tool")


if __name__ == "__main__":
    unittest.main()
