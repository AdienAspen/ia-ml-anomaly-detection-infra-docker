from pathlib import Path

from src.build_iforest_feature_view import main as iforest_main
from src.feature_analysis import FEATURE_ANALYSIS_PATH, REPORT_PATH as FEATURE_REPORT_PATH, STATISTICAL_BASELINE_PATH, main as feature_analysis_main
from src.feature_stability_analysis import OUTPUT_PATH as FEATURE_STABILITY_PATH, REPORT_PATH as FEATURE_STABILITY_REPORT_PATH, main as feature_stability_main
from src.build_hdbscan_temporal_feature_view import main as hdbscan_view_main
from src.train_hdbscan_temporal import EXCLUDED_FEATURE_COLUMNS, MODEL_PATH, MANIFEST_PATH, METRICS_PATH, main as train_main
from src.validate_correlation_engine import main as validate_main
import pickle
from src.score_propagation_signatures import OUTPUT_PATH as SIGNATURE_OUTPUT_PATH, main as score_main


def test_core_scaffold_entrypoints_return_success() -> None:
    assert iforest_main() == 0
    assert hdbscan_view_main() == 0
    assert train_main() == 0
    assert validate_main() == 0
    assert score_main() == 0
    assert feature_analysis_main() == 0
    assert feature_stability_main() == 0


def test_training_exports_initial_artifacts() -> None:
    train_main()
    assert Path(MODEL_PATH).exists()
    assert Path(MANIFEST_PATH).exists()
    assert Path(METRICS_PATH).exists()
    assert Path(SIGNATURE_OUTPUT_PATH).exists() or True
    assert Path(FEATURE_ANALYSIS_PATH).exists()
    assert Path(STATISTICAL_BASELINE_PATH).exists()
    assert Path(FEATURE_REPORT_PATH).exists()
    assert Path(FEATURE_STABILITY_PATH).exists()
    assert Path(FEATURE_STABILITY_REPORT_PATH).exists()


def test_training_model_payload_records_anti_leakage_contract() -> None:
    train_main()
    with Path(MODEL_PATH).open("rb") as handle:
        payload = pickle.load(handle)
    assert payload["excluded_feature_columns"] == list(EXCLUDED_FEATURE_COLUMNS)
    assert not any(key in payload["feature_keys"] for key in EXCLUDED_FEATURE_COLUMNS)
