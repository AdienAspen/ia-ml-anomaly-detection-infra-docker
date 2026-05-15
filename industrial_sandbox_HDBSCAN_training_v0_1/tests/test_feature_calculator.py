from src.build_temporal_windows import build_temporal_windows
from src.feature_calculator import build_hdbscan_feature_rows, validate_feature_row
from src.scenario_engine import build_scenario_events


def test_feature_calculator_builds_rows_aligned_to_temporal_windows() -> None:
    events = build_scenario_events("S4_INTERSERVICE_CHAIN", seed=88, steps=8)
    windows = build_temporal_windows(events)
    rows = build_hdbscan_feature_rows(windows)
    assert rows
    assert rows[0]["window_id"] == windows[0]["window_id"]
    assert rows[0]["schema_version"] == "hdbscan_temporal_feature_view_v0_2"


def test_feature_calculator_enforces_basic_sanity_ranges() -> None:
    events = build_scenario_events("S2_SERVICE_TO_REDIS_PROPAGATION", seed=99, steps=8)
    windows = build_temporal_windows(events)
    rows = build_hdbscan_feature_rows(windows)
    sample = rows[0]
    assert validate_feature_row(sample) == []
    assert 0.0 <= sample["window_anomaly_density"] <= 1.0
    assert 0.0 <= sample["window_data_quality_score"] <= 1.0
