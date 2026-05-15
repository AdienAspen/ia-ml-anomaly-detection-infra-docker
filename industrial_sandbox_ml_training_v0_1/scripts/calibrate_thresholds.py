#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import polars as pl

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils import get_project_paths, load_json, read_frame, timestamp_utc, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Recommend an anomaly-score threshold from evaluation scores.")
    parser.add_argument("scores", type=Path, help="Scores dataset emitted by evaluate_iforest.py.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/evaluation/threshold_calibration_v1.json"),
        help="Threshold calibration config.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = get_project_paths()

    config_path = args.config if args.config.is_absolute() else paths.root / args.config
    config = load_json(config_path)
    frame = read_frame(args.scores)

    if "anomaly_score" not in frame.columns:
        raise ValueError("Scores dataset must include an `anomaly_score` column.")

    normal_quantile = config["recommended_threshold_policy"]["normal_quantile"]
    mixed_quantile = config["recommended_threshold_policy"]["mixed_quantile"]

    if "scenario_tag" in frame.columns and frame.filter(pl.col("scenario_tag") == "normal").height > 0:
        normal_slice = frame.filter(pl.col("scenario_tag") == "normal")
        normal_threshold = float(normal_slice.get_column("anomaly_score").quantile(normal_quantile))
    else:
        normal_threshold = float(frame.get_column("anomaly_score").quantile(normal_quantile))

    mixed_threshold = float(frame.get_column("anomaly_score").quantile(mixed_quantile))
    recommended_threshold = max(normal_threshold, mixed_threshold)

    recommendation = {
        "created_at": timestamp_utc(),
        "scores_path": str(args.scores),
        "normal_quantile_threshold": normal_threshold,
        "mixed_quantile_threshold": mixed_threshold,
        "recommended_anomaly_score_threshold": recommended_threshold,
        "recommended_min_flag_window": config["recommended_threshold_policy"]["minimum_flag_window"],
    }

    if "scenario_tag" in frame.columns:
        flagged = frame.with_columns((pl.col("anomaly_score") >= recommended_threshold).alias("predicted_flag"))
        recommendation["scenario_flag_rates"] = flagged.group_by("scenario_tag").agg(pl.col("predicted_flag").mean()).to_dicts()
        normal_slice = flagged.filter(pl.col("scenario_tag") == "normal")
        anomalous_slice = flagged.filter(pl.col("scenario_tag") == "anomalous")
        recommendation["false_positive_rate_on_normal"] = (
            float(normal_slice.get_column("predicted_flag").mean()) if normal_slice.height > 0 else None
        )
        recommendation["flag_rate_on_anomalous"] = (
            float(anomalous_slice.get_column("predicted_flag").mean()) if anomalous_slice.height > 0 else None
        )

    output_path = paths.artifacts_dir / "reports" / "threshold_recommendation_v1.json"
    write_json(output_path, recommendation)

    print(json.dumps(
        {
            "status": "ok",
            "output_path": str(output_path),
            "recommended_threshold": recommended_threshold,
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
