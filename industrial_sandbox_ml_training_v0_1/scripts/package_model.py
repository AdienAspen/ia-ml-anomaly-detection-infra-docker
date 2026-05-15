#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils import get_project_paths, load_json, timestamp_utc, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Package a trained model artifact into a versioned directory.")
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path("artifacts/models/isolation_forest/baseline_v1"),
        help="Source model directory.",
    )
    parser.add_argument("--package-version", default="iforest_package_v1", help="Package version label.")
    parser.add_argument(
        "--validation-metrics",
        type=Path,
        default=Path("artifacts/metrics/validation_metrics.json"),
        help="Validation metrics JSON path.",
    )
    parser.add_argument(
        "--threshold-recommendation",
        type=Path,
        default=Path("artifacts/reports/threshold_recommendation_v1.json"),
        help="Threshold recommendation JSON path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = get_project_paths()

    source_dir = args.model_dir if args.model_dir.is_absolute() else paths.root / args.model_dir
    validation_metrics_path = (
        args.validation_metrics if args.validation_metrics.is_absolute() else paths.root / args.validation_metrics
    )
    threshold_recommendation_path = (
        args.threshold_recommendation
        if args.threshold_recommendation.is_absolute()
        else paths.root / args.threshold_recommendation
    )
    target_dir = paths.artifacts_dir / "models" / "isolation_forest" / "packages" / args.package_version
    target_dir.mkdir(parents=True, exist_ok=True)

    training_manifest = load_json(source_dir / "training_manifest.json")
    feature_contract = load_json(source_dir / "feature_contract.json")
    validation_metrics = load_json(validation_metrics_path) if validation_metrics_path.exists() else {}
    threshold_recommendation = load_json(threshold_recommendation_path) if threshold_recommendation_path.exists() else {}

    copied_files = []
    for filename in (
        "model.joblib",
        "training_manifest.json",
        "feature_contract.json",
    ):
        source_path = source_dir / filename
        if source_path.exists():
            shutil.copy2(source_path, target_dir / filename)
            copied_files.append(filename)
    if validation_metrics_path.exists():
        shutil.copy2(validation_metrics_path, target_dir / "validation_metrics.json")
        copied_files.append("validation_metrics.json")
    if threshold_recommendation_path.exists():
        shutil.copy2(threshold_recommendation_path, target_dir / "threshold_recommendation.json")
        copied_files.append("threshold_recommendation.json")

    package_manifest = {
        "model_name": "isolation_forest",
        "model_version": args.package_version,
        "artifact_type": "joblib",
        "feature_contract": "feature_contract_v1",
        "training_dataset": training_manifest["dataset_path"],
        "validation_dataset": validation_metrics.get("dataset_path", ""),
        "hyperparameters": training_manifest["hyperparameters"],
        "thresholds": {
            "anomaly_score_threshold": threshold_recommendation.get("recommended_anomaly_score_threshold"),
            "min_flag_window": threshold_recommendation.get("recommended_min_flag_window"),
        },
        "metrics": {
            "training_metrics_path": training_manifest.get("metrics_path"),
            "validation_metrics_path": str(validation_metrics_path) if validation_metrics_path.exists() else None,
            "false_positive_rate_on_normal": validation_metrics.get("false_positive_rate_on_normal"),
            "flag_rate_on_anomalous": validation_metrics.get("flag_rate_on_anomalous"),
            "flag_rate_overall": validation_metrics.get("flag_rate_overall"),
        },
        "created_at": timestamp_utc(),
        "package_metadata": {
            "source_dir": str(source_dir),
            "target_dir": str(target_dir),
            "copied_files": copied_files,
        },
    }
    write_json(target_dir / "manifest.json", package_manifest)

    print(json.dumps(
        {
            "status": "ok",
            "target_dir": str(target_dir),
            "copied_files": copied_files,
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
