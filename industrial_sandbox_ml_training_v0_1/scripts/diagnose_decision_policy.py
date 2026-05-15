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

from src.evaluation import (
    apply_service_thresholds,
    build_service_score_distribution_svg,
    build_top_outliers_markdown,
    compute_flagged_metrics,
    compute_threshold_metrics,
    derive_analysis_columns,
)
from src.utils import FEATURE_COLUMNS, ensure_feature_columns, get_project_paths, load_json, read_frame, timestamp_utc, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose score-vs-threshold policy effects for Isolation Forest.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/evaluation/decision_diagnostics_v1.json"),
        help="Decision diagnostics config path.",
    )
    return parser.parse_args()


def _build_score_frame(frame: pl.DataFrame, *, raw_scores: list[float], anomaly_scores: list[float], policy_name: str) -> pl.DataFrame:
    scored = frame.with_columns(
        pl.Series(name="raw_score", values=raw_scores),
        pl.Series(name="anomaly_score", values=anomaly_scores),
        pl.lit(policy_name).alias("score_policy"),
    )
    return derive_analysis_columns(scored)


def _normal_quantile_threshold(frame: pl.DataFrame, *, target_false_positive_rate: float) -> float:
    normal_slice = frame.filter(pl.col("scenario_tag") == "normal")
    quantile = max(0.0, min(1.0, 1.0 - target_false_positive_rate))
    return float(normal_slice.get_column("anomaly_score").quantile(quantile))


def _service_thresholds(frame: pl.DataFrame, *, target_false_positive_rate: float) -> dict[str, float]:
    quantile = max(0.0, min(1.0, 1.0 - target_false_positive_rate))
    thresholds: dict[str, float] = {}
    for service_name in sorted(frame.get_column("service_name").unique().to_list()):
        service_normal = frame.filter((pl.col("service_name") == service_name) & (pl.col("scenario_tag") == "normal"))
        thresholds[service_name] = float(service_normal.get_column("anomaly_score").quantile(quantile))
    return thresholds


def _top_outliers_by_service_markdown(frame: pl.DataFrame, path: Path, *, score_policy: str, top_n_per_service: int) -> Path:
    lines = [
        f"# Top Outliers By Service - {score_policy}",
        "",
    ]
    for service_name in sorted(frame.get_column("service_name").unique().to_list()):
        lines.extend(
            [
                f"## {service_name}",
                "",
                "| rank | scenario | anomaly_score | latency_ms | queue_length | http_5xx_rate | event_id |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        rows = (
            frame.filter(pl.col("service_name") == service_name)
            .sort("anomaly_score", descending=True)
            .select(["scenario_tag", "anomaly_score", "latency_ms", "queue_length", "http_5xx_rate", "event_id"])
            .head(top_n_per_service)
            .to_dicts()
        )
        for index, row in enumerate(rows, start=1):
            lines.append(
                "| {rank} | {scenario} | {score:.6f} | {latency:.3f} | {queue:.3f} | {http5xx:.3f} | `{event_id}` |".format(
                    rank=index,
                    scenario=row["scenario_tag"],
                    score=float(row["anomaly_score"]),
                    latency=float(row["latency_ms"]),
                    queue=float(row["queue_length"]),
                    http5xx=float(row["http_5xx_rate"]),
                    event_id=row["event_id"],
                )
            )
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _summarize_variant(
    *,
    policy_name: str,
    threshold_mode: str,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    return {
        "score_policy": policy_name,
        "threshold_mode": threshold_mode,
        "threshold": metrics.get("threshold"),
        "threshold_by_service": metrics.get("threshold_by_service"),
        "flag_rate_overall": metrics.get("flag_rate_overall"),
        "false_positive_rate_on_normal": metrics.get("false_positive_rate_on_normal"),
        "true_positive_rate_on_anomalous": metrics.get("true_positive_rate_on_anomalous"),
        "service_flag_rate_span": metrics.get("service_flag_rate_span"),
        "service_flag_rates": metrics.get("service_flag_rates"),
    }


def _write_report(path: Path, *, variants: list[dict[str, Any]], conclusion: str) -> Path:
    lines = [
        "# Decision Policy Diagnostics",
        "",
        "## Conclusion",
        f"- {conclusion}",
        "",
        "## Variant Table",
        "| score policy | threshold mode | threshold | TPR anomalous | FPR normal | service span | overall flag rate |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in variants:
        threshold_repr = f"{float(row['threshold']):.6f}" if row.get("threshold") is not None else "service-specific"
        lines.append(
            "| {policy} | {mode} | {threshold} | {tpr:.6f} | {fpr:.6f} | {span:.6f} | {flag:.6f} |".format(
                policy=row["score_policy"],
                mode=row["threshold_mode"],
                threshold=threshold_repr,
                tpr=float(row.get("true_positive_rate_on_anomalous") or 0.0),
                fpr=float(row.get("false_positive_rate_on_normal") or 0.0),
                span=float(row.get("service_flag_rate_span") or 0.0),
                flag=float(row.get("flag_rate_overall") or 0.0),
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
    shadow_profile = load_json(paths.root / config["shadow_threshold_profile"])
    global_threshold = float(shadow_profile["anomaly_score_threshold"])

    model_dir = paths.root / config["model_dir"]
    model_path = model_dir / "model.joblib"
    model = joblib.load(model_path)

    frame = read_frame(paths.root / config["validation_dataset"])
    ensure_feature_columns(frame.columns)
    x = frame.select(list(FEATURE_COLUMNS)).to_numpy()

    score_samples_raw = model.score_samples(x)
    score_samples_frame = _build_score_frame(
        frame,
        raw_scores=list(score_samples_raw),
        anomaly_scores=list(-score_samples_raw),
        policy_name="score_samples",
    )
    score_samples_global = compute_threshold_metrics(score_samples_frame, global_threshold)
    target_fpr = float(score_samples_global["false_positive_rate_on_normal"] or 0.0)
    score_samples_service_thresholds = _service_thresholds(score_samples_frame, target_false_positive_rate=target_fpr)
    score_samples_service_frame = apply_service_thresholds(
        score_samples_frame,
        threshold_by_service=score_samples_service_thresholds,
    )
    score_samples_service = compute_flagged_metrics(
        score_samples_service_frame,
        threshold_mode="service_specific",
        threshold_by_service=score_samples_service_thresholds,
    )

    decision_raw = model.decision_function(x)
    decision_frame = _build_score_frame(
        frame,
        raw_scores=list(decision_raw),
        anomaly_scores=list(-decision_raw),
        policy_name="decision_function",
    )
    decision_global_threshold = _normal_quantile_threshold(decision_frame, target_false_positive_rate=target_fpr)
    decision_global = compute_threshold_metrics(decision_frame, decision_global_threshold)
    decision_service_thresholds = _service_thresholds(decision_frame, target_false_positive_rate=target_fpr)
    decision_service_frame = apply_service_thresholds(
        decision_frame,
        threshold_by_service=decision_service_thresholds,
    )
    decision_service = compute_flagged_metrics(
        decision_service_frame,
        threshold_mode="service_specific",
        threshold_by_service=decision_service_thresholds,
    )

    prefix = config["output_prefix"]
    report_json_path = paths.artifacts_dir / "reports" / f"{prefix}.json"
    report_md_path = paths.artifacts_dir / "reports" / f"{prefix}.md"
    score_samples_dist_path = paths.artifacts_dir / "reports" / f"{prefix}_score_samples_by_service.svg"
    decision_dist_path = paths.artifacts_dir / "reports" / f"{prefix}_decision_function_by_service.svg"
    top_outliers_score_samples_path = paths.artifacts_dir / "reports" / f"{prefix}_score_samples_top_outliers_by_service.md"
    top_outliers_decision_path = paths.artifacts_dir / "reports" / f"{prefix}_decision_function_top_outliers_by_service.md"

    build_service_score_distribution_svg(
        score_samples_frame,
        score_samples_dist_path,
        title="score_samples anomaly-score distributions by service",
    )
    build_service_score_distribution_svg(
        decision_frame,
        decision_dist_path,
        title="decision_function anomaly-score distributions by service",
    )
    _top_outliers_by_service_markdown(
        score_samples_frame,
        top_outliers_score_samples_path,
        score_policy="score_samples",
        top_n_per_service=config["top_n_outliers_per_policy"],
    )
    _top_outliers_by_service_markdown(
        decision_frame,
        top_outliers_decision_path,
        score_policy="decision_function",
        top_n_per_service=config["top_n_outliers_per_policy"],
    )
    build_top_outliers_markdown(
        score_samples_frame,
        paths.artifacts_dir / "reports" / f"{prefix}_score_samples_top_outliers.md",
        top_n=config["top_n_outliers_per_policy"] * 2,
    )
    build_top_outliers_markdown(
        decision_frame,
        paths.artifacts_dir / "reports" / f"{prefix}_decision_function_top_outliers.md",
        top_n=config["top_n_outliers_per_policy"] * 2,
    )

    variants = [
        _summarize_variant(policy_name="score_samples", threshold_mode="global", metrics=score_samples_global),
        _summarize_variant(policy_name="score_samples", threshold_mode="service_specific", metrics=score_samples_service),
        _summarize_variant(policy_name="decision_function", threshold_mode="global", metrics=decision_global),
        _summarize_variant(policy_name="decision_function", threshold_mode="service_specific", metrics=decision_service),
    ]

    best_span_row = min(variants, key=lambda row: float(row.get("service_flag_rate_span") or 999.0))
    conclusion = (
        f"Best service homogeneity came from {best_span_row['score_policy']} + {best_span_row['threshold_mode']}; "
        f"service span={float(best_span_row['service_flag_rate_span'] or 0.0):.6f}."
    )

    write_json(
        report_json_path,
        {
            "created_at": timestamp_utc(),
            "config_path": str(config_path),
            "model_path": str(model_path),
            "validation_dataset": str(paths.root / config["validation_dataset"]),
            "global_shadow_threshold": global_threshold,
            "matched_false_positive_rate_target": target_fpr,
            "variants": variants,
            "distribution_artifacts": {
                "score_samples_by_service": str(score_samples_dist_path),
                "decision_function_by_service": str(decision_dist_path),
            },
            "top_outlier_artifacts": {
                "score_samples_by_service": str(top_outliers_score_samples_path),
                "decision_function_by_service": str(top_outliers_decision_path),
            },
            "conclusion": conclusion,
        },
    )
    _write_report(report_md_path, variants=variants, conclusion=conclusion)

    print(
        json.dumps(
            {
                "status": "ok",
                "report_json_path": str(report_json_path),
                "report_md_path": str(report_md_path),
                "best_variant": best_span_row,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
