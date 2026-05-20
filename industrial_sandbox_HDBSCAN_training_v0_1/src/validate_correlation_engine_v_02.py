"""Non-circular validation for the correlation engine using holdout scenarios."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any
import json

from src.build_hdbscan_temporal_feature_view_v_02 import build_hdbscan_temporal_feature_view_v_02
from src.build_temporal_windows import build_temporal_windows
from src.scenario_engine import scenario_catalog
from src.window_scaling_v_02 import (
    build_training_profiles_v_02,
    build_validation_profiles_v_02,
    build_windowing_policy_v_02,
    export_window_scaling_summary_v_02,
)
from src.train_hdbscan_temporal_v_02 import (
    build_events_from_profiles,
    cluster_feature_matrix,
    filter_windows_for_validation,
    load_training_config,
    prepare_training_rows,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "reports" / "correlation_engine_validation_report_v_02.md"
SUMMARY_PATH = PROJECT_ROOT / "artifacts" / "metrics" / "correlation_engine_validation_summary_v_02.json"
POST_FILTER_REQUESTED_THRESHOLD = 0.30
POST_FILTER_FALLBACK_QUANTILE = 0.70
POST_FILTER_AGGREGATION = "percentile_25"


SERVICE_NAME_ALIASES = {
    "payments-api": "payments",
    "redis": "redis",
    "checkout-api": "checkout",
    "orders-api": "orders",
}


def validate_correlation_engine() -> dict[str, Any]:
    profiles = build_validation_profiles_v_02()
    export_window_scaling_summary_v_02(build_training_profiles_v_02(), profiles)
    config = load_training_config()
    validation_events = build_events_from_profiles(profiles, start_anchor=datetime(2026, 2, 1, tzinfo=timezone.utc))
    windows = build_temporal_windows(validation_events, policy=build_windowing_policy_v_02())
    feature_rows = build_hdbscan_temporal_feature_view_v_02(windows)
    feature_index = {row["window_id"]: row for row in feature_rows}
    eligible_windows, low_quality_windows = filter_windows_for_validation(windows, config)
    matrix, feature_keys, metadata_rows = prepare_training_rows(eligible_windows, feature_index)
    cluster_output = cluster_feature_matrix(matrix, metadata_rows, config)

    filtered_assignments, post_filter = apply_iforest_post_filter(
        cluster_output.assignments,
        feature_index,
        requested_threshold=POST_FILTER_REQUESTED_THRESHOLD,
        fallback_quantile=POST_FILTER_FALLBACK_QUANTILE,
        aggregation=POST_FILTER_AGGREGATION,
    )

    assignments_by_window = {entry["window_id"]: entry for entry in filtered_assignments}
    catalog = scenario_catalog()
    positive_windows = 0
    negative_windows = 0
    detected_positive_windows = 0
    false_positive_windows = 0
    rejected_negative_windows = 0
    order_checks = 0
    order_hits = 0
    temporal_checks = 0
    temporal_hits = 0

    for window in eligible_windows:
        scenario_name = window.get("scenario_tag")
        definition = catalog.get(scenario_name) if scenario_name else None
        assignment = assignments_by_window.get(window["window_id"])
        predicted_propagation = assignment is not None and not assignment["noise"]
        is_positive = bool(definition and definition.expected_propagation)
        if is_positive:
            positive_windows += 1
            if predicted_propagation:
                detected_positive_windows += 1
            if definition and definition.propagation_chain:
                order_checks += 1
                if _order_matches(feature_index.get(window["window_id"]), tuple(definition.propagation_chain)):
                    order_hits += 1
            lag_values = [
                window.get("features", {}).get("payments-api__latency_p95"),
                window.get("features", {}).get("redis__redis_latency"),
                window.get("features", {}).get("checkout-api__latency_p95"),
            ]
            temporal_checks += 1
            if all(value is not None and value >= 0.0 for value in lag_values[:2]):
                temporal_hits += 1
        else:
            negative_windows += 1
            if predicted_propagation:
                false_positive_windows += 1
            else:
                rejected_negative_windows += 1

    cluster_members: dict[int, list[str]] = defaultdict(list)
    for assignment in filtered_assignments:
        if assignment["cluster_id"] != -1:
            cluster_members[int(assignment["cluster_id"])] .append(assignment["scenario_tag"])

    weighted_purity_numerator = 0.0
    weighted_purity_denominator = 0
    for tags in cluster_members.values():
        if not tags:
            continue
        size = len(tags)
        dominant = max(tags.count(tag) for tag in set(tags))
        weighted_purity_numerator += dominant
        weighted_purity_denominator += size
    cluster_stability = round(weighted_purity_numerator / weighted_purity_denominator, 6) if weighted_purity_denominator else 0.0

    raw_cluster_ids = {int(entry["cluster_id"]) for entry in cluster_output.assignments if entry["cluster_id"] != -1}
    filtered_cluster_ids = {int(entry["cluster_id"]) for entry in filtered_assignments if entry["cluster_id"] != -1}

    summary = {
        "schema_version": "correlation_engine_validation_summary_v_02",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "backend_executed": cluster_output.backend_executed,
        "eligible_window_count": len(eligible_windows),
        "propagation_detection_rate": _safe_rate(detected_positive_windows, positive_windows),
        "false_propagation_rate": _safe_rate(false_positive_windows, negative_windows),
        "precision": round(1.0 - _safe_rate(false_positive_windows, negative_windows), 6),
        "noise_rejection_rate": _safe_rate(rejected_negative_windows, negative_windows),
        "propagation_order_accuracy": _safe_rate(order_hits, order_checks),
        "temporal_consistency": _safe_rate(temporal_hits, temporal_checks),
        "cluster_stability": cluster_stability,
        "cluster_count": len(filtered_cluster_ids),
        "raw_cluster_count": len(raw_cluster_ids),
        "noise_window_count": sum(1 for entry in filtered_assignments if entry["noise"]),
        "raw_noise_window_count": sum(1 for entry in cluster_output.assignments if entry["noise"]),
        "validation_scenarios": sorted({profile["scenario_name"] for profile in profiles}),
        "feature_count": len(feature_keys),
        "validation_min_window_quality_score": config.validation_min_window_quality_score,
        "low_quality_window_count": len(low_quality_windows),
        "post_filter_requested_threshold": POST_FILTER_REQUESTED_THRESHOLD,
        "post_filter_aggregation": POST_FILTER_AGGREGATION,
        "post_filter_effective_threshold": post_filter["effective_threshold"],
        "post_filter_policy": post_filter["policy"],
        "post_filter_fallback_quantile": POST_FILTER_FALLBACK_QUANTILE,
        "post_filter_rejected_cluster_count": len(raw_cluster_ids) - len(filtered_cluster_ids),
        "post_filter_kept_cluster_ids": sorted(filtered_cluster_ids),
        "post_filter_cluster_iforest_means": post_filter["cluster_iforest_means"],
        "post_filter_rejected_window_count": post_filter["rejected_window_count"],
    }
    return summary


def export_validation_artifacts(summary: dict[str, Any]) -> None:
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SUMMARY_PATH.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
    REPORT_PATH.write_text(_render_report(summary), encoding="utf-8")


def main() -> int:
    summary = validate_correlation_engine()
    export_validation_artifacts(summary)
    print(
        "Correlation engine validation v_02 ready: "
        f"detection={summary['propagation_detection_rate']}, "
        f"false_positive={summary['false_propagation_rate']}, "
        f"order_accuracy={summary['propagation_order_accuracy']}"
    )
    return 0


def apply_iforest_post_filter(
    assignments: list[dict[str, Any]],
    feature_index: dict[str, dict[str, Any]],
    *,
    requested_threshold: float,
    fallback_quantile: float,
    aggregation: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cluster_scores: dict[int, list[float]] = defaultdict(list)
    for assignment in assignments:
        cluster_id = int(assignment["cluster_id"])
        if cluster_id == -1:
            continue
        feature_row = feature_index.get(assignment["window_id"], {})
        cluster_scores[cluster_id].append(float(feature_row.get("iforest_score_mean", 0.0)))

    cluster_confidence = {
        cluster_id: _aggregate_cluster_score(values, aggregation)
        for cluster_id, values in cluster_scores.items()
        if values
    }
    effective_threshold = requested_threshold
    policy = "fixed_threshold"
    if cluster_confidence and max(cluster_confidence.values()) < requested_threshold:
        effective_threshold = _percentile(sorted(cluster_confidence.values()), fallback_quantile)
        policy = "adaptive_quantile_fallback"

    kept_cluster_ids = {cluster_id for cluster_id, score in cluster_confidence.items() if score >= effective_threshold}
    filtered_assignments: list[dict[str, Any]] = []
    rejected_window_count = 0
    for assignment in assignments:
        raw_cluster_id = int(assignment["cluster_id"])
        enriched = dict(assignment)
        enriched["raw_cluster_id"] = raw_cluster_id
        enriched["cluster_iforest_score_mean"] = round(mean(cluster_scores.get(raw_cluster_id, [0.0])), 6)
        enriched["cluster_iforest_confidence"] = cluster_confidence.get(raw_cluster_id, 0.0)
        enriched["post_filter_threshold"] = round(effective_threshold, 6)
        enriched["post_filter_passed"] = raw_cluster_id == -1 or raw_cluster_id in kept_cluster_ids
        if raw_cluster_id != -1 and raw_cluster_id not in kept_cluster_ids:
            enriched["cluster_id"] = -1
            enriched["noise"] = True
            enriched["cluster_strength"] = 0.0
            rejected_window_count += 1
        filtered_assignments.append(enriched)

    return filtered_assignments, {
        "effective_threshold": round(effective_threshold, 6),
        "policy": policy,
        "cluster_iforest_means": {str(key): round(mean(values), 6) for key, values in sorted(cluster_scores.items())},
        "cluster_iforest_confidence": {str(key): value for key, value in sorted(cluster_confidence.items())},
        "aggregation": aggregation,
        "rejected_window_count": rejected_window_count,
    }


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    clipped = min(max(quantile, 0.0), 1.0)
    index = clipped * (len(values) - 1)
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    fraction = index - lower
    return round(values[lower] + (values[upper] - values[lower]) * fraction, 6)


def _aggregate_cluster_score(values: list[float], aggregation: str) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    if aggregation == "mean":
        return round(mean(ordered), 6)
    if aggregation == "median":
        return _percentile(ordered, 0.50)
    if aggregation == "percentile_25":
        return _percentile(ordered, 0.25)
    raise ValueError(f"unsupported post-filter aggregation: {aggregation}")


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _order_matches(feature_row: dict[str, Any] | None, chain: tuple[str, ...]) -> bool:
    if feature_row is None:
        return False
    normalized_chain = [SERVICE_NAME_ALIASES.get(service) for service in chain]
    if any(service is None for service in normalized_chain):
        return False
    origin = feature_row.get("detected_origin_service")
    if origin != normalized_chain[0]:
        return False
    distances: list[float] = []
    for service in normalized_chain:
        value = feature_row.get(f"topological_distance_{service}")
        if value is None:
            return False
        distances.append(float(value))
    if not distances or distances[0] != 0.0:
        return False
    return all(left <= right for left, right in zip(distances, distances[1:]))


def _render_report(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Correlation Engine Validation Report",
            "",
            f"- backend: {summary['backend_executed']}",
            f"- eligible_window_count: {summary['eligible_window_count']}",
            f"- propagation_detection_rate: {summary['propagation_detection_rate']}",
            f"- false_propagation_rate: {summary['false_propagation_rate']}",
            f"- precision: {summary['precision']}",
            f"- noise_rejection_rate: {summary['noise_rejection_rate']}",
            f"- propagation_order_accuracy: {summary['propagation_order_accuracy']}",
            f"- temporal_consistency: {summary['temporal_consistency']}",
            f"- cluster_stability: {summary['cluster_stability']}",
            f"- raw_cluster_count: {summary['raw_cluster_count']}",
            f"- cluster_count: {summary['cluster_count']}",
            f"- raw_noise_window_count: {summary['raw_noise_window_count']}",
            f"- noise_window_count: {summary['noise_window_count']}",
            f"- post_filter_requested_threshold: {summary['post_filter_requested_threshold']}",
            f"- post_filter_aggregation: {summary['post_filter_aggregation']}",
            f"- post_filter_effective_threshold: {summary['post_filter_effective_threshold']}",
            f"- post_filter_policy: {summary['post_filter_policy']}",
            f"- post_filter_rejected_cluster_count: {summary['post_filter_rejected_cluster_count']}",
            f"- post_filter_rejected_window_count: {summary['post_filter_rejected_window_count']}",
        ]
    )
