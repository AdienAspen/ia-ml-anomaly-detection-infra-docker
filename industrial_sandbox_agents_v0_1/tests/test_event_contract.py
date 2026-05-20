import unittest

from src.event_bus.schemas import ValidationError, validate_enriched_anomaly_event
from src.event_bus.testing import build_sample_enriched_anomaly_event


class EnrichedAnomalyEventContractTests(unittest.TestCase):
    def test_accepts_valid_payload(self) -> None:
        event = build_sample_enriched_anomaly_event()
        validated = validate_enriched_anomaly_event(event)
        self.assertEqual(validated, event)

    def test_rejects_missing_required_field(self) -> None:
        event = build_sample_enriched_anomaly_event()
        del event["correlation_engine"]

        with self.assertRaises(ValidationError) as ctx:
            validate_enriched_anomaly_event(event)

        self.assertIn("Schema validation failed", str(ctx.exception))

    def test_rejects_forbidden_runtime_field(self) -> None:
        event = build_sample_enriched_anomaly_event()
        event["chaos_template"] = {"scenario": "not_allowed"}

        with self.assertRaises(ValidationError) as ctx:
            validate_enriched_anomaly_event(event)

        self.assertIn("Forbidden runtime fields", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
