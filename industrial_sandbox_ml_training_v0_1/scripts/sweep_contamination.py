#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import polars as pl

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.evaluation import compute_threshold_metrics, derive_analysis_columns
from src.training import train_iforest_artifact
from src.utils import ensure_feature_columns, get_project_paths, load_json, read_frame, timestamp_utc, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Retrain and compare multiple contamination values.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/training/contamination_sweep_v1.json"),
        help="Contamination sweep config path.",
    )
    return parser.parse_args()


def _safe_label(value: float) -> str:
    return str(value).replace(".", "p")


def _evaluate_model(model: Any, frame: pl.DataFrame, threshold: float) -> dict[str, Any]:
    x = frame.select(
        [
            "cpu_pct",
            "memory_pct",
            "latency_ms",
            "disk_io_pct",
            "net_error_rate",
            "queue_length",
            "throughput_rate",
            "http_5xx_rate",
        ]
    ).to_numpy()
    raw_scores = model.score_samples(x)
    anomaly_scores = [-score for score in raw_scores]
    scored = frame.with_columns(
        pl.Series(name="raw_score", values=raw_scores),
        pl.Series(name="anomaly_score", values=anomaly_scores),
    )
    scored = derive_analysis_columns(scored)
    return compute_threshold_metrics(scored, threshold)


def _select_recommendation(rows: list[dict[str, Any]], policy: dict[str, Any]) -> dict[str, Any] | None:
    eligible = [
        row
        for row in rows
        if (row.get("true_positive_rate_on_anomalous") or 0.0) >= policy["minimum_true_positive_rate_on_anomalous"]
        and (row.get("false_positive_rate_on_normal") or 0.0) <= policy["maximum_false_positive_rate_on_normal"]
    ]
    if not eligible:
        return None
    return sorted(
        eligible,
        key=lambda row: (
            row.get("service_flag_rate_span") or 999.0,
            -(row.get("true_positive_rate_on_anomalous") or 0.0),
            row.get("false_positive_rate_on_normal") or 999.0,
        ),
    )[0]


def _write_markdown_report(path: Path, rows: list[dict[str, Any]], recommendation: dict[str, Any] | None) -> Path:
    contamination_effect_detected = len(
        {
            (
                round(float(row.get("flag_rate_overall") or 0.0), 9),
                round(float(row.get("false_positive_rate_on_normal") or 0.0), 9),
                round(float(row.get("true_positive_rate_on_anomalous") or 0.0), 9),
                round(float(row.get("service_flag_rate_span") or 0.0), 9),
            )
            for row in rows
        }
    ) > 1
    lines = [
        "# Contamination Sweep Report",
        "",
        "## Recommendation",
        f"- recommended_available: `{recommendation is not None}`",
        f"- contamination_effect_detected: `{contamination_effect_detected}`",
    ]
    if recommendation is not None:
        lines.extend(
            [
                f"- contamination: `{recommendation['contamination']}`",
                f"- threshold: `{recommendation['shadow_threshold']:.6f}`",
                f"- TPR anomalous: `{recommendation['true_positive_rate_on_anomalous']:.6f}`",
                f"- FPR normal: `{recommendation['false_positive_rate_on_normal']:.6f}`",
                f"- service span: `{recommendation['service_flag_rate_span']:.6f}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Candidate Table",
            "| contamination | TPR anomalous | FPR normal | service span | overall flag rate | burst flag rate | late drift flag rate |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in rows:
        lines.append(
            "| {contamination} | {tpr:.6f} | {fpr:.6f} | {span:.6f} | {flag:.6f} | {burst:.6f} | {late:.6f} |".format(
                contamination=row["contamination"],
                tpr=float(row.get("true_positive_rate_on_anomalous") or 0.0),
                fpr=float(row.get("false_positive_rate_on_normal") or 0.0),
                span=float(row.get("service_flag_rate_span") or 0.0),
                flag=float(row.get("flag_rate_overall") or 0.0),
                burst=float(row.get("burst_proxy_flag_rate") or 0.0),
                late=float(row.get("late_drift_flag_rate") or 0.0),
            )
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    args = parse_args()
    paths = get_project_paths()

    config_path = args.config if args.config.is_absolute() else paths.root / args.config
    config = load_json(config_path)
    base_training_config = load_json(paths.root / config["base_training_config"])
    shadow_profile = load_json(paths.root / config["shadow_threshold_profile"])
    threshold = float(shadow_profile["anomaly_score_threshold"])

    training_dataset_path = paths.root / base_training_config["training_dataset"]
    validation_dataset_path = paths.root / config["validation_dataset"]
    training_frame = read_frame(training_dataset_path)
    validation_frame = derive_analysis_columns(read_frame(validation_dataset_path))
    ensure_feature_columns(training_frame.columns)
    ensure_feature_columns(validation_frame.columns)

    if "generated_at" in training_frame.columns:
        training_frame = training_frame.sort("generated_at")

    experiment_root = paths.root / config["experiment_output_dir"]
    metrics_output_path = paths.root / config["metrics_output_path"]
    report_output_path = paths.root / config["report_output_path"]
    markdown_output_path = paths.root / config["markdown_output_path"]

    rows: list[dict[str, Any]] = []
    for contamination in config["contamination_values"]:
        contamination_label = _safe_label(float(contamination))
        artifact_dir = experiment_root / f"contamination_{contamination_label}"
        result = train_iforest_artifact(
            frame=training_frame,
            dataset_path=training_dataset_path,
            output_dir=artifact_dir,
            model_version=f"contamination_{contamination_label}",
            hyperparameters={**base_training_config["hyperparameters"], "contamination": float(contamination)},
            feature_contract_path=paths.contracts_dir / "feature_contract_v1.json",
            metrics_path=paths.artifacts_dir / "metrics" / f"training_contamination_{contamination_label}.json",
            report_path=paths.artifacts_dir / "reports" / f"training_contamination_{contamination_label}.md",
        )
        evaluation = _evaluate_model(result["model"], validation_frame, threshold)
        burst_flag_rate = None
        late_drift_flag_rate = None
        payments_flag_rate = None
        orders_flag_rate = None
        checkout_flag_rate = None
        for row in evaluation.get("burst_slice_metrics", []):
            if row.get("burst_proxy") is True:
                burst_flag_rate = row.get("flag_rate")
        for row in evaluation.get("drift_slice_metrics", []):
            if row.get("drift_slice") == "late":
                late_drift_flag_rate = row.get("flag_rate")
        for row in evaluation.get("service_flag_rates", []):
            if row.get("service_name") == "payments-api":
                payments_flag_rate = row.get("flag_rate")
            if row.get("service_name") == "orders-api":
                orders_flag_rate = row.get("flag_rate")
            if row.get("service_name") == "checkout-api":
                checkout_flag_rate = row.get("flag_rate")

        rows.append(
            {
                "contamination": float(contamination),
                "shadow_threshold": threshold,
                "model_dir": str(artifact_dir),
                "training_metrics_path": str(result["metrics_path"]),
                "flag_rate_overall": evaluation.get("flag_rate_overall"),
                "false_positive_rate_on_normal": evaluation.get("false_positive_rate_on_normal"),
                "true_positive_rate_on_anomalous": evaluation.get("true_positive_rate_on_anomalous"),
                "service_flag_rate_span": evaluation.get("service_flag_rate_span"),
                "burst_proxy_flag_rate": burst_flag_rate,
                "late_drift_flag_rate": late_drift_flag_rate,
                "payments_flag_rate": payments_flag_rate,
                "orders_flag_rate": orders_flag_rate,
                "checkout_flag_rate": checkout_flag_rate,
            }
        )

    recommendation = _select_recommendation(rows, config["selection_policy"])
    contamination_effect_detected = len(
        {
            (
                round(float(row.get("flag_rate_overall") or 0.0), 9),
                round(float(row.get("false_positive_rate_on_normal") or 0.0), 9),
                round(float(row.get("true_positive_rate_on_anomalous") or 0.0), 9),
                round(float(row.get("service_flag_rate_span") or 0.0), 9),
            )
            for row in rows
        }
    ) > 1
    pl.DataFrame(rows).write_parquet(metrics_output_path)
    write_json(
        report_output_path,
        {
            "created_at": timestamp_utc(),
            "config_path": str(config_path),
            "training_dataset": str(training_dataset_path),
            "validation_dataset": str(validation_dataset_path),
            "shadow_profile": shadow_profile,
            "selection_policy": config["selection_policy"],
            "contamination_effect_detected": contamination_effect_detected,
            "interpretation": (
                "Changing contamination does not affect score_samples-based thresholding in the current pipeline."
                if not contamination_effect_detected
                else "Changing contamination altered the evaluated operating metrics."
            ),
            "recommendation": recommendation,
            "rows": rows,
        },
    )
    _write_markdown_report(markdown_output_path, rows, recommendation)

    print(
        json.dumps(
            {
                "status": "ok",
                "row_count": len(rows),
                "recommendation": recommendation,
                "report_path": str(report_output_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
