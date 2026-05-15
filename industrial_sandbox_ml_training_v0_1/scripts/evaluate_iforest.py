#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import polars as pl

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils import FEATURE_COLUMNS, ensure_feature_columns, get_project_paths, read_frame, timestamp_utc, write_json
from src.evaluation import (
    build_score_distribution_svg,
    build_top_outliers_markdown,
    compute_threshold_metrics,
    derive_analysis_columns,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a trained Isolation Forest against a validation dataset.")
    parser.add_argument("dataset", type=Path, help="Validation dataset path.")
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path("artifacts/models/isolation_forest/baseline_v1"),
        help="Model artifact directory.",
    )
    parser.add_argument("--threshold", type=float, default=0.58, help="Anomaly-score threshold.")
    parser.add_argument("--output-prefix", default="validation", help="Output file prefix.")
    parser.add_argument("--top-n-outliers", type=int, default=20, help="How many top outliers to persist in the report.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = get_project_paths()

    model_dir = args.model_dir if args.model_dir.is_absolute() else paths.root / args.model_dir
    model_path = model_dir / "model.joblib"
    frame = read_frame(args.dataset)
    ensure_feature_columns(frame.columns)

    model = joblib.load(model_path)
    x = frame.select(list(FEATURE_COLUMNS)).to_numpy()
    raw_scores = model.score_samples(x)
    anomaly_scores = [-score for score in raw_scores]
    flags = [score >= args.threshold for score in anomaly_scores]

    result = frame.with_columns(
        pl.Series(name="raw_score", values=raw_scores),
        pl.Series(name="anomaly_score", values=anomaly_scores),
    )
    result = derive_analysis_columns(result)
    result = result.with_columns(pl.Series(name="predicted_flag", values=flags))

    scores_path = paths.artifacts_dir / "metrics" / f"{args.output_prefix}_scores.parquet"
    metrics_path = paths.artifacts_dir / "metrics" / f"{args.output_prefix}_metrics.json"
    top_outliers_path = paths.artifacts_dir / "reports" / f"{args.output_prefix}_top_outliers.md"
    distribution_plot_path = paths.artifacts_dir / "reports" / f"{args.output_prefix}_score_distribution.svg"
    result.write_parquet(scores_path)
    metrics = compute_threshold_metrics(result, args.threshold)
    metrics.update(
        {
            "evaluated_at": timestamp_utc(),
            "dataset_path": str(args.dataset),
            "model_path": str(model_path),
            "top_outliers_report_path": str(top_outliers_path),
            "score_distribution_plot_path": str(distribution_plot_path),
        }
    )
    if "true_positive_rate_on_anomalous" in metrics and "flag_rate_on_anomalous" not in metrics:
        metrics["flag_rate_on_anomalous"] = metrics["true_positive_rate_on_anomalous"]

    build_top_outliers_markdown(result, top_outliers_path, top_n=args.top_n_outliers)
    build_score_distribution_svg(result, distribution_plot_path)
    write_json(metrics_path, metrics)

    print(json.dumps(
        {
            "status": "ok",
            "scores_path": str(scores_path),
            "metrics_path": str(metrics_path),
            "threshold": args.threshold,
            "rows": result.height,
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
