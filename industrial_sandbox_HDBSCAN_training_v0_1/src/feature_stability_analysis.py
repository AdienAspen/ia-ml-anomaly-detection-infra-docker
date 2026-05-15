"""Bootstrap-style feature stability analysis for the temporal HDBSCAN lane."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from random import Random
from statistics import fmean
from typing import Any
import json

from src.build_hdbscan_temporal_feature_view import build_hdbscan_temporal_feature_view
from src.build_temporal_windows import build_temporal_windows, load_windowing_policy
from src.scenario_repository import load_validation_scenarios
from src.train_hdbscan_temporal import (
    build_events_from_profiles,
    cluster_feature_matrix,
    filter_windows_for_validation,
    load_training_config,
    prepare_training_rows,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "artifacts" / "metrics" / "feature_stability_analysis_v0_1.json"
REPORT_PATH = PROJECT_ROOT / "reports" / "feature_stability_analysis_report.md"
BOOTSTRAP_ITERATIONS = 12
BOOTSTRAP_SEED = 20260512
SIGNIFICANCE_DELTA = 0.03


def build_feature_stability_analysis() -> dict[str, Any]:
    config = load_training_config()
    profiles = load_validation_scenarios()
    validation_events = build_events_from_profiles(profiles, start_anchor=datetime(2026, 2, 1, tzinfo=timezone.utc))
    windows = build_temporal_windows(validation_events, policy=load_windowing_policy())
    feature_rows = build_hdbscan_temporal_feature_view(windows)
    feature_index = {row["window_id"]: row for row in feature_rows}
    eligible_windows, low_quality_windows = filter_windows_for_validation(windows, config)
    _base_matrix, feature_keys, _metadata_rows = prepare_training_rows(eligible_windows, feature_index)

    baseline = _bootstrap_cluster_stability(
        windows=eligible_windows,
        feature_index=feature_index,
        feature_keys=feature_keys,
        config=config,
        iterations=BOOTSTRAP_ITERATIONS,
        seed=BOOTSTRAP_SEED,
    )

    per_feature = []
    for feature_name in feature_keys:
        reduced_keys = [key for key in feature_keys if key != feature_name]
        without_feature = _bootstrap_cluster_stability(
            windows=eligible_windows,
            feature_index=feature_index,
            feature_keys=reduced_keys,
            config=config,
            iterations=BOOTSTRAP_ITERATIONS,
            seed=BOOTSTRAP_SEED,
        )
        delta = round(without_feature["mean_cluster_stability"] - baseline["mean_cluster_stability"], 6)
        per_feature.append(
            {
                "feature": feature_name,
                "stability_with_feature": baseline["mean_cluster_stability"],
                "stability_without_feature": without_feature["mean_cluster_stability"],
                "stability_delta_without_feature": delta,
                "classification": _classify_delta(delta),
            }
        )

    per_feature.sort(key=lambda item: item["stability_delta_without_feature"])

    report = {
        "schema_version": "feature_stability_analysis_v0_1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "bootstrap_iterations": BOOTSTRAP_ITERATIONS,
        "eligible_window_count": len(eligible_windows),
        "low_quality_window_count": len(low_quality_windows),
        "baseline_mean_cluster_stability": baseline["mean_cluster_stability"],
        "baseline_stability_samples": baseline["samples"],
        "active_feature_count": len(feature_keys),
        "active_features": feature_keys,
        "per_feature": per_feature,
    }
    return report


def export_feature_stability_analysis(report: dict[str, Any]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    REPORT_PATH.write_text(_render_report(report), encoding="utf-8")


def main() -> int:
    report = build_feature_stability_analysis()
    export_feature_stability_analysis(report)
    print(
        "Feature stability analysis ready: "
        f"features={report['active_feature_count']}, baseline_stability={report['baseline_mean_cluster_stability']}"
    )
    return 0


def _bootstrap_cluster_stability(
    *,
    windows: list[dict[str, Any]],
    feature_index: dict[str, dict[str, Any]],
    feature_keys: list[str],
    config: Any,
    iterations: int,
    seed: int,
) -> dict[str, Any]:
    if not windows:
        return {"mean_cluster_stability": 0.0, "samples": []}
    rng = Random(seed)
    samples: list[float] = []
    for _ in range(iterations):
        sampled_windows = [windows[rng.randrange(len(windows))] for _ in range(len(windows))]
        matrix, _used_keys, metadata_rows = prepare_training_rows(sampled_windows, feature_index, feature_keys=feature_keys)
        cluster_output = cluster_feature_matrix(matrix, metadata_rows, config)
        samples.append(_cluster_stability(cluster_output.assignments))
    return {
        "mean_cluster_stability": round(fmean(samples), 6) if samples else 0.0,
        "samples": [round(value, 6) for value in samples],
    }


def _cluster_stability(assignments: list[dict[str, Any]]) -> float:
    cluster_members: dict[int, list[str]] = {}
    for assignment in assignments:
        cluster_id = int(assignment["cluster_id"])
        if cluster_id == -1:
            continue
        cluster_members.setdefault(cluster_id, []).append(assignment.get("scenario_tag"))
    weighted_purity_numerator = 0.0
    weighted_purity_denominator = 0
    for tags in cluster_members.values():
        filtered_tags = [tag for tag in tags if tag is not None]
        if not filtered_tags:
            continue
        size = len(filtered_tags)
        dominant = max(filtered_tags.count(tag) for tag in set(filtered_tags))
        weighted_purity_numerator += dominant
        weighted_purity_denominator += size
    if weighted_purity_denominator == 0:
        return 0.0
    return round(weighted_purity_numerator / weighted_purity_denominator, 6)


def _classify_delta(delta: float) -> str:
    if delta <= -SIGNIFICANCE_DELTA:
        return "stabilizer"
    if delta >= SIGNIFICANCE_DELTA:
        return "destabilizer_or_redundant"
    return "neutral"


def _render_report(report: dict[str, Any]) -> str:
    lines = [
        "# Feature Stability Analysis Report",
        "",
        f"- bootstrap_iterations: {report['bootstrap_iterations']}",
        f"- eligible_window_count: {report['eligible_window_count']}",
        f"- baseline_mean_cluster_stability: {report['baseline_mean_cluster_stability']}",
        "",
        "## Per-Feature Impact",
        "| feature | with_feature | without_feature | delta_without | classification |",
        "|---|---:|---:|---:|---|",
    ]
    for row in report["per_feature"]:
        lines.append(
            f"| {row['feature']} | {row['stability_with_feature']} | {row['stability_without_feature']} | {row['stability_delta_without_feature']} | {row['classification']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "- `stabilizer`: removing the feature lowers mean cluster stability materially.",
            "- `destabilizer_or_redundant`: removing the feature improves stability materially.",
            "- `neutral`: removing the feature does not move stability enough to matter yet.",
        ]
    )
    return "\n".join(lines)
