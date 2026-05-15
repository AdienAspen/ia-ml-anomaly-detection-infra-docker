from src.build_iforest_feature_view import build_iforest_feature_view, main
from src.scenario_engine import build_scenario_events


def test_iforest_feature_view_scaffold_returns_success() -> None:
    assert main() == 0


def test_iforest_feature_view_builds_service_rows() -> None:
    events = build_scenario_events("S2_SERVICE_TO_REDIS_PROPAGATION", seed=33, steps=5)
    rows = build_iforest_feature_view(events)
    assert rows
    sample = rows[0]
    assert sample["schema_version"] == "iforest_feature_view_v0_1"
    assert sample["service_name"] in {"payments-api", "orders-api", "checkout-api"}
    assert "iforest_score" in sample
