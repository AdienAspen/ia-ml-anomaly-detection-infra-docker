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

from src.evaluation import compute_threshold_metrics, derive_analysis_columns, generate_threshold_grid
from src.utils import get_project_paths, load_json, read_frame, timestamp_utc, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sweep thresholds over a scored validation dataset.")
    parser.add_argument("scores", type=Path, help="Scores parquet emitted by evaluate_iforest.py.")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/evaluation/threshold_calibration_v1.json"),
        help="Threshold sweep config.",
    )
    parser.add_argument("--output-prefix", default="threshold_sweep_v1", help="Output prefix under artifacts.")
    return parser.parse_args()


def _recommend_threshold(rows: list[dict[str, float | None]], criteria: dict[str, float]) -> tuple[dict[str, float | None] | None, str]:
    eligible = [
        row
        for row in rows
        if (row.get("false_positive_rate_on_normal") or 0.0) <= criteria["max_false_positive_rate_on_normal"]
        and (row.get("service_flag_rate_span") or 0.0) <= criteria["max_service_flag_rate_span"]
        and (row.get("true_positive_rate_on_anomalous") or 0.0) >= criteria["minimum_true_positive_rate_on_anomalous"]
    ]
    if eligible:
        ranked = sorted(
            eligible,
            key=lambda row: (
                -(row.get("true_positive_rate_on_anomalous") or 0.0),
                row.get("false_positive_rate_on_normal") or 0.0,
                row.get("service_flag_rate_span") or 0.0,
            ),
        )
        return ranked[0], "strict_operating_criteria"

    return None, "no_threshold_met_strict_operating_criteria"


def _pick_profile(rows: list[dict[str, float | None]], *, max_fpr: float) -> dict[str, float | None]:
    eligible = [row for row in rows if (row.get("false_positive_rate_on_normal") or 0.0) <= max_fpr]
    if not eligible:
        return min(
            rows,
            key=lambda row: abs((row.get("false_positive_rate_on_normal") or 0.0) - max_fpr),
        )
    return sorted(
        eligible,
        key=lambda row: (
            -((row.get("true_positive_rate_on_anomalous") or 0.0)),
            row.get("false_positive_rate_on_normal") or 0.0,
        ),
    )[0]


def _write_markdown_report(
    path: Path,
    rows: list[dict[str, float | None]],
    strict_recommendation: dict[str, float | None] | None,
    reason: str,
    profiles: dict[str, dict[str, float | None]],
) -> Path:
    top_rows = sorted(
        rows,
        key=lambda row: (
            abs((row.get("false_positive_rate_on_normal") or 0.0) - 0.1),
            -(row.get("true_positive_rate_on_anomalous") or 0.0),
        ),
    )[:8]
    lines = [
        "# Threshold Sweep Report",
        "",
        "## Strict Criteria",
        f"- status: `{reason}`",
        f"- strict_recommendation_available: `{strict_recommendation is not None}`",
        "",
        "## Operating Profiles",
    ]
    for profile_name, profile in profiles.items():
        lines.append(
            f"- `{profile_name}` threshold `{float(profile['threshold']):.6f}` | TPR `{float(profile.get('true_positive_rate_on_anomalous') or 0.0):.6f}` | FPR `{float(profile.get('false_positive_rate_on_normal') or 0.0):.6f}` | span `{float(profile.get('service_flag_rate_span') or 0.0):.6f}`"
        )
    lines.extend(
        [
            "",
        "## Candidate Table",
        "| threshold | TPR anomalous | FPR normal | overall flag rate | service span | burst flag rate | late drift flag rate |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in top_rows:
        lines.append(
            "| {threshold:.6f} | {tpr:.6f} | {fpr:.6f} | {flag:.6f} | {span:.6f} | {burst:.6f} | {late:.6f} |".format(
                threshold=float(row["threshold"]),
                tpr=float(row.get("true_positive_rate_on_anomalous") or 0.0),
                fpr=float(row.get("false_positive_rate_on_normal") or 0.0),
                flag=float(row.get("flag_rate_overall") or 0.0),
                span=float(row.get("service_flag_rate_span") or 0.0),
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
    frame = derive_analysis_columns(read_frame(args.scores))

    if "anomaly_score" not in frame.columns or "raw_score" not in frame.columns:
        raise ValueError("Scores dataset must include `raw_score` and `anomaly_score` columns.")

    sweep_config = config["threshold_sweep"]
    thresholds = generate_threshold_grid(
        frame.get_column("anomaly_score").to_numpy(),
        quantiles=list(sweep_config["quantiles"]),
        include_thresholds=list(sweep_config.get("include_thresholds", [])),
    )

    rows: list[dict[str, float | None]] = []
    for threshold in thresholds:
        metrics = compute_threshold_metrics(frame, threshold)
        burst_proxy_flag_rate = None
        late_drift_flag_rate = None
        for row in metrics.get("burst_slice_metrics", []):
            if row.get("burst_proxy") is True:
                burst_proxy_flag_rate = float(row.get("flag_rate") or 0.0)
        for row in metrics.get("drift_slice_metrics", []):
            if row.get("drift_slice") == "late":
                late_drift_flag_rate = float(row.get("flag_rate") or 0.0)

        rows.append(
            {
                "threshold": float(threshold),
                "flag_rate_overall": float(metrics.get("flag_rate_overall") or 0.0),
                "false_positive_rate_on_normal": metrics.get("false_positive_rate_on_normal"),
                "true_positive_rate_on_anomalous": metrics.get("true_positive_rate_on_anomalous"),
                "service_flag_rate_span": metrics.get("service_flag_rate_span"),
                "burst_proxy_flag_rate": burst_proxy_flag_rate,
                "late_drift_flag_rate": late_drift_flag_rate,
            }
        )

    strict_recommendation, reason = _recommend_threshold(rows, sweep_config["operating_criteria"])
    profiles = {
        "sensitivity": _pick_profile(rows, max_fpr=0.12),
        "balanced": _pick_profile(rows, max_fpr=0.05),
        "conservative": _pick_profile(rows, max_fpr=0.01),
    }

    output_json_path = paths.artifacts_dir / "reports" / f"{args.output_prefix}.json"
    output_parquet_path = paths.artifacts_dir / "metrics" / f"{args.output_prefix}.parquet"
    output_md_path = paths.artifacts_dir / "reports" / f"{args.output_prefix}.md"

    pl.DataFrame(rows).write_parquet(output_parquet_path)
    write_json(
        output_json_path,
        {
            "created_at": timestamp_utc(),
            "scores_path": str(args.scores),
            "config_path": str(config_path),
            "criteria": sweep_config["operating_criteria"],
            "recommendation_reason": reason,
            "strict_recommendation": strict_recommendation,
            "operating_profiles": profiles,
            "sweep_rows": rows,
        },
    )
    _write_markdown_report(output_md_path, rows, strict_recommendation, reason, profiles)

    print(
        json.dumps(
            {
                "status": "ok",
                "rows": len(rows),
                "balanced_threshold": profiles["balanced"]["threshold"],
                "report_path": str(output_json_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
