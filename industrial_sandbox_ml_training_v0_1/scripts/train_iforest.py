#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.training import train_iforest_artifact
from src.utils import ensure_feature_columns, get_project_paths, load_json, read_frame


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train the baseline Isolation Forest artifact.")
    parser.add_argument("--config", type=Path, default=Path("configs/training/iforest_baseline_v1.json"))
    parser.add_argument("--dataset", type=Path, help="Optional explicit training dataset path.")
    parser.add_argument("--contamination", type=float, help="Optional contamination override.")
    parser.add_argument("--model-version", help="Optional model version override.")
    parser.add_argument("--artifact-output-dir", type=Path, help="Optional artifact directory override.")
    parser.add_argument("--metrics-path", type=Path, help="Optional metrics JSON output path.")
    parser.add_argument("--report-path", type=Path, help="Optional report output path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = get_project_paths()

    config_path = args.config if args.config.is_absolute() else paths.root / args.config
    config = load_json(config_path)

    dataset_path = args.dataset or (paths.root / config["training_dataset"])
    frame = read_frame(dataset_path)
    ensure_feature_columns(frame.columns)

    if "generated_at" in frame.columns:
        frame = frame.sort("generated_at")

    params = config["hyperparameters"]
    if args.contamination is not None:
        params = {**params, "contamination": args.contamination}

    output_dir = (
        args.artifact_output_dir
        if args.artifact_output_dir and args.artifact_output_dir.is_absolute()
        else paths.root / (args.artifact_output_dir or config["artifact_output_dir"])
    )
    metrics_path = (
        args.metrics_path
        if args.metrics_path and args.metrics_path.is_absolute()
        else paths.root / args.metrics_path
        if args.metrics_path
        else paths.artifacts_dir / "metrics" / "training_baseline_metrics.json"
    )
    report_path = (
        args.report_path
        if args.report_path and args.report_path.is_absolute()
        else paths.root / args.report_path
        if args.report_path
        else paths.artifacts_dir / "reports" / "training_baseline_report.md"
    )

    result = train_iforest_artifact(
        frame=frame,
        dataset_path=dataset_path,
        output_dir=output_dir,
        model_version=args.model_version or config["model_version"],
        hyperparameters=params,
        feature_contract_path=paths.contracts_dir / "feature_contract_v1.json",
        metrics_path=metrics_path,
        report_path=report_path,
    )

    print(json.dumps(
        {
            "status": "ok",
            "model_path": str(result["model_path"]),
            "manifest_path": str(result["manifest_path"]),
            "metrics_path": str(result["metrics_path"]),
            "report_path": str(result["report_path"]),
            "row_count": frame.height,
            "feature_count": 8,
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
