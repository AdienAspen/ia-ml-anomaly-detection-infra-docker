#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import joblib
import polars as pl

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.evaluation import apply_service_thresholds, compute_flagged_metrics, compute_threshold_metrics, derive_analysis_columns
from src.utils import FEATURE_COLUMNS, ensure_feature_columns, get_project_paths, load_json, read_frame, timestamp_utc, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run prolonged shadow analysis with service-specific thresholds.")
    parser.add_argument(
        "--service-threshold-profile",
        type=Path,
        default=Path("configs/evaluation/shadow_threshold_service_v1.json"),
        help="Service-specific shadow threshold profile.",
    )
    parser.add_argument(
        "--global-threshold-profile",
        type=Path,
        default=Path("configs/evaluation/shadow_threshold_balanced_v1.json"),
        help="Global shadow threshold profile.",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("data/processed/validation_mixed_v1.parquet"),
        help="Shadow dataset path.",
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=Path("artifacts/models/isolation_forest/baseline_v1"),
        help="Model directory.",
    )
    parser.add_argument("--output-prefix", default="shadow_service_thresholds_v1", help="Artifacts output prefix.")
    return parser.parse_args()


def _score_frame(frame: pl.DataFrame, model_dir: Path) -> pl.DataFrame:
    model = joblib.load(model_dir / "model.joblib")
    x = frame.select(list(FEATURE_COLUMNS)).to_numpy()
    raw_scores = model.score_samples(x)
    anomaly_scores = [-score for score in raw_scores]
    scored = frame.with_columns(
        pl.Series(name="raw_score", values=raw_scores),
        pl.Series(name="anomaly_score", values=anomaly_scores),
    )
    return derive_analysis_columns(scored)


def _cycle_rows(flagged: pl.DataFrame, *, policy_name: str) -> list[dict[str, Any]]:
    if "temporal_bucket" not in flagged.columns:
        return []
    rows = (
        flagged.group_by(["temporal_bucket", "service_name"])
        .agg(
            pl.len().alias("row_count"),
            pl.col("predicted_flag").mean().alias("flag_rate"),
            pl.col("anomaly_score").mean().alias("anomaly_score_mean"),
            pl.when(pl.col("scenario_tag") == "anomalous").then(pl.col("predicted_flag")).otherwise(None).mean().alias("tpr_anomalous"),
            pl.when(pl.col("scenario_tag") == "normal").then(pl.col("predicted_flag")).otherwise(None).mean().alias("fpr_normal"),
        )
        .sort(["temporal_bucket", "service_name"])
        .to_dicts()
    )
    for row in rows:
        row["policy_name"] = policy_name
    return rows


def _cycle_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    frame = pl.DataFrame(rows)
    summary = (
        frame.group_by("temporal_bucket")
        .agg(
            pl.len().alias("service_count"),
            pl.col("flag_rate").mean().alias("mean_flag_rate"),
            (pl.col("flag_rate").max() - pl.col("flag_rate").min()).alias("service_span"),
            pl.col("tpr_anomalous").mean().alias("mean_tpr_anomalous"),
            pl.col("fpr_normal").mean().alias("mean_fpr_normal"),
        )
        .sort("temporal_bucket")
        .to_dicts()
    )
    return summary


def _persistence_summary(cycle_summary: list[dict[str, Any]]) -> dict[str, float | None]:
    if not cycle_summary:
        return {"mean_service_span": None, "max_service_span": None, "mean_tpr_anomalous": None, "mean_fpr_normal": None}
    service_spans = [float(row["service_span"]) for row in cycle_summary]
    tprs = [float(row["mean_tpr_anomalous"]) for row in cycle_summary if row.get("mean_tpr_anomalous") is not None]
    fprs = [float(row["mean_fpr_normal"]) for row in cycle_summary if row.get("mean_fpr_normal") is not None]
    return {
        "mean_service_span": sum(service_spans) / len(service_spans),
        "max_service_span": max(service_spans),
        "mean_tpr_anomalous": (sum(tprs) / len(tprs)) if tprs else None,
        "mean_fpr_normal": (sum(fprs) / len(fprs)) if fprs else None,
    }


def _write_report(path: Path, *, global_metrics: dict[str, Any], service_metrics: dict[str, Any], global_persistence: dict[str, Any], service_persistence: dict[str, Any]) -> Path:
    lines = [
        "# Prolonged Shadow Report",
        "",
        "## Summary",
        f"- global threshold service span: `{float(global_metrics['service_flag_rate_span'] or 0.0):.6f}`",
        f"- service-specific threshold service span: `{float(service_metrics['service_flag_rate_span'] or 0.0):.6f}`",
        f"- global mean cycle span: `{float(global_persistence['mean_service_span'] or 0.0):.6f}`",
        f"- service-threshold mean cycle span: `{float(service_persistence['mean_service_span'] or 0.0):.6f}`",
        f"- global TPR anomalous: `{float(global_metrics['true_positive_rate_on_anomalous'] or 0.0):.6f}`",
        f"- service-threshold TPR anomalous: `{float(service_metrics['true_positive_rate_on_anomalous'] or 0.0):.6f}`",
        "",
        "## Interpretation",
        "- if service-threshold cycle span stays low across buckets, the imbalance is mostly a decision-policy issue.",
        "- if service-threshold cycle span rises again strongly, the service heterogeneity is structural and thresholding only partially masks it.",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    args = parse_args()
    paths = get_project_paths()

    service_profile_path = (
        args.service_threshold_profile
        if args.service_threshold_profile.is_absolute()
        else paths.root / args.service_threshold_profile
    )
    global_profile_path = (
        args.global_threshold_profile
        if args.global_threshold_profile.is_absolute()
        else paths.root / args.global_threshold_profile
    )
    dataset_path = args.dataset if args.dataset.is_absolute() else paths.root / args.dataset
    model_dir = args.model_dir if args.model_dir.is_absolute() else paths.root / args.model_dir

    service_profile = load_json(service_profile_path)
    global_profile = load_json(global_profile_path)

    frame = read_frame(dataset_path)
    ensure_feature_columns(frame.columns)
    scored = _score_frame(frame, model_dir)

    global_threshold = float(global_profile["anomaly_score_threshold"])
    service_thresholds = {key: float(value) for key, value in service_profile["threshold_by_service"].items()}

    global_metrics = compute_threshold_metrics(scored, global_threshold)
    service_flagged = apply_service_thresholds(scored, threshold_by_service=service_thresholds)
    service_metrics = compute_flagged_metrics(
        service_flagged,
        threshold_mode="service_specific",
        threshold_by_service=service_thresholds,
    )

    global_flagged = scored.with_columns((pl.col("anomaly_score") >= global_threshold).alias("predicted_flag"))
    global_cycle_rows = _cycle_rows(global_flagged, policy_name="global")
    service_cycle_rows = _cycle_rows(service_flagged, policy_name="service_specific")
    global_cycle_summary = _cycle_summary(global_cycle_rows)
    service_cycle_summary = _cycle_summary(service_cycle_rows)
    global_persistence = _persistence_summary(global_cycle_summary)
    service_persistence = _persistence_summary(service_cycle_summary)

    metrics_path = paths.artifacts_dir / "metrics" / f"{args.output_prefix}_cycles.parquet"
    report_json_path = paths.artifacts_dir / "reports" / f"{args.output_prefix}.json"
    report_md_path = paths.artifacts_dir / "reports" / f"{args.output_prefix}.md"
    pl.DataFrame(global_cycle_rows + service_cycle_rows).write_parquet(metrics_path)
    write_json(
        report_json_path,
        {
            "created_at": timestamp_utc(),
            "dataset_path": str(dataset_path),
            "model_dir": str(model_dir),
            "global_threshold_profile": str(global_profile_path),
            "service_threshold_profile": str(service_profile_path),
            "global_metrics": global_metrics,
            "service_threshold_metrics": service_metrics,
            "global_cycle_summary": global_cycle_summary,
            "service_cycle_summary": service_cycle_summary,
            "global_persistence": global_persistence,
            "service_persistence": service_persistence,
            "interpretation": (
                "Service-specific thresholding stayed more homogeneous across temporal cycles than the global threshold."
                if (service_persistence["mean_service_span"] or 999.0) < (global_persistence["mean_service_span"] or 999.0)
                else "Service-specific thresholding did not improve temporal homogeneity versus the global threshold."
            ),
        },
    )
    _write_report(
        report_md_path,
        global_metrics=global_metrics,
        service_metrics=service_metrics,
        global_persistence=global_persistence,
        service_persistence=service_persistence,
    )

    print(
        json.dumps(
            {
                "status": "ok",
                "metrics_path": str(metrics_path),
                "report_json_path": str(report_json_path),
                "report_md_path": str(report_md_path),
                "service_mean_cycle_span": service_persistence["mean_service_span"],
                "global_mean_cycle_span": global_persistence["mean_service_span"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
