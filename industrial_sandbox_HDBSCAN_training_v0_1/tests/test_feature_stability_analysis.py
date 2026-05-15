from pathlib import Path
import json

from src.feature_stability_analysis import OUTPUT_PATH, REPORT_PATH, build_feature_stability_analysis, main


def test_feature_stability_analysis_bundle_contains_feature_rows() -> None:
    report = build_feature_stability_analysis()
    assert report["schema_version"] == "feature_stability_analysis_v0_1"
    assert report["active_feature_count"] > 0
    assert report["per_feature"]
    sample = report["per_feature"][0]
    assert "feature" in sample
    assert "stability_delta_without_feature" in sample
    assert sample["classification"] in {"stabilizer", "destabilizer_or_redundant", "neutral"}


def test_feature_stability_analysis_main_exports_artifacts() -> None:
    assert main() == 0
    assert Path(OUTPUT_PATH).exists()
    assert Path(REPORT_PATH).exists()
    report = json.loads(Path(OUTPUT_PATH).read_text())
    assert report["per_feature"]
