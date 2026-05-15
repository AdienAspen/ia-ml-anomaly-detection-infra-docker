from pathlib import Path
import json

from src.feature_analysis import (
    FEATURE_ANALYSIS_PATH,
    REPORT_PATH,
    STATISTICAL_BASELINE_PATH,
    build_feature_analysis_bundle,
    main,
)


def test_feature_analysis_bundle_contains_expected_sections() -> None:
    bundle = build_feature_analysis_bundle()
    assert "feature_analysis_summary" in bundle
    assert "statistical_baseline" in bundle
    assert "report_markdown" in bundle
    summary = bundle["feature_analysis_summary"]
    baseline = bundle["statistical_baseline"]
    assert summary["schema_version"] == "feature_analysis_summary_v0_1"
    assert baseline["schema_version"] == "statistical_baseline_v0_1"
    assert summary["feature_count"] > 0
    assert summary["variance_ranking"]
    assert summary["top_absolute_correlations"]


def test_feature_analysis_main_exports_artifacts() -> None:
    assert main() == 0
    assert Path(FEATURE_ANALYSIS_PATH).exists()
    assert Path(STATISTICAL_BASELINE_PATH).exists()
    assert Path(REPORT_PATH).exists()
    summary = json.loads(Path(FEATURE_ANALYSIS_PATH).read_text())
    baseline = json.loads(Path(STATISTICAL_BASELINE_PATH).read_text())
    assert summary["feature_keys"]
    assert baseline["features"]
