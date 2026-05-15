from pathlib import Path

from src.validate_correlation_engine import REPORT_PATH, SUMMARY_PATH, main, validate_correlation_engine


def test_validation_summary_contains_core_metrics() -> None:
    summary = validate_correlation_engine()
    assert summary["schema_version"] == "correlation_engine_validation_summary_v0_1"
    assert "propagation_detection_rate" in summary
    assert "false_propagation_rate" in summary
    assert "precision" in summary
    assert "propagation_order_accuracy" in summary
    assert "cluster_stability" in summary
    assert "validation_min_window_quality_score" in summary
    assert "low_quality_window_count" in summary


def test_validation_main_exports_artifacts() -> None:
    assert main() == 0
    assert Path(SUMMARY_PATH).exists()
    assert Path(REPORT_PATH).exists()
