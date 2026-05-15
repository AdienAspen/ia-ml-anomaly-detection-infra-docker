from src.build_hdbscan_temporal_feature_view import build_hdbscan_temporal_feature_view, main
from src.build_temporal_windows import build_temporal_windows
from src.scenario_engine import build_scenario_events


def test_hdbscan_feature_view_scaffold_returns_success() -> None:
    assert main() == 0


def test_hdbscan_feature_view_builds_window_rows() -> None:
    events = build_scenario_events("S4_INTERSERVICE_CHAIN", seed=55, steps=6)
    windows = build_temporal_windows(events)
    rows = build_hdbscan_temporal_feature_view(windows)
    assert rows
    sample = rows[0]
    assert sample["schema_version"] == "hdbscan_temporal_feature_view_v0_2"
    assert "iforest_score_payments" in sample
    assert "window_anomaly_density" in sample
    assert "delta_latency_orders" in sample
    assert "delta_latency_checkout" in sample
    assert sample["window_id"].startswith("temporal_window_")
