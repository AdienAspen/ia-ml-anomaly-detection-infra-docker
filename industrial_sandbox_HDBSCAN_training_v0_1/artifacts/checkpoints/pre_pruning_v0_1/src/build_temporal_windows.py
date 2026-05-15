"""Build multivariate temporal windows from common telemetry events."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
import json

from src.common_telemetry import CommonTelemetryEvent, sort_common_telemetry_events
from src.scenario_engine import SERVICE_METRICS, build_scenario_events

POLICY_PATH = Path(__file__).resolve().parents[1] / "configs" / "windowing_policy.yaml"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "temporal_windows_v0_1.json"
SCHEMA_VERSION = "temporal_window_v0_1"
EXPECTED_SERVICE_METRIC_PAIRS = {
    (service_name, metric_name)
    for service_name, metrics in SERVICE_METRICS.items()
    for metric_name, _unit in metrics
}


@dataclass(frozen=True)
class WindowingPolicy:
    window_length_seconds: int
    stride_seconds: int
    max_missing_ratio: float
    late_event_tolerance_seconds: int
    late_discard_ratio_threshold: float
    min_events_per_window: int
    discard_window_if_quality_below: float
    late_event_policy_mode: str
    within_tolerance_action: str
    beyond_tolerance_action: str


def load_windowing_policy(path: Path = POLICY_PATH) -> WindowingPolicy:
    parsed: dict[str, str] = {}
    current_section: str | None = None
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.endswith(":"):
                current_section = stripped[:-1]
                continue
            if ":" not in stripped:
                continue
            key, value = stripped.split(":", 1)
            full_key = f"{current_section}.{key.strip()}" if current_section else key.strip()
            parsed[full_key] = value.strip()
    return WindowingPolicy(
        window_length_seconds=int(parsed["window_length_seconds"]),
        stride_seconds=int(parsed["stride_seconds"]),
        max_missing_ratio=float(parsed["max_missing_ratio"]),
        late_event_tolerance_seconds=int(parsed["late_event_tolerance_seconds"]),
        late_discard_ratio_threshold=float(parsed["late_discard_ratio_threshold"]),
        min_events_per_window=int(parsed["min_events_per_window"]),
        discard_window_if_quality_below=float(parsed["discard_window_if_quality_below"]),
        late_event_policy_mode=parsed["late_event_policy.mode"],
        within_tolerance_action=parsed["late_event_policy.within_tolerance_action"],
        beyond_tolerance_action=parsed["late_event_policy.beyond_tolerance_action"],
    )


def build_temporal_windows(
    events: list[CommonTelemetryEvent],
    *,
    policy: WindowingPolicy | None = None,
) -> list[dict[str, Any]]:
    if not events:
        return []

    active_policy = policy or load_windowing_policy()
    ordered_events = sort_common_telemetry_events(events)
    normalized_events = [
        (event, datetime.fromisoformat(event.timestamp.replace("Z", "+00:00")))
        for event in ordered_events
    ]

    first_timestamp = normalized_events[0][1]
    last_timestamp = normalized_events[-1][1]
    windows: list[dict[str, Any]] = []
    window_index = 0
    start_time = first_timestamp
    window_delta = timedelta(seconds=active_policy.window_length_seconds)
    stride_delta = timedelta(seconds=active_policy.stride_seconds)
    tolerance_delta = timedelta(seconds=active_policy.late_event_tolerance_seconds)

    while start_time <= last_timestamp:
        end_time = start_time + window_delta
        strict_events = [
            event for event, ts in normalized_events if start_time <= ts < end_time
        ]
        tolerated_late_events = [
            event for event, ts in normalized_events if end_time <= ts < end_time + tolerance_delta
        ]
        late_discarded_for_window = [
            event
            for event, ts in normalized_events
            if end_time + tolerance_delta <= ts < end_time + stride_delta
        ]
        window_events = strict_events + tolerated_late_events
        if window_events:
            window = _build_window_record(
                window_id=f"temporal_window_{window_index:04d}",
                start_time=start_time,
                end_time=end_time,
                strict_events=strict_events,
                tolerated_late_events=tolerated_late_events,
                late_discarded_for_window=late_discarded_for_window,
                policy=active_policy,
            )
            windows.append(window)
        start_time = start_time + stride_delta
        window_index += 1

    return windows


def export_temporal_windows(rows: list[dict[str, Any]], output_path: Path = OUTPUT_PATH) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2)
    return output_path


def main() -> int:
    sample_events = build_scenario_events("S4_INTERSERVICE_CHAIN", seed=42, steps=8)
    windows = build_temporal_windows(sample_events)
    export_temporal_windows(windows)
    print(f"Temporal window builder ready: {len(windows)} windows -> {OUTPUT_PATH}")
    return 0


def _build_window_record(
    *,
    window_id: str,
    start_time: datetime,
    end_time: datetime,
    strict_events: list[CommonTelemetryEvent],
    tolerated_late_events: list[CommonTelemetryEvent],
    late_discarded_for_window: list[CommonTelemetryEvent],
    policy: WindowingPolicy,
) -> dict[str, Any]:
    all_events = strict_events + tolerated_late_events
    grouped_values: dict[tuple[str, str], list[float]] = defaultdict(list)
    services_included = sorted({event.service_name for event in all_events})
    scenario_tags = {event.scenario_tag for event in all_events if event.scenario_tag is not None}
    chaos_suitabilities = {event.chaos_suitability for event in all_events if event.chaos_suitability is not None}

    for event in all_events:
        grouped_values[(event.service_name, event.metric_name)].append(event.metric_value)

    features: dict[str, Any] = {}
    for service_name, metrics in SERVICE_METRICS.items():
        for metric_name, _unit in metrics:
            key = f"{service_name}__{metric_name}"
            values = grouped_values.get((service_name, metric_name), [])
            features[key] = round(sum(values) / len(values), 6) if values else None

    strict_pair_set = {(event.service_name, event.metric_name) for event in strict_events}
    ordering_broken, ordering_violations = _sequence_integrity_status(all_events)
    covered_ratio = len(strict_pair_set) / max(len(EXPECTED_SERVICE_METRIC_PAIRS), 1)
    missing_ratio = 1.0 - covered_ratio
    min_event_ratio = min(len(strict_events) / max(policy.min_events_per_window, 1), 1.0)
    late_event_ratio = len(tolerated_late_events) / max(len(all_events), 1)
    late_discard_ratio = len(late_discarded_for_window) / max(len(all_events) + len(late_discarded_for_window), 1)
    degraded_quality = late_discard_ratio > policy.late_discard_ratio_threshold
    quality_score = round(
        max(
            min(
                (covered_ratio * 0.55)
                + (min_event_ratio * 0.20)
                + ((1.0 - late_event_ratio) * 0.10)
                + ((1.0 - late_discard_ratio) * 0.15),
                1.0,
            ),
            0.0,
        ),
        6,
    )
    if degraded_quality:
        quality_score = round(max(quality_score - 0.10, 0.0), 6)
    if ordering_broken:
        quality_score = round(max(quality_score - 0.20, 0.0), 6)

    accepted_for_training = (
        missing_ratio <= policy.max_missing_ratio
        and len(strict_events) >= policy.min_events_per_window
        and quality_score >= policy.discard_window_if_quality_below
        and not ordering_broken
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "window_id": window_id,
        "window_start": start_time.isoformat(),
        "window_end": end_time.isoformat(),
        "services_included": services_included,
        "features": features,
        "window_data_quality_score": quality_score,
        "scenario_tag": next(iter(sorted(scenario_tags))) if scenario_tags else None,
        "chaos_suitability": next(iter(sorted(chaos_suitabilities))) if chaos_suitabilities else None,
        "training_metadata": {
            "strict_event_count": len(strict_events),
            "late_events_within_tolerance": len(tolerated_late_events),
            "late_discarded_for_window_count": len(late_discarded_for_window),
            "total_event_count": len(all_events),
            "covered_service_metric_pairs": len(strict_pair_set),
            "expected_service_metric_pairs": len(EXPECTED_SERVICE_METRIC_PAIRS),
            "missing_ratio": round(missing_ratio, 6),
            "coverage_ratio": round(covered_ratio, 6),
            "min_event_ratio": round(min_event_ratio, 6),
            "late_event_ratio": round(late_event_ratio, 6),
            "late_discard_ratio": round(late_discard_ratio, 6),
            "degraded_quality": degraded_quality,
            "ordering_broken": ordering_broken,
            "ordering_violation_services": ordering_violations,
            "accepted_for_training": accepted_for_training,
            "discard_below_quality_threshold": policy.discard_window_if_quality_below,
            "max_missing_ratio": policy.max_missing_ratio,
            "min_events_per_window": policy.min_events_per_window,
            "ordering_strategy": "timestamp_then_sequence_number",
            "late_event_policy": {
                "mode": policy.late_event_policy_mode,
                "within_tolerance_action": policy.within_tolerance_action,
                "beyond_tolerance_action": policy.beyond_tolerance_action,
                "late_event_tolerance_seconds": policy.late_event_tolerance_seconds,
                "late_discard_ratio_threshold": policy.late_discard_ratio_threshold,
            },
            "feature_inputs": {
                "service_metric_series": _serialize_metric_series(strict_events, tolerated_late_events),
            },
        },
    }




def _sequence_integrity_status(events: list[CommonTelemetryEvent]) -> tuple[bool, list[str]]:
    sequence_history: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for event in sorted(events, key=lambda item: (item.timestamp, item.sequence_number)):
        sequence_history[event.service_name].append((event.timestamp, int(event.sequence_number)))

    violations: list[str] = []
    for service_name, entries in sequence_history.items():
        previous_sequence: int | None = None
        for _timestamp, sequence_number in entries:
            if previous_sequence is not None and sequence_number <= previous_sequence:
                violations.append(service_name)
                break
            previous_sequence = sequence_number
    return bool(violations), sorted(set(violations))

def _serialize_metric_series(
    strict_events: list[CommonTelemetryEvent],
    tolerated_late_events: list[CommonTelemetryEvent],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    service_metric_series: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    tolerated_ids = {event.event_id for event in tolerated_late_events}
    for event in strict_events + tolerated_late_events:
        service_metric_series[event.service_name][event.metric_name].append(
            {
                "timestamp": event.timestamp,
                "sequence_number": event.sequence_number,
                "metric_value": event.metric_value,
                "within_late_tolerance": event.event_id in tolerated_ids,
            }
        )
    return {
        service_name: {metric_name: points for metric_name, points in metrics.items()}
        for service_name, metrics in service_metric_series.items()
    }
