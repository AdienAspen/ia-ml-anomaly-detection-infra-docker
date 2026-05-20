import unittest

from src.context_engine.builder import build_context_slice
from src.context_engine.contracts import ValidationError, validate_context_slice
from src.event_bus.testing import build_sample_enriched_anomaly_event


class ContextContractTests(unittest.TestCase):
    def test_accepts_valid_context_slice(self) -> None:
        context_slice = build_context_slice(build_sample_enriched_anomaly_event("evt-context-contract-001"))
        validated = validate_context_slice(context_slice)
        self.assertEqual(validated["event_id"], "evt-context-contract-001")

    def test_rejects_estimated_tokens_above_max(self) -> None:
        context_slice = build_context_slice(build_sample_enriched_anomaly_event("evt-context-contract-002"))
        context_slice["token_budget"]["estimated_tokens"] = 9999

        with self.assertRaises(ValidationError) as ctx:
            validate_context_slice(context_slice)

        self.assertIn("estimated_tokens", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
