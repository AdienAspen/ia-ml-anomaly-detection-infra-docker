"""Feature analysis and statistical baselining for the HDBSCAN temporal lane."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean, pstdev
from typing import Any
import json

from src.scenario_engine import scenario_catalog
from src.train_hdbscan_temporal import (
    FEATURE_VIEW_PATH,
    METRICS_PATH,
    WINDOWS_PATH,
    ensure_training_inputs,
    filter_windows_for_training,
    load_training_config,
    prepare_training_rows,
)
from src.validate_correlation_engine import SUMMARY_PATH

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FEATURE_ANALYSIS_PATH = PROJECT_ROOT / "artifacts" / "metrics" / "feature_analysis_summary_v0_1.json"
STATISTICAL_BASELINE_PATH = PROJECT_ROOT / "artifacts" / "metrics" / "statistical_baseline_v0_1.json"
REPORT_PATH = PROJECT_ROOT / "reports" / "internal_hdbscan_benchmark_report.md"


def build_feature_analysis_bundle() -> dict[str, Any]:
    windows, feature_rows = ensure_training_inputs()
    config = load_training_config()
    eligible_windows, low_quality_windows = filter_windows_for_training(windows, config)
    feature_index = {row["window_id"]: row for row in feature_rows}
    _matrix, feature_keys, _metadata_rows = prepare_training_rows(eligible_windows, feature_index)

    rows = [feature_index[window["window_id"]] for window in eligible_windows if window["window_id"] in feature_index]
    per_feature_values = {
        key: [_to_float(row.get(key)) for row in rows]
        for key in feature_keys
    }

    scenario_lookup = scenario_catalog()
    positive_rows = [row for row in rows if scenario_lookup.get(row.get("scenario_tag")) and scenario_lookup[row.get("scenario_tag")].expected_propagation]
    negative_rows = [row for row in rows if not (scenario_lookup.get(row.get("scenario_tag")) and scenario_lookup[row.get("scenario_tag")].expected_propagation)]

    feature_analysis_summary = {
        "schema_version": "feature_analysis_summary_v0_1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "eligible_window_count": len(eligible_windows),
        "low_quality_window_count": len(low_quality_windows),
        "feature_count": len(feature_keys),
        "feature_keys": feature_keys,
        "variance_ranking": _variance_ranking(per_feature_values),
        "top_absolute_correlations": _top_absolute_correlations(per_feature_values),
        "feature_signal_contrast": _feature_signal_contrast(feature_keys, positive_rows, negative_rows),
    }

    statistical_baseline = {
        "schema_version": "statistical_baseline_v0_1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "eligible_window_count": len(eligible_windows),
        "features": {
            key: _statistical_profile(per_feature_values[key])
            for key in feature_keys
        },
    }

    validation_summary = _load_optional_json(SUMMARY_PATH)
    training_summary = _load_optional_json(METRICS_PATH)
    report_markdown = _render_report(
        feature_analysis_summary=feature_analysis_summary,
        statistical_baseline=statistical_baseline,
        training_summary=training_summary,
        validation_summary=validation_summary,
    )

    return {
        "feature_analysis_summary": feature_analysis_summary,
        "statistical_baseline": statistical_baseline,
        "report_markdown": report_markdown,
    }


def export_feature_analysis_bundle(bundle: dict[str, Any]) -> None:
    FEATURE_ANALYSIS_PATH.parent.mkdir(parents=True, exist_ok=True)
    FEATURE_ANALYSIS_PATH.write_text(json.dumps(bundle["feature_analysis_summary"], indent=2), encoding="utf-8")
    STATISTICAL_BASELINE_PATH.write_text(json.dumps(bundle["statistical_baseline"], indent=2), encoding="utf-8")
    REPORT_PATH.write_text(bundle["report_markdown"], encoding="utf-8")


def main() -> int:
    bundle = build_feature_analysis_bundle()
    export_feature_analysis_bundle(bundle)
    print(
        "Feature analysis ready: "
        f"features={bundle['feature_analysis_summary']['feature_count']}, "
        f"windows={bundle['feature_analysis_summary']['eligible_window_count']}"
    )
    return 0


def _variance_ranking(per_feature_values: dict[str, list[float]]) -> list[dict[str, Any]]:
    ranking = []
    for feature_name, values in per_feature_values.items():
        ranking.append(
            {
                "feature": feature_name,
                "variance": round(_variance(values), 6),
                "std_dev": round(pstdev(values), 6) if len(values) > 1 else 0.0,
            }
        )
    ranking.sort(key=lambda item: item["variance"], reverse=True)
    return ranking


def _top_absolute_correlations(per_feature_values: dict[str, list[float]], limit: int = 10) -> list[dict[str, Any]]:
    feature_names = sorted(per_feature_values)
    correlations: list[dict[str, Any]] = []
    for index, left_name in enumerate(feature_names):
        for right_name in feature_names[index + 1 :]:
            coefficient = _pearson(per_feature_values[left_name], per_feature_values[right_name])
            if coefficient is None:
                continue
            correlations.append(
                {
                    "left_feature": left_name,
                    "right_feature": right_name,
                    "pearson": round(coefficient, 6),
                    "abs_pearson": round(abs(coefficient), 6),
                }
            )
    correlations.sort(key=lambda item: item["abs_pearson"], reverse=True)
    return correlations[:limit]


def _feature_signal_contrast(
    feature_keys: list[str],
    positive_rows: list[dict[str, Any]],
    negative_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    output = []
    for key in feature_keys:
        positive_values = [_to_float(row.get(key)) for row in positive_rows]
        negative_values = [_to_float(row.get(key)) for row in negative_rows]
        positive_mean = fmean(positive_values) if positive_values else 0.0
        negative_mean = fmean(negative_values) if negative_values else 0.0
        pooled_scale = max(abs(positive_mean) + abs(negative_mean), 1e-9)
        contrast = abs(positive_mean - negative_mean) / pooled_scale
        output.append(
            {
                "feature": key,
                "positive_mean": round(positive_mean, 6),
                "negative_mean": round(negative_mean, 6),
                "relative_contrast": round(contrast, 6),
            }
        )
    output.sort(key=lambda item: item["relative_contrast"], reverse=True)
    return output


def _statistical_profile(values: list[float]) -> dict[str, Any]:
    clean = list(values)
    zero_ratio = sum(1 for value in clean if value == 0.0) / max(len(clean), 1)
    return {
        "count": len(clean),
        "mean": round(fmean(clean), 6) if clean else 0.0,
        "std_dev": round(pstdev(clean), 6) if len(clean) > 1 else 0.0,
        "min": round(min(clean), 6) if clean else 0.0,
        "p50": _percentile(clean, 0.50),
        "p90": _percentile(clean, 0.90),
        "p95": _percentile(clean, 0.95),
        "max": round(max(clean), 6) if clean else 0.0,
        "zero_ratio": round(zero_ratio, 6),
    }


def _render_report(*, feature_analysis_summary: dict[str, Any], statistical_baseline: dict[str, Any], training_summary: dict[str, Any], validation_summary: dict[str, Any]) -> str:
    top_variance = feature_analysis_summary["variance_ranking"][:5]
    top_correlation = feature_analysis_summary["top_absolute_correlations"][:5]
    top_contrast = feature_analysis_summary["feature_signal_contrast"][:5]

    lines = [
        "# Internal HDBSCAN Benchmark Report",
        "",
        "## Executive Summary",
        "- This report summarizes the current internal benchmark baseline for the temporal HDBSCAN correlation engine.",
        f"- Eligible training windows: {feature_analysis_summary['eligible_window_count']}",
        f"- Low-quality training windows excluded: {feature_analysis_summary['low_quality_window_count']}",
        f"- Active feature count: {feature_analysis_summary['feature_count']}",
        "",
        "## Current Validation Snapshot",
        f"- propagation_detection_rate: {validation_summary.get('propagation_detection_rate', 'n/a')}",
        f"- false_propagation_rate: {validation_summary.get('false_propagation_rate', 'n/a')}",
        f"- noise_rejection_rate: {validation_summary.get('noise_rejection_rate', 'n/a')}",
        f"- propagation_order_accuracy: {validation_summary.get('propagation_order_accuracy', 'n/a')}",
        f"- cluster_stability: {validation_summary.get('cluster_stability', 'n/a')}",
        "",
        "## Top Variance Features",
        "| feature | variance | std_dev |",
        "|---|---:|---:|",
    ]
    for row in top_variance:
        lines.append(f"| {row['feature']} | {row['variance']} | {row['std_dev']} |")

    lines.extend([
        "",
        "## Top Absolute Correlations",
        "| left_feature | right_feature | pearson |",
        "|---|---|---:|",
    ])
    for row in top_correlation:
        lines.append(f"| {row['left_feature']} | {row['right_feature']} | {row['pearson']} |")

    lines.extend([
        "",
        "## Top Positive/Negative Contrast Features",
        "| feature | positive_mean | negative_mean | relative_contrast |",
        "|---|---:|---:|---:|",
    ])
    for row in top_contrast:
        lines.append(f"| {row['feature']} | {row['positive_mean']} | {row['negative_mean']} | {row['relative_contrast']} |")

    lines.extend([
        "",
        "## Interpretation Notes",
        "- This block is exploratory and diagnostic, not a supervised feature-importance ranking.",
        "- High variance or high correlation does not automatically mean high operational value.",
        "- The next tuning cycle should use this report to reduce redundancy, inspect unstable dimensions and target recall loss with more evidence.",
        "- PCA and autoencoders remain future options; they are intentionally not introduced in this baseline step.",
        "",
        "## Statistical Baselining",
        f"- Baseline artifact: {STATISTICAL_BASELINE_PATH}",
        f"- Training summary artifact: {METRICS_PATH}",
        f"- Validation summary artifact: {SUMMARY_PATH}",
    ])
    return "\n".join(lines)


def _pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = fmean(left)
    right_mean = fmean(right)
    left_centered = [value - left_mean for value in left]
    right_centered = [value - right_mean for value in right]
    numerator = sum(a * b for a, b in zip(left_centered, right_centered))
    left_scale = sum(a * a for a in left_centered) ** 0.5
    right_scale = sum(b * b for b in right_centered) ** 0.5
    denominator = left_scale * right_scale
    if denominator == 0.0:
        return None
    return numerator / denominator


def _variance(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = fmean(values)
    return sum((value - mean) ** 2 for value in values) / len(values)


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 6)
    index = ratio * (len(ordered) - 1)
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    interpolated = ordered[lower] * (1.0 - weight) + ordered[upper] * weight
    return round(interpolated, 6)


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def _load_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
