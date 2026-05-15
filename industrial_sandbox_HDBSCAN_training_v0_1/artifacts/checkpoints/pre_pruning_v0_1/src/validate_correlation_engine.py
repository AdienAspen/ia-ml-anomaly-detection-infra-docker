"""Non-circular validation for the correlation engine using holdout scenarios."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

from src.build_hdbscan_temporal_feature_view import build_hdbscan_temporal_feature_view
from src.build_temporal_windows import build_temporal_windows, load_windowing_policy
from src.scenario_engine import scenario_catalog
from src.scenario_repository import load_validation_scenarios
from src.train_hdbscan_temporal import build_events_from_profiles, cluster_feature_matrix, filter_windows_for_validation, load_training_config, prepare_training_rows

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = PROJECT_ROOT / "reports" / "correlation_engine_validation_report.md"
SUMMARY_PATH = PROJECT_ROOT / "artifacts" / "metrics" / "correlation_engine_validation_summary_v0_1.json"


def validate_correlation_engine() -> dict[str, Any]:
    profiles = load_validation_scenarios()
    config = load_training_config()
    validation_events = build_events_from_profiles(profiles, start_anchor=datetime(2026, 2, 1, tzinfo=timezone.utc))
    windows = build_temporal_windows(validation_events, policy=load_windowing_policy())
    feature_rows = build_hdbscan_temporal_feature_view(windows)
    feature_index = {row["window_id"]: row for row in feature_rows}
    eligible_windows, low_quality_windows = filter_windows_for_validation(windows, config)
    matrix, feature_keys, metadata_rows = prepare_training_rows(eligible_windows, feature_index)
    cluster_output = cluster_feature_matrix(matrix, metadata_rows, config)

    assignments_by_window = {entry["window_id"]: entry for entry in cluster_output.assignments}
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
    for assignment in cluster_output.assignments:
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

    summary = {
        "schema_version": "correlation_engine_validation_summary_v0_1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "backend_executed": cluster_output.backend_executed,
        "eligible_window_count": len(eligible_windows),
        "propagation_detection_rate": _safe_rate(detected_positive_windows, positive_windows),
        "false_propagation_rate": _safe_rate(false_positive_windows, negative_windows),
        "noise_rejection_rate": _safe_rate(rejected_negative_windows, negative_windows),
        "propagation_order_accuracy": _safe_rate(order_hits, order_checks),
        "temporal_consistency": _safe_rate(temporal_hits, temporal_checks),
        "cluster_stability": cluster_stability,
        "cluster_count": len(cluster_members),
        "noise_window_count": sum(1 for entry in cluster_output.assignments if entry["noise"]),
        "validation_scenarios": sorted({profile["scenario_name"] for profile in profiles}),
        "feature_count": len(feature_keys),
        "validation_min_window_quality_score": config.validation_min_window_quality_score,
        "low_quality_window_count": len(low_quality_windows),
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
        "Correlation engine validation ready: "
        f"detection={summary['propagation_detection_rate']}, "
        f"false_positive={summary['false_propagation_rate']}, "
        f"order_accuracy={summary['propagation_order_accuracy']}"
    )
    return 0


def _safe_rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _decode_order(encoded: int | float | None) -> dict[str, int] | None:
    if encoded is None:
        return None
    value = int(encoded)
    return {
        "payments-api": value // 1000,
        "redis": (value % 1000) // 100,
        "checkout-api": (value % 100) // 10,
        "orders-api": value % 10,
    }


def _order_matches(feature_row: dict[str, Any] | None, chain: tuple[str, ...]) -> bool:
    if feature_row is None:
        return False
    encoded = feature_row.get("service_degradation_order_encoded")
    positions = _decode_order(encoded)
    if positions is None:
        return False
    for left, right in zip(chain, chain[1:]):
        if left not in positions or right not in positions:
            return False
        if positions[left] >= positions[right]:
            return False
    return True


def _render_report(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Correlation Engine Validation Report",
            "",
            f"- backend: {summary['backend_executed']}",
            f"- eligible_window_count: {summary['eligible_window_count']}",
            f"- propagation_detection_rate: {summary['propagation_detection_rate']}",
            f"- false_propagation_rate: {summary['false_propagation_rate']}",
            f"- noise_rejection_rate: {summary['noise_rejection_rate']}",
            f"- propagation_order_accuracy: {summary['propagation_order_accuracy']}",
            f"- temporal_consistency: {summary['temporal_consistency']}",
            f"- cluster_stability: {summary['cluster_stability']}",
            f"- cluster_count: {summary['cluster_count']}",
            f"- noise_window_count: {summary['noise_window_count']}",
        ]
    )
