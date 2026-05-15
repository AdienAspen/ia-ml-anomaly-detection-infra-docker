"""Calculate validated temporal correlation features from temporal windows."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import json

from src.build_iforest_feature_view import _compute_iforest_proxy_score
from src.build_temporal_windows import build_temporal_windows
from src.scenario_engine import BASELINE_METRICS, build_scenario_events

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "hdbscan_temporal_feature_view_v0_1.json"
ORDER_SERVICES = ("payments-api", "redis", "checkout-api", "orders-api")
API_SERVICES = ("payments-api", "orders-api", "checkout-api")


def build_hdbscan_feature_rows(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for window in windows:
        row = _build_feature_row(window)
        errors = validate_feature_row(row)
        if errors:
            raise ValueError(f"feature sanity failed for {window['window_id']}: {errors}")
        rows.append(row)
    return rows


def export_hdbscan_feature_rows(rows: list[dict[str, Any]], output_path: Path = OUTPUT_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2)
    return output_path


def main() -> int:
    sample_events = build_scenario_events("S4_INTERSERVICE_CHAIN", seed=42, steps=8)
    sample_windows = build_temporal_windows(sample_events)
    rows = build_hdbscan_feature_rows(sample_windows)
    export_hdbscan_feature_rows(rows)
    print(f"Feature calculator ready: {len(rows)} rows -> {OUTPUT_PATH}")
    return 0


def validate_feature_row(row: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    anomaly_density = row.get("window_anomaly_density")
    if anomaly_density is None or not 0.0 <= float(anomaly_density) <= 1.0:
        errors.append("window_anomaly_density must be between 0 and 1")
    quality = row.get("window_data_quality_score")
    if quality is None or not 0.0 <= float(quality) <= 1.0:
        errors.append("window_data_quality_score must be between 0 and 1")
    for lag_key in ("lag_payments_to_redis", "lag_redis_to_checkout"):
        lag = row.get(lag_key)
        if lag is not None and float(lag) < 0.0:
            errors.append(f"{lag_key} cannot be negative")
    return errors


def _build_feature_row(window: dict[str, Any]) -> dict[str, Any]:
    feature_values = window.get("features", {})
    feature_inputs = window.get("training_metadata", {}).get("feature_inputs", {})
    service_metric_series = feature_inputs.get("service_metric_series", {})
    redis_latency = _coalesce(feature_values.get("redis__redis_latency"), 0.0)
    redis_queue_depth = _coalesce(feature_values.get("redis__redis_queue_depth"), 0.0)

    iforest_scores = {}
    for service_name in API_SERVICES:
        latency = _coalesce(feature_values.get(f"{service_name}__latency_p95"), 0.0)
        error_rate = _coalesce(feature_values.get(f"{service_name}__error_rate"), 0.0)
        throughput = _coalesce(feature_values.get(f"{service_name}__throughput"), 0.0)
        iforest_scores[service_name] = _compute_iforest_proxy_score(
            latency_p95=latency,
            error_rate=error_rate,
            throughput=throughput,
            redis_latency=redis_latency,
            redis_queue_depth=redis_queue_depth,
        )

    anomaly_density = round(
        sum(1 for score in iforest_scores.values() if score >= 0.55) / max(len(iforest_scores), 1),
        6,
    )
    iforest_compact = _iforest_compact_stats(iforest_scores)
    activation_times = {
        service_name: _activation_time(service_name, service_metric_series)
        for service_name in ORDER_SERVICES
    }

    return {
        "schema_version": "hdbscan_temporal_feature_view_v0_2",
        "window_id": window["window_id"],
        "window_start": window.get("window_start"),
        "window_end": window.get("window_end"),
        "iforest_score_payments": iforest_scores["payments-api"],
        "iforest_score_orders": iforest_scores["orders-api"],
        "iforest_score_checkout": iforest_scores["checkout-api"],
        "iforest_score_max": iforest_compact["iforest_score_max"],
        "iforest_score_mean": iforest_compact["iforest_score_mean"],
        "iforest_score_spread": iforest_compact["iforest_score_spread"],
        "latency_p95_payments": _coalesce(feature_values.get("payments-api__latency_p95"), 0.0),
        "latency_p95_orders": _coalesce(feature_values.get("orders-api__latency_p95"), 0.0),
        "latency_p95_checkout": _coalesce(feature_values.get("checkout-api__latency_p95"), 0.0),
        "error_rate_payments": _coalesce(feature_values.get("payments-api__error_rate"), 0.0),
        "error_rate_orders": _coalesce(feature_values.get("orders-api__error_rate"), 0.0),
        "error_rate_checkout": _coalesce(feature_values.get("checkout-api__error_rate"), 0.0),
        "redis_queue_depth": redis_queue_depth,
        "redis_latency": redis_latency,
        "window_anomaly_density": anomaly_density,
        "lag_payments_to_redis": _lag_seconds(activation_times.get("payments-api"), activation_times.get("redis")),
        "lag_redis_to_checkout": _lag_seconds(activation_times.get("redis"), activation_times.get("checkout-api")),
        "service_degradation_order_encoded": _encode_order(activation_times),
        "window_data_quality_score": window.get("window_data_quality_score", 0.0),
        "scenario_tag": window.get("scenario_tag"),
        "chaos_suitability": window.get("chaos_suitability"),
        "feature_calculation_policy": {
            "feature_calculator_version": "v0_1",
            "lag_policy": "first_threshold_crossing",
            "late_event_policy_mode": window.get("training_metadata", {}).get("late_event_policy", {}).get("mode"),
        },
        "iforest_score_source": "proxy_from_temporal_window_features",
    }


def _iforest_compact_stats(iforest_scores: dict[str, float]) -> dict[str, float]:
    values = [float(value) for value in iforest_scores.values()]
    if not values:
        return {"iforest_score_max": 0.0, "iforest_score_mean": 0.0, "iforest_score_spread": 0.0}
    return {
        "iforest_score_max": round(max(values), 6),
        "iforest_score_mean": round(sum(values) / len(values), 6),
        "iforest_score_spread": round(max(values) - min(values), 6),
    }


def _activation_time(service_name: str, service_metric_series: dict[str, Any]) -> datetime | None:
    metrics = service_metric_series.get(service_name, {})
    if service_name == "redis":
        redis_latency_points = metrics.get("redis_latency", [])
        queue_points = metrics.get("redis_queue_depth", [])
        threshold_latency = BASELINE_METRICS["redis"]["redis_latency"] * 1.35
        threshold_queue = BASELINE_METRICS["redis"]["redis_queue_depth"] * 2.0
        return _first_crossing_timestamp(
            redis_latency_points,
            queue_points,
            latency_threshold=threshold_latency,
            queue_threshold=threshold_queue,
        )

    latency_points = metrics.get("latency_p95", [])
    error_points = metrics.get("error_rate", [])
    throughput_points = metrics.get("throughput", [])
    baseline = BASELINE_METRICS[service_name]
    return _first_crossing_timestamp(
        latency_points,
        error_points,
        throughput_points,
        latency_threshold=baseline["latency_p95"] * 1.20,
        error_threshold=baseline["error_rate"] * 1.60,
        throughput_threshold=baseline["throughput"] * 0.90,
    )


def _first_crossing_timestamp(*series_lists: list[dict[str, Any]], **thresholds: float) -> datetime | None:
    merged: dict[tuple[str, int], dict[str, Any]] = {}
    names = list(thresholds.keys())
    for index, points in enumerate(series_lists):
        metric_label = names[index]
        for point in points:
            key = (point["timestamp"], int(point["sequence_number"]))
            merged.setdefault(key, {})[metric_label] = point["metric_value"]
    for timestamp, sequence_number in sorted(merged):
        observed = merged[(timestamp, sequence_number)]
        if _crossed_threshold(observed, thresholds):
            return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return None


def _crossed_threshold(observed: dict[str, Any], thresholds: dict[str, float]) -> bool:
    for threshold_name, threshold_value in thresholds.items():
        value = observed.get(threshold_name)
        if value is None:
            continue
        if threshold_name == "throughput_threshold":
            if float(value) <= threshold_value:
                return True
        elif float(value) >= threshold_value:
            return True
    return False


def _lag_seconds(left: datetime | None, right: datetime | None) -> float | None:
    if left is None or right is None:
        return None
    lag = round((right - left).total_seconds(), 6)
    if lag < 0:
        return None
    return lag


def _encode_order(service_times: dict[str, datetime | None]) -> int:
    fallback = datetime.max.replace(tzinfo=None)
    sortable = []
    for service_name in ORDER_SERVICES:
        timestamp = service_times.get(service_name)
        sortable.append((timestamp.replace(tzinfo=None) if timestamp is not None else fallback, service_name))
    ordered = [service_name for _, service_name in sorted(sortable)]
    positions = {service_name: index for index, service_name in enumerate(ordered)}
    return (
        positions["payments-api"] * 1000
        + positions["redis"] * 100
        + positions["checkout-api"] * 10
        + positions["orders-api"]
    )


def _coalesce(value: Any, default: float) -> float:
    return default if value is None else float(value)
