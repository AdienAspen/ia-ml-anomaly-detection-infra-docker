"""Score or export defensive propagation signatures from clustered windows."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import json
import pickle

from src.train_hdbscan_temporal import ensure_training_inputs

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = PROJECT_ROOT / "artifacts" / "models" / "hdbscan_temporal" / "hdbscan_temporal_model.pkl"
WINDOWS_PATH = PROJECT_ROOT / "data" / "processed" / "temporal_windows_v0_1.json"
FEATURE_VIEW_PATH = PROJECT_ROOT / "data" / "processed" / "hdbscan_temporal_feature_view_v0_1.json"
OUTPUT_PATH = PROJECT_ROOT / "artifacts" / "propagation_signatures_v0_1.json"

SERVICE_ORDER = ("payments-api", "redis", "checkout-api", "orders-api")
LAG_CI_METHOD = "observed_percentiles_p10_p50_p90"
LAG_CI_PRECISION_MIN_WINDOWS = 30

METRIC_SELECTION = {
    "payments-api": ("latency_p95_payments", "iforest_score_payments"),
    "orders-api": ("error_rate_orders", "latency_p95_orders"),
    "checkout-api": ("error_rate_checkout", "latency_p95_checkout"),
    "redis": ("redis_queue_depth", "redis_latency"),
}


def load_artifacts() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    model_payload = pickle.loads(MODEL_PATH.read_bytes())
    windows = json.loads(WINDOWS_PATH.read_text(encoding="utf-8"))
    feature_rows = json.loads(FEATURE_VIEW_PATH.read_text(encoding="utf-8"))
    assignment_window_ids = {entry.get("window_id") for entry in model_payload.get("assignments", [])}
    current_window_ids = {row.get("window_id") for row in windows}
    if not assignment_window_ids.issubset(current_window_ids):
        windows, feature_rows = ensure_training_inputs()
    return model_payload, windows, feature_rows


def build_propagation_signatures() -> list[dict[str, Any]]:
    model_payload, windows, feature_rows = load_artifacts()
    assignments = model_payload.get("assignments", [])
    feature_index = {row["window_id"]: row for row in feature_rows}
    window_index = {row["window_id"]: row for row in windows}
    resolved_features = {
        window_id: feature_index.get(window_id) or _feature_row_from_window(window_row)
        for window_id, window_row in window_index.items()
    }
    grouped_by_cluster: dict[int, list[dict[str, Any]]] = {}
    for assignment in assignments:
        grouped_by_cluster.setdefault(int(assignment["cluster_id"]), []).append(assignment)

    signatures: list[dict[str, Any]] = []
    for assignment in assignments:
        window_id = assignment["window_id"]
        cluster_id = int(assignment["cluster_id"])
        cluster_assignments = grouped_by_cluster.get(cluster_id, [assignment])
        feature_row = resolved_features[window_id]
        window_row = window_index[window_id]
        signatures.append(
            {
                "schema_version": "propagation_signature_v0_1",
                "signature_id": f"prop_sig_{window_id}",
                "cluster_id": cluster_id,
                "window_id": window_id,
                "detected": cluster_id != -1,
                "noise": bool(assignment["noise"]),
                "services_chain_observed": _services_chain_observed(feature_row),
                "lag_pattern_seconds_ci": _lag_pattern_ci(cluster_assignments, resolved_features),
                "lag_ci_metadata": _lag_ci_metadata(cluster_assignments),
                "affected_metrics": _affected_metrics(feature_row),
                "metric_ranges_observed": _metric_ranges_observed(cluster_assignments, resolved_features),
                "window_data_quality_score": round(float(window_row["window_data_quality_score"]), 6),
                "propagation_order_confidence": round(float(assignment.get("cluster_strength", 0.0)), 6),
                "observation_period": {
                    "start": window_row["window_start"],
                    "end": window_row["window_end"],
                },
                "evidence": {
                    "features_used": list(model_payload.get("feature_keys", [])),
                    "source_windows": [entry["window_id"] for entry in cluster_assignments],
                    "backend_executed": model_payload.get("backend_executed"),
                    "scenario_tag": assignment.get("scenario_tag"),
                },
            }
        )
    return signatures


def export_propagation_signatures(signatures: list[dict[str, Any]]) -> Path:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(signatures, indent=2), encoding="utf-8")
    return OUTPUT_PATH


def main() -> int:
    signatures = build_propagation_signatures()
    export_propagation_signatures(signatures)
    print(f"Propagation signature scoring ready: {len(signatures)} signatures -> {OUTPUT_PATH}")
    return 0


def _feature_row_from_window(window_row: dict[str, Any]) -> dict[str, Any]:
    features = window_row.get("features", {})
    payments_latency = _as_float(features.get("payments-api__latency_p95"))
    orders_latency = _as_float(features.get("orders-api__latency_p95"))
    checkout_latency = _as_float(features.get("checkout-api__latency_p95"))
    payments_error = _as_float(features.get("payments-api__error_rate"))
    orders_error = _as_float(features.get("orders-api__error_rate"))
    checkout_error = _as_float(features.get("checkout-api__error_rate"))
    redis_latency = _as_float(features.get("redis__redis_latency"))
    redis_queue_depth = _as_float(features.get("redis__redis_queue_depth"))
    signal_scores = {
        "payments-api": (payments_latency / 220.0) + (payments_error / 0.02),
        "redis": (redis_latency / 10.0) + (redis_queue_depth / 40.0),
        "checkout-api": (checkout_latency / 220.0) + (checkout_error / 0.02),
        "orders-api": (orders_latency / 220.0) + (orders_error / 0.02),
    }
    ordered_services = [service for service, _score in sorted(signal_scores.items(), key=lambda item: item[1], reverse=True)]
    positions = {service: index for index, service in enumerate(ordered_services)}
    encoded = positions["payments-api"] * 1000 + positions["redis"] * 100 + positions["checkout-api"] * 10 + positions["orders-api"]
    anomaly_density = sum(1 for score in signal_scores.values() if score >= 1.0) / max(len(signal_scores), 1)
    return {
        "window_id": window_row.get("window_id"),
        "latency_p95_payments": payments_latency,
        "latency_p95_orders": orders_latency,
        "latency_p95_checkout": checkout_latency,
        "error_rate_orders": orders_error,
        "error_rate_checkout": checkout_error,
        "redis_queue_depth": redis_queue_depth,
        "redis_latency": redis_latency,
        "iforest_score_payments": max((payments_latency / 400.0) + payments_error, 0.0),
        "iforest_score_orders": max((orders_latency / 400.0) + orders_error, 0.0),
        "iforest_score_checkout": max((checkout_latency / 400.0) + checkout_error, 0.0),
        "window_anomaly_density": round(anomaly_density, 6),
        "lag_payments_to_redis": None,
        "lag_redis_to_checkout": None,
        "service_degradation_order_encoded": encoded,
        "window_data_quality_score": window_row.get("window_data_quality_score"),
        "scenario_tag": window_row.get("scenario_tag"),
    }


def _decode_order(encoded: int | float | None) -> list[str]:
    if encoded is None:
        return []
    value = int(encoded)
    positions = {
        "payments-api": value // 1000,
        "redis": (value % 1000) // 100,
        "checkout-api": (value % 100) // 10,
        "orders-api": value % 10,
    }
    return [service_name for service_name, _pos in sorted(positions.items(), key=lambda item: item[1])]


def _services_chain_observed(feature_row: dict[str, Any]) -> list[str]:
    ordered = _decode_order(feature_row.get("service_degradation_order_encoded"))
    filtered: list[str] = []
    for service_name in ordered:
        metrics = METRIC_SELECTION.get(service_name, ())
        if any(feature_row.get(metric_name) not in (None, 0, 0.0) for metric_name in metrics):
            filtered.append(service_name)
    return filtered or ordered or list(SERVICE_ORDER)


def _lag_pattern_ci(cluster_assignments: list[dict[str, Any]], resolved_features: dict[str, dict[str, Any]]) -> dict[str, Any]:
    lag_map = {
        "payments-api_to_redis": [resolved_features[entry["window_id"]].get("lag_payments_to_redis") for entry in cluster_assignments],
        "redis_to_checkout-api": [resolved_features[entry["window_id"]].get("lag_redis_to_checkout") for entry in cluster_assignments],
    }
    result: dict[str, Any] = {}
    for key, values in lag_map.items():
        numeric = sorted(float(value) for value in values if value is not None)
        if not numeric:
            result[key] = {"p10": None, "p50": None, "p90": None}
            continue
        result[key] = {
            "p10": _percentile(numeric, 0.10),
            "p50": _percentile(numeric, 0.50),
            "p90": _percentile(numeric, 0.90),
        }
    return result




def _lag_ci_metadata(cluster_assignments: list[dict[str, Any]]) -> dict[str, Any]:
    sample_window_count = len(cluster_assignments)
    precise = sample_window_count >= LAG_CI_PRECISION_MIN_WINDOWS
    return {
        "lag_ci_method": LAG_CI_METHOD,
        "sample_window_count": sample_window_count,
        "minimum_windows_for_precision": LAG_CI_PRECISION_MIN_WINDOWS,
        "precision": "precise" if precise else "imprecise",
    }

def _affected_metrics(feature_row: dict[str, Any]) -> dict[str, list[str]]:
    affected: dict[str, list[str]] = {}
    thresholds = {
        "iforest_score_payments": 0.45,
        "error_rate_orders": 0.02,
        "error_rate_checkout": 0.02,
        "redis_queue_depth": 40.0,
        "redis_latency": 10.0,
        "latency_p95_payments": 220.0,
        "latency_p95_orders": 220.0,
        "latency_p95_checkout": 220.0,
    }
    for service_name, metric_names in METRIC_SELECTION.items():
        selected = []
        for metric_name in metric_names:
            value = feature_row.get(metric_name)
            threshold = thresholds.get(metric_name, 0.0)
            if value is not None and float(value) >= threshold:
                selected.append(_public_metric_name(metric_name))
        if selected:
            affected[service_name] = selected
    return affected


def _metric_ranges_observed(cluster_assignments: list[dict[str, Any]], resolved_features: dict[str, dict[str, Any]]) -> dict[str, Any]:
    keys = [
        "latency_p95_payments",
        "latency_p95_orders",
        "latency_p95_checkout",
        "error_rate_orders",
        "error_rate_checkout",
        "redis_queue_depth",
        "redis_latency",
        "iforest_score_payments",
    ]
    ranges: dict[str, Any] = {}
    for key in keys:
        values = [resolved_features[entry["window_id"]].get(key) for entry in cluster_assignments]
        numeric = [float(value) for value in values if value is not None]
        if not numeric:
            continue
        ranges[key] = {"min": round(min(numeric), 6), "max": round(max(numeric), 6)}
    return ranges


def _percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(values[0], 6)
    index = ratio * (len(values) - 1)
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    weight = index - lower
    interpolated = values[lower] * (1.0 - weight) + values[upper] * weight
    return round(interpolated, 6)


def _public_metric_name(metric_name: str) -> str:
    return metric_name.replace("_payments", "").replace("_orders", "").replace("_checkout", "")


def _as_float(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)
