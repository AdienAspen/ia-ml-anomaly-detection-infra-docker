"""Calculate v_02 temporal correlation features from temporal windows."""

from __future__ import annotations

from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any
import json
import math

from src.build_iforest_feature_view import _compute_iforest_proxy_score
from src.build_temporal_windows import build_temporal_windows
from src.scenario_engine import BASELINE_METRICS, build_scenario_events

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "hdbscan_temporal_feature_view_v_02.json"
TOPOLOGY_PATH = Path(__file__).resolve().parents[1] / "configs" / "topology_graph_v_02.json"
API_SERVICES = ("payments-api", "orders-api", "checkout-api")
TOPOLOGY_SERVICE_ORDER = ("payments", "redis", "checkout", "orders")
SERVICE_NAME_MAP = {
    "payments-api": "payments",
    "orders-api": "orders",
    "checkout-api": "checkout",
    "redis": "redis",
}
FEATURE_SERVICES = ("payments", "redis", "checkout", "orders")
DEGRADATION_ERROR_THRESHOLD = 0.1
EMA_ALPHA = 0.3
TRAFFIC_PRESSURE_WINDOW = 6


def load_topology(path: Path = TOPOLOGY_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    nodes = list(payload.get("nodes", []))
    edges = list(payload.get("edges", []))
    criticality = dict(payload.get("criticality", {}))

    adjacency: dict[str, list[tuple[str, int]]] = {node: [] for node in nodes}
    reverse_adjacency: dict[str, list[str]] = {node: [] for node in nodes}
    for edge in edges:
        source = str(edge["source"])
        target = str(edge["target"])
        weight = int(edge.get("weight", 1))
        adjacency.setdefault(source, []).append((target, weight))
        reverse_adjacency.setdefault(target, []).append(source)
        adjacency.setdefault(target, [])
        reverse_adjacency.setdefault(source, [])

    return {
        "schema_version": payload.get("schema_version", "topology_graph_v_02"),
        "nodes": nodes,
        "edges": edges,
        "criticality": criticality,
        "adjacency": adjacency,
        "reverse_adjacency": reverse_adjacency,
    }


def bfs_distance(topology: dict[str, Any], source: str | None, target: str) -> int | None:
    if source is None:
        return None
    if source == target:
        return 0

    adjacency = topology.get("adjacency", {})
    queue: deque[tuple[str, int]] = deque([(source, 0)])
    best: dict[str, int] = {source: 0}

    while queue:
        node, distance = queue.popleft()
        for neighbor, weight in adjacency.get(node, []):
            candidate = distance + int(weight)
            if candidate < best.get(neighbor, 10**9):
                best[neighbor] = candidate
                if neighbor == target:
                    continue
                queue.append((neighbor, candidate))

    return best.get(target)


def get_upstream(topology: dict[str, Any], target: str) -> list[str]:
    reverse_adjacency = topology.get("reverse_adjacency", {})
    queue: deque[str] = deque(reverse_adjacency.get(target, []))
    seen: set[str] = set()
    ordered: list[str] = []

    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        ordered.append(node)
        for upstream in reverse_adjacency.get(node, []):
            if upstream not in seen:
                queue.append(upstream)

    return ordered


def build_hdbscan_feature_rows_v_02(windows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    topology = load_topology()
    rows = [_build_feature_row(window, topology=topology) for window in windows]
    rows = _with_temporal_enrichment(rows)
    validated: list[dict[str, Any]] = []
    for row in rows:
        errors = validate_feature_row_v_02(row)
        if errors:
            raise ValueError(f"feature sanity failed for {row['window_id']}: {errors}")
        validated.append(row)
    return validated


def export_hdbscan_feature_rows_v_02(rows: list[dict[str, Any]], output_path: Path = OUTPUT_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2)
    return output_path


def main() -> int:
    sample_events = build_scenario_events("S4_INTERSERVICE_CHAIN", seed=42, steps=8)
    sample_windows = build_temporal_windows(sample_events)
    rows = build_hdbscan_feature_rows_v_02(sample_windows)
    export_hdbscan_feature_rows_v_02(rows)
    print(f"Feature calculator v_02 ready: {len(rows)} rows -> {OUTPUT_PATH}")
    return 0


def validate_feature_row_v_02(row: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    anomaly_density = row.get("window_anomaly_density")
    if anomaly_density is None or not 0.0 <= float(anomaly_density) <= 1.0:
        errors.append("window_anomaly_density must be between 0 and 1")

    cache_health_score = row.get("cache_health_score")
    if cache_health_score is None or not 0.0 <= float(cache_health_score) <= 1.0:
        errors.append("cache_health_score must be between 0 and 1")

    for service in FEATURE_SERVICES:
        criticality = row.get(f"service_criticality_{service}")
        if criticality is None or float(criticality) < 0.0:
            errors.append(f"service_criticality_{service} must be non-negative")
        topo_distance = row.get(f"topological_distance_{service}")
        if topo_distance is None or float(topo_distance) < 0.0:
            errors.append(f"topological_distance_{service} must be non-negative")

    return errors


def _build_feature_row(window: dict[str, Any], *, topology: dict[str, Any]) -> dict[str, Any]:
    feature_values = window.get("features", {})
    feature_inputs = window.get("training_metadata", {}).get("feature_inputs", {})
    service_metric_series = feature_inputs.get("service_metric_series", {})
    redis_latency = _coalesce(feature_values.get("redis__redis_latency"), 0.0)
    redis_queue_depth = _coalesce(feature_values.get("redis__redis_queue_depth"), 0.0)

    iforest_scores: dict[str, float] = {}
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
        SERVICE_NAME_MAP[service_name]: _activation_time(service_name, service_metric_series)
        for service_name in SERVICE_NAME_MAP
    }
    detected_origin = _detect_origin(activation_times)
    cache_health_score = _cache_health_score(redis_queue_depth, redis_latency)
    observed_stress = _observed_stress_by_service(feature_values, cache_health_score)

    row = {
        "schema_version": "hdbscan_temporal_feature_view_v_02",
        "window_id": window["window_id"],
        "window_start": window.get("window_start"),
        "window_end": window.get("window_end"),
        "latency_p95_payments": _coalesce(feature_values.get("payments-api__latency_p95"), 0.0),
        "latency_p95_orders": _coalesce(feature_values.get("orders-api__latency_p95"), 0.0),
        "latency_p95_checkout": _coalesce(feature_values.get("checkout-api__latency_p95"), 0.0),
        "error_rate_payments": _coalesce(feature_values.get("payments-api__error_rate"), 0.0),
        "error_rate_orders": _coalesce(feature_values.get("orders-api__error_rate"), 0.0),
        "error_rate_checkout": _coalesce(feature_values.get("checkout-api__error_rate"), 0.0),
        "redis_queue_depth": redis_queue_depth,
        "redis_latency": redis_latency,
        "window_anomaly_density": anomaly_density,
        "cache_health_score": cache_health_score,
        "scenario_tag": window.get("scenario_tag"),
        "chaos_suitability": window.get("chaos_suitability"),
        "detected_origin_service": detected_origin,
        "iforest_score_max": iforest_compact["iforest_score_max"],
        "iforest_score_mean": iforest_compact["iforest_score_mean"],
        "iforest_score_spread": iforest_compact["iforest_score_spread"],
        "iforest_score_source": "proxy_from_temporal_window_features",
        "feature_calculation_policy": {
            "feature_calculator_version": "v_02",
            "topology_schema_version": topology.get("schema_version", "topology_graph_v_02"),
            "topological_distance_policy": "weighted_bfs_from_first_threshold_crossing",
            "upstream_health_policy": "mean_observed_upstream_stress",
            "recovery_memory_policy": "steps_since_last_clean_window",
        },
    }

    for service_name in API_SERVICES:
        short_name = SERVICE_NAME_MAP[service_name]
        metrics = service_metric_series.get(service_name, {})
        error_series = metrics.get("error_rate", [])
        throughput_series = metrics.get("throughput", [])
        latency_value = _coalesce(feature_values.get(f"{service_name}__latency_p95"), 0.0)
        throughput_value = _coalesce(feature_values.get(f"{service_name}__throughput"), 0.0)

        row[f"degradation_intensity_{short_name}"] = _ema_series(error_series, alpha=EMA_ALPHA)
        row[f"propagation_velocity_{short_name}"] = _propagation_velocity(error_series)
        row[f"traffic_pressure_{short_name}"] = _traffic_pressure(throughput_series, TRAFFIC_PRESSURE_WINDOW)
        row[f"flow_efficiency_{short_name}"] = _flow_efficiency(throughput_value, latency_value)
        row[f"stress_rate_{short_name}"] = _stress_rate(throughput_series)

    for service in FEATURE_SERVICES:
        row[f"service_criticality_{service}"] = float(topology.get("criticality", {}).get(service, 0))
        distance = bfs_distance(topology, detected_origin, service)
        row[f"topological_distance_{service}"] = float(distance if distance is not None else 0.0)
        upstream_nodes = get_upstream(topology, service)
        row[f"upstream_health_{service}"] = _upstream_health(upstream_nodes, observed_stress)

    return row


def _with_temporal_enrichment(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row.get("scenario_tag") or "", []).append(dict(row))

    output: list[dict[str, Any]] = []
    for scenario_tag, scenario_rows in grouped.items():
        ordered = sorted(scenario_rows, key=_sort_key)
        previous_orders: float | None = None
        previous_checkout: float | None = None
        last_clean_index = -1
        for index, row in enumerate(ordered):
            current_orders = float(row.get("latency_p95_orders", 0.0))
            current_checkout = float(row.get("latency_p95_checkout", 0.0))
            row["delta_latency_orders"] = round(current_orders - previous_orders, 6) if previous_orders is not None else 0.0
            row["delta_latency_checkout"] = round(current_checkout - previous_checkout, 6) if previous_checkout is not None else 0.0

            if _is_clean_window(row):
                row["recovery_memory"] = 0.0
                last_clean_index = index
            else:
                row["recovery_memory"] = float(index - last_clean_index if last_clean_index >= 0 else index + 1)

            output.append(row)
            previous_orders = current_orders
            previous_checkout = current_checkout

    return sorted(output, key=_sort_key)


def _sort_key(row: dict[str, Any]) -> tuple[str, datetime]:
    scenario_tag = row.get("scenario_tag") or ""
    window_start = row.get("window_start")
    timestamp = datetime.fromisoformat(window_start) if window_start else datetime.min
    return scenario_tag, timestamp


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
        error_threshold=max(baseline["error_rate"] * 1.60, DEGRADATION_ERROR_THRESHOLD),
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


def _detect_origin(activation_times: dict[str, datetime | None]) -> str | None:
    active = [(timestamp, service_name) for service_name, timestamp in activation_times.items() if timestamp is not None]
    if not active:
        return None
    active.sort()
    return active[0][1]


def _ema_series(points: list[dict[str, Any]], *, alpha: float) -> float:
    values = [float(point["metric_value"]) for point in points]
    if not values:
        return 0.0
    ema = values[0]
    for value in values[1:]:
        ema = alpha * value + (1.0 - alpha) * ema
    return round(ema, 6)


def _traffic_pressure(points: list[dict[str, Any]], sample_size: int) -> float:
    values = [float(point["metric_value"]) for point in points[-sample_size:]]
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    std = math.sqrt(variance)
    if std == 0.0:
        return 0.0
    return round((values[-1] - mean) / std, 6)


def _flow_efficiency(throughput: float, latency: float) -> float:
    return round(float(throughput) / (float(latency) + 1.0), 6)


def _stress_rate(points: list[dict[str, Any]]) -> float:
    if len(points) < 2:
        return 0.0
    previous = points[-2]
    current = points[-1]
    dt = _seconds_between(previous["timestamp"], current["timestamp"])
    if dt <= 0.0:
        return 0.0
    return round((float(previous["metric_value"]) - float(current["metric_value"])) / dt, 6)


def _propagation_velocity(points: list[dict[str, Any]]) -> float:
    if len(points) < 4:
        return 0.0
    previous = points[-4]
    current = points[-1]
    dt = _seconds_between(previous["timestamp"], current["timestamp"])
    if dt <= 0.0:
        return 0.0
    return round((float(current["metric_value"]) - float(previous["metric_value"])) / dt, 6)


def _cache_health_score(redis_queue_depth: float, redis_latency: float) -> float:
    score = 1.0 / (1.0 + float(redis_queue_depth) + (float(redis_latency) / 100.0))
    return round(max(min(score, 1.0), 0.0), 6)


def _observed_stress_by_service(feature_values: dict[str, Any], cache_health_score: float) -> dict[str, float]:
    stress = {
        "payments": _coalesce(feature_values.get("payments-api__error_rate"), 0.0),
        "orders": _coalesce(feature_values.get("orders-api__error_rate"), 0.0),
        "checkout": _coalesce(feature_values.get("checkout-api__error_rate"), 0.0),
        "redis": round(1.0 - cache_health_score, 6),
    }
    return stress


def _upstream_health(upstream_nodes: list[str], observed_stress: dict[str, float]) -> float:
    if not upstream_nodes:
        return 0.0
    values = [float(observed_stress.get(node, 0.0)) for node in upstream_nodes]
    return round(sum(values) / len(values), 6)


def _is_clean_window(row: dict[str, Any]) -> bool:
    return not any(
        float(row.get(field, 0.0)) > DEGRADATION_ERROR_THRESHOLD
        for field in ("error_rate_payments", "error_rate_orders", "error_rate_checkout")
    )


def _seconds_between(left_timestamp: str, right_timestamp: str) -> float:
    left = datetime.fromisoformat(left_timestamp.replace("Z", "+00:00"))
    right = datetime.fromisoformat(right_timestamp.replace("Z", "+00:00"))
    return max((right - left).total_seconds(), 0.0)


def _coalesce(value: Any, default: float) -> float:
    return default if value is None else float(value)
