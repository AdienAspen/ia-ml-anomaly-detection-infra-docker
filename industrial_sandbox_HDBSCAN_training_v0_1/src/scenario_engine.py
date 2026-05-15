"""Stochastic scenario engine for block 1B.2.

The engine produces plausible synthetic telemetry events under a shared common
contract. Scenarios are intentionally noisy and non-deterministic so the future
correlation engine must learn temporal signatures rather than memorize perfect
chains.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from random import Random
from typing import Any
import statistics
import uuid

from src.common_telemetry import CommonTelemetryEvent, build_common_telemetry_event, validate_common_telemetry_event

SCENARIO_NAMES = (
    "S0_NORMAL_BASELINE",
    "S1_LOCAL_ANOMALY_ONLY",
    "S2_SERVICE_TO_REDIS_PROPAGATION",
    "S3_REDIS_TO_MULTISERVICE_PROPAGATION",
    "S4_INTERSERVICE_CHAIN",
    "S5_DRIFT_WITHOUT_INCIDENT",
    "S6_NOISE_FALSE_POSITIVE",
    "S7_RECOVERY_AFTER_DEGRADATION",
    "S8_HIGH_DENSITY_UNCORRELATED_NOISE",
)

SERVICE_METRICS = {
    "payments-api": (("latency_p95", "milliseconds"), ("error_rate", "ratio"), ("throughput", "requests_per_interval")),
    "orders-api": (("latency_p95", "milliseconds"), ("error_rate", "ratio"), ("throughput", "requests_per_interval")),
    "checkout-api": (("latency_p95", "milliseconds"), ("error_rate", "ratio"), ("throughput", "requests_per_interval")),
    "redis": (("redis_latency", "milliseconds"), ("redis_queue_depth", "items")),
}

BASELINE_METRICS = {
    "payments-api": {"latency_p95": 180.0, "error_rate": 0.012, "throughput": 220.0},
    "orders-api": {"latency_p95": 165.0, "error_rate": 0.010, "throughput": 190.0},
    "checkout-api": {"latency_p95": 175.0, "error_rate": 0.011, "throughput": 170.0},
    "redis": {"redis_latency": 7.5, "redis_queue_depth": 24.0},
}

METRIC_NOISE_RATIO = {
    "latency_p95": 0.06,
    "error_rate": 0.22,
    "throughput": 0.08,
    "redis_latency": 0.10,
    "redis_queue_depth": 0.20,
}


@dataclass(frozen=True)
class ScenarioDefinition:
    name: str
    description: str
    expected_propagation: bool
    chaos_suitability: str | None
    root_service: str | None = None
    propagation_chain: tuple[str, ...] = ()
    negative_case: bool = False
    allows_branching: bool = False
    includes_recovery: bool = False


@dataclass(frozen=True)
class ScenarioControls:
    jitter_seconds_min: int = 0
    jitter_seconds_max: int = 20
    lag_seconds_min: int = 10
    lag_seconds_max: int = 90
    intensity_scale_min: float = 0.6
    intensity_scale_max: float = 1.4


def scenario_catalog() -> dict[str, ScenarioDefinition]:
    return {
        "S0_NORMAL_BASELINE": ScenarioDefinition(
            name="S0_NORMAL_BASELINE",
            description="Stable baseline without notable propagation.",
            expected_propagation=False,
            chaos_suitability="not_suitable",
            negative_case=True,
        ),
        "S1_LOCAL_ANOMALY_ONLY": ScenarioDefinition(
            name="S1_LOCAL_ANOMALY_ONLY",
            description="Single-service degradation without downstream spread.",
            expected_propagation=False,
            chaos_suitability="requires_review",
            root_service="payments-api",
        ),
        "S2_SERVICE_TO_REDIS_PROPAGATION": ScenarioDefinition(
            name="S2_SERVICE_TO_REDIS_PROPAGATION",
            description="A service degrades first and Redis absorbs the pressure later.",
            expected_propagation=True,
            chaos_suitability="suitable_with_limits",
            root_service="payments-api",
            propagation_chain=("payments-api", "redis"),
        ),
        "S3_REDIS_TO_MULTISERVICE_PROPAGATION": ScenarioDefinition(
            name="S3_REDIS_TO_MULTISERVICE_PROPAGATION",
            description="Redis pressure propagates outward to several API services.",
            expected_propagation=True,
            chaos_suitability="suitable_with_limits",
            root_service="redis",
            propagation_chain=("redis", "payments-api", "orders-api", "checkout-api"),
            allows_branching=True,
        ),
        "S4_INTERSERVICE_CHAIN": ScenarioDefinition(
            name="S4_INTERSERVICE_CHAIN",
            description="Multi-hop propagation across services and Redis.",
            expected_propagation=True,
            chaos_suitability="suitable_full_replay",
            root_service="payments-api",
            propagation_chain=("payments-api", "redis", "checkout-api", "orders-api"),
        ),
        "S5_DRIFT_WITHOUT_INCIDENT": ScenarioDefinition(
            name="S5_DRIFT_WITHOUT_INCIDENT",
            description="Gradual drift that should not look like a true incident chain.",
            expected_propagation=False,
            chaos_suitability="not_suitable",
            root_service="orders-api",
            negative_case=True,
        ),
        "S6_NOISE_FALSE_POSITIVE": ScenarioDefinition(
            name="S6_NOISE_FALSE_POSITIVE",
            description="Short-lived spikes and noise bursts without consistent order.",
            expected_propagation=False,
            chaos_suitability="not_suitable",
            negative_case=True,
        ),
        "S7_RECOVERY_AFTER_DEGRADATION": ScenarioDefinition(
            name="S7_RECOVERY_AFTER_DEGRADATION",
            description="Propagation with later partial recovery.",
            expected_propagation=True,
            chaos_suitability="suitable_with_limits",
            root_service="payments-api",
            propagation_chain=("payments-api", "redis", "checkout-api"),
            includes_recovery=True,
        ),
        "S8_HIGH_DENSITY_UNCORRELATED_NOISE": ScenarioDefinition(
            name="S8_HIGH_DENSITY_UNCORRELATED_NOISE",
            description="Heavy noise density with no stable propagation semantics.",
            expected_propagation=False,
            chaos_suitability="requires_review",
            negative_case=True,
        ),
    }


def build_scenario_events(
    scenario_name: str,
    *,
    seed: int = 7,
    steps: int = 12,
    interval_seconds: int = 30,
    start_at: datetime | None = None,
) -> list[CommonTelemetryEvent]:
    catalog = scenario_catalog()
    if scenario_name not in catalog:
        raise KeyError(f"unknown scenario: {scenario_name}")

    definition = catalog[scenario_name]
    controls = ScenarioControls()
    rng = Random(seed)
    start = start_at or datetime.now(timezone.utc).replace(microsecond=0)
    correlation_id = str(uuid.uuid4())
    intensity = rng.uniform(controls.intensity_scale_min, controls.intensity_scale_max)
    sequence_number = 0
    events: list[CommonTelemetryEvent] = []

    activation_steps = _build_activation_steps(definition, steps=steps, rng=rng)

    for step in range(steps):
        base_time = start + timedelta(seconds=step * interval_seconds)
        for service_name, metrics in SERVICE_METRICS.items():
            service_state = _service_state(
                scenario=definition,
                service_name=service_name,
                step=step,
                steps=steps,
                intensity=intensity,
                activation_steps=activation_steps,
                rng=rng,
            )
            window_id = f"{scenario_name.lower()}_{step:04d}"
            jitter_seconds = rng.randint(controls.jitter_seconds_min, controls.jitter_seconds_max)
            service_time = base_time + timedelta(seconds=jitter_seconds)
            for metric_name, unit in metrics:
                baseline_value = BASELINE_METRICS[service_name][metric_name]
                metric_value = _apply_metric_model(
                    metric_name=metric_name,
                    baseline_value=baseline_value,
                    state=service_state,
                    rng=rng,
                )
                event = build_common_telemetry_event(
                    sequence_number=sequence_number,
                    timestamp=service_time.isoformat(),
                    window_id=window_id,
                    service_name=service_name,
                    metric_name=metric_name,
                    metric_value=metric_value,
                    unit=unit,
                    source="synthetic_generator",
                    correlation_id=correlation_id,
                    scenario_tag=scenario_name,
                    chaos_suitability=definition.chaos_suitability,
                    metadata={
                        "scenario_description": definition.description,
                        "expected_propagation": definition.expected_propagation,
                        "phase": service_state["phase"],
                        "service_intensity": round(service_state["intensity"], 6),
                        "activation_step": activation_steps.get(service_name),
                        "seed": seed,
                    },
                )
                events.append(event)
                sequence_number += 1

    return events


def scenario_summary(events: list[CommonTelemetryEvent]) -> dict[str, Any]:
    validations = [validate_common_telemetry_event(event.to_dict()) for event in events]
    invalid_events = sum(1 for errors in validations if errors)
    event_counts: dict[str, int] = {}
    metric_means: dict[str, float] = {}
    scenario_name = events[0].scenario_tag if events else None

    for event in events:
        event_counts[event.service_name] = event_counts.get(event.service_name, 0) + 1

    for metric_name in sorted({event.metric_name for event in events}):
        values = [event.metric_value for event in events if event.metric_name == metric_name]
        metric_means[metric_name] = round(statistics.fmean(values), 6)

    return {
        "scenario_tag": scenario_name,
        "events_generated": len(events),
        "invalid_events": invalid_events,
        "services_covered": sorted(event_counts),
        "events_by_service": event_counts,
        "metric_means": metric_means,
    }


def main() -> int:
    events = build_scenario_events("S4_INTERSERVICE_CHAIN", seed=42, steps=10)
    summary = scenario_summary(events)
    print(f"Scenario engine ready: {summary['scenario_tag']} -> {summary['events_generated']} events")
    if summary["invalid_events"]:
        print(f"Invalid events detected: {summary['invalid_events']}")
        return 1
    return 0


def _build_activation_steps(
    definition: ScenarioDefinition,
    *,
    steps: int,
    rng: Random,
) -> dict[str, int | None]:
    activation: dict[str, int | None] = {service_name: None for service_name in SERVICE_METRICS}
    root_start = 2
    if definition.root_service is not None:
        activation[definition.root_service] = root_start

    if definition.propagation_chain:
        current_step = root_start
        for index, service_name in enumerate(definition.propagation_chain):
            if index == 0:
                activation[service_name] = root_start
                continue
            current_step += rng.randint(1, 3)
            activation[service_name] = min(current_step, max(steps - 2, 0))

    return activation


def _service_state(
    *,
    scenario: ScenarioDefinition,
    service_name: str,
    step: int,
    steps: int,
    intensity: float,
    activation_steps: dict[str, int | None],
    rng: Random,
) -> dict[str, Any]:
    activation_step = activation_steps.get(service_name)
    is_active = activation_step is not None and step >= activation_step
    base_noise = rng.uniform(0.97, 1.03)
    service_intensity = 1.0
    phase = "baseline"

    if scenario.name == "S0_NORMAL_BASELINE":
        pass
    elif scenario.name == "S1_LOCAL_ANOMALY_ONLY" and service_name == scenario.root_service and is_active:
        service_intensity = 1.0 + 0.55 * intensity
        phase = "localized_degradation"
    elif scenario.name == "S2_SERVICE_TO_REDIS_PROPAGATION" and is_active:
        service_intensity = 1.0 + (0.45 if service_name == "payments-api" else 0.35) * intensity
        phase = "propagating"
    elif scenario.name == "S3_REDIS_TO_MULTISERVICE_PROPAGATION" and is_active:
        if service_name == "redis":
            service_intensity = 1.0 + 0.60 * intensity
        else:
            service_intensity = 1.0 + 0.30 * intensity
        phase = "branching_propagation"
    elif scenario.name == "S4_INTERSERVICE_CHAIN" and is_active:
        service_intensity = 1.0 + 0.40 * intensity + (0.05 * rng.random())
        phase = "interservice_chain"
    elif scenario.name == "S5_DRIFT_WITHOUT_INCIDENT" and service_name == scenario.root_service:
        service_intensity = 1.0 + (step / max(steps - 1, 1)) * 0.25 * intensity
        phase = "gradual_drift"
    elif scenario.name == "S6_NOISE_FALSE_POSITIVE":
        spike = rng.uniform(0.0, 0.40) if rng.random() < 0.30 else 0.0
        service_intensity = 1.0 + spike
        phase = "noise_spike" if spike else "baseline"
    elif scenario.name == "S7_RECOVERY_AFTER_DEGRADATION" and is_active:
        halfway = (activation_step or 0) + 2
        if step <= halfway:
            service_intensity = 1.0 + 0.45 * intensity
            phase = "propagating"
        else:
            service_intensity = 1.0 + 0.20 * intensity
            phase = "partial_recovery"
    elif scenario.name == "S8_HIGH_DENSITY_UNCORRELATED_NOISE":
        service_intensity = 1.0 + rng.uniform(0.0, 0.55)
        phase = "dense_noise"

    return {
        "intensity": max(service_intensity * base_noise, 0.01),
        "phase": phase,
    }


def _apply_metric_model(
    *,
    metric_name: str,
    baseline_value: float,
    state: dict[str, Any],
    rng: Random,
) -> float:
    intensity = state["intensity"]
    noise_ratio = METRIC_NOISE_RATIO[metric_name]
    noise = 1.0 + rng.uniform(-noise_ratio, noise_ratio)

    if metric_name in {"latency_p95", "error_rate", "redis_latency", "redis_queue_depth"}:
        raw_value = baseline_value * intensity * noise
    else:
        throughput_drop = max(0.35, 2.0 - intensity)
        raw_value = baseline_value * throughput_drop * noise

    return round(max(raw_value, 0.0), 6)
