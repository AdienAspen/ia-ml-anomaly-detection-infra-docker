"""Build the iforest-compatible feature view without breaking the existing 1B lane."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
import json

from src.common_telemetry import CommonTelemetryEvent
from src.scenario_engine import build_scenario_events

API_SERVICES = ("payments-api", "orders-api", "checkout-api")
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "interim" / "iforest_feature_view_v0_1.json"


def build_iforest_feature_view(events: list[CommonTelemetryEvent]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[CommonTelemetryEvent]] = defaultdict(list)
    for event in events:
        if event.service_name in API_SERVICES:
            grouped[(event.window_id or "no_window", event.service_name)].append(event)

    redis_grouped: dict[str, list[CommonTelemetryEvent]] = defaultdict(list)
    for event in events:
        if event.service_name == "redis":
            redis_grouped[event.window_id or "no_window"].append(event)

    rows: list[dict[str, Any]] = []
    for (window_id, service_name), group_events in sorted(grouped.items()):
        metric_map = _metric_value_map(group_events)
        redis_metrics = _metric_value_map(redis_grouped.get(window_id, []))
        latency = metric_map.get("latency_p95", 0.0)
        error_rate = metric_map.get("error_rate", 0.0)
        throughput = metric_map.get("throughput", 0.0)
        redis_latency = redis_metrics.get("redis_latency", 0.0)
        redis_queue_depth = redis_metrics.get("redis_queue_depth", 0.0)
        proxy_score = _compute_iforest_proxy_score(
            latency_p95=latency,
            error_rate=error_rate,
            throughput=throughput,
            redis_latency=redis_latency,
            redis_queue_depth=redis_queue_depth,
        )
        timestamps = [datetime.fromisoformat(event.timestamp.replace("Z", "+00:00")) for event in group_events]
        rows.append(
            {
                "schema_version": "iforest_feature_view_v0_1",
                "window_id": window_id,
                "service_name": service_name,
                "window_start": min(timestamps).isoformat(),
                "window_end": max(timestamps).isoformat(),
                "latency_p95": latency,
                "error_rate": error_rate,
                "throughput": throughput,
                "redis_latency": redis_latency,
                "redis_queue_depth": redis_queue_depth,
                "iforest_score": proxy_score,
                "iforest_score_source": "proxy_from_common_telemetry",
                "scenario_tag": group_events[0].scenario_tag,
                "chaos_suitability": group_events[0].chaos_suitability,
                "window_data_quality_score": _window_quality_score(group_events),
            }
        )
    return rows


def export_iforest_feature_view(rows: list[dict[str, Any]], output_path: Path = OUTPUT_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2)
    return output_path


def main() -> int:
    sample_events = build_scenario_events("S4_INTERSERVICE_CHAIN", seed=42, steps=8)
    rows = build_iforest_feature_view(sample_events)
    export_iforest_feature_view(rows)
    print(f"IForest feature view ready: {len(rows)} rows -> {OUTPUT_PATH}")
    return 0


def _metric_value_map(events: list[CommonTelemetryEvent]) -> dict[str, float]:
    values: dict[str, list[float]] = defaultdict(list)
    for event in events:
        values[event.metric_name].append(event.metric_value)
    return {metric_name: round(sum(metric_values) / len(metric_values), 6) for metric_name, metric_values in values.items()}


def _window_quality_score(events: list[CommonTelemetryEvent]) -> float:
    metric_names = {event.metric_name for event in events}
    expected_metrics = 3
    ratio = len(metric_names) / expected_metrics
    return round(min(max(ratio, 0.0), 1.0), 6)


def _compute_iforest_proxy_score(
    *,
    latency_p95: float,
    error_rate: float,
    throughput: float,
    redis_latency: float,
    redis_queue_depth: float,
) -> float:
    latency_component = min(latency_p95 / 400.0, 1.5)
    error_component = min(error_rate / 0.08, 1.5)
    throughput_component = min(max((220.0 - throughput) / 220.0, 0.0), 1.0)
    redis_component = min((redis_latency / 25.0) + (redis_queue_depth / 300.0), 1.5)
    return round((latency_component + error_component + throughput_component + redis_component) / 4.0, 6)
