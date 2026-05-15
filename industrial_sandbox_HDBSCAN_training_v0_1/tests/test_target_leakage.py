import pytest

from src.build_hdbscan_temporal_feature_view import build_hdbscan_temporal_feature_view
from src.build_temporal_windows import build_temporal_windows
from src.scenario_engine import build_scenario_events
from src.train_hdbscan_temporal import EXCLUDED_FEATURE_COLUMNS, prepare_training_rows, validate_no_target_leakage


def test_validate_no_target_leakage_accepts_clean_feature_keys() -> None:
    validate_no_target_leakage(["iforest_score_payments", "redis_latency", "window_data_quality_score"])


def test_validate_no_target_leakage_rejects_excluded_columns() -> None:
    with pytest.raises(ValueError):
        validate_no_target_leakage(["iforest_score_payments", "scenario_tag"])


def test_prepare_training_rows_does_not_emit_excluded_feature_columns() -> None:
    events = build_scenario_events("S4_INTERSERVICE_CHAIN", seed=123, steps=8)
    windows = build_temporal_windows(events)
    feature_rows = build_hdbscan_temporal_feature_view(windows)
    feature_index = {row["window_id"]: row for row in feature_rows}
    eligible_windows = [
        window
        for window in windows
        if window.get("training_metadata", {}).get("accepted_for_training")
    ]
    _, feature_keys, _ = prepare_training_rows(eligible_windows, feature_index)
    assert not any(key in EXCLUDED_FEATURE_COLUMNS for key in feature_keys)
