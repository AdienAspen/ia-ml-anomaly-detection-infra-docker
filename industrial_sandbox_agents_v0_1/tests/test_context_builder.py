import unittest

from src.context_engine.builder import build_context_slice
from src.event_bus.testing import build_sample_enriched_anomaly_event


class ContextBuilderTests(unittest.TestCase):
    def test_build_context_slice_projects_primary_fields(self) -> None:
        event = build_sample_enriched_anomaly_event("evt-context-001")
        context_slice = build_context_slice(event)

        self.assertEqual(context_slice["schema_version"], "context_slice_v0_1")
        self.assertEqual(context_slice["event_id"], "evt-context-001")
        self.assertEqual(context_slice["primary_service"], "payments-api")
        self.assertIn("redis", context_slice["related_services"])
        self.assertGreater(context_slice["token_budget"]["estimated_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
