from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ServiceProfile:
    service_name: str
    cpu_base: float
    memory_base: float
    latency_base: float
    disk_base: float
    queue_base: float
    throughput_base: float
    http5xx_base: float
    net_error_base: float
    latency_bias: float


@dataclass(frozen=True)
class ScenarioProfile:
    scenario_name: str
    burst_chance: float
    burst_strength: float
    burst_min: float
    burst_max: float
    drift_step: float
    scenario_intensity: float
    anomaly_probability: float
    force_anomalous_label_on_intensity: bool
    label_burst_as_anomalous: bool
    label_http5xx_threshold: float
    label_queue_threshold: float
    label_latency_threshold: float
    drift_reference_rows: int = 5000


SERVICE_PROFILES = {
    "payments-api": ServiceProfile(
        service_name="payments-api",
        cpu_base=41.0,
        memory_base=49.0,
        latency_base=36.0,
        disk_base=26.0,
        queue_base=24.0,
        throughput_base=84.0,
        http5xx_base=0.45,
        net_error_base=0.11,
        latency_bias=1.15,
    ),
    "orders-api": ServiceProfile(
        service_name="orders-api",
        cpu_base=47.0,
        memory_base=44.0,
        latency_base=28.0,
        disk_base=31.0,
        queue_base=18.0,
        throughput_base=118.0,
        http5xx_base=0.28,
        net_error_base=0.08,
        latency_bias=0.95,
    ),
    "checkout-api": ServiceProfile(
        service_name="checkout-api",
        cpu_base=45.0,
        memory_base=47.0,
        latency_base=33.0,
        disk_base=29.0,
        queue_base=20.0,
        throughput_base=96.0,
        http5xx_base=0.52,
        net_error_base=0.16,
        latency_bias=1.05,
    ),
}


SCENARIO_PROFILES = {
    "normal": ScenarioProfile(
        scenario_name="normal",
        burst_chance=0.05,
        burst_strength=0.35,
        burst_min=4.0,
        burst_max=12.0,
        drift_step=0.03,
        scenario_intensity=0.0,
        anomaly_probability=0.0,
        force_anomalous_label_on_intensity=True,
        label_burst_as_anomalous=True,
        label_http5xx_threshold=1.8,
        label_queue_threshold=85.0,
        label_latency_threshold=220.0,
    ),
    "anomalous": ScenarioProfile(
        scenario_name="anomalous",
        burst_chance=0.18,
        burst_strength=1.0,
        burst_min=4.0,
        burst_max=12.0,
        drift_step=0.08,
        scenario_intensity=0.9,
        anomaly_probability=0.3,
        force_anomalous_label_on_intensity=True,
        label_burst_as_anomalous=True,
        label_http5xx_threshold=1.8,
        label_queue_threshold=85.0,
        label_latency_threshold=220.0,
    ),
    "training_normal_v1": ScenarioProfile(
        scenario_name="training_normal_v1",
        burst_chance=0.004,
        burst_strength=0.08,
        burst_min=3.0,
        burst_max=7.0,
        drift_step=0.0015,
        scenario_intensity=0.12,
        anomaly_probability=0.015,
        force_anomalous_label_on_intensity=False,
        label_burst_as_anomalous=False,
        label_http5xx_threshold=5.5,
        label_queue_threshold=180.0,
        label_latency_threshold=360.0,
    ),
    "validation_mixed_v1": ScenarioProfile(
        scenario_name="validation_mixed_v1",
        burst_chance=0.045,
        burst_strength=0.28,
        burst_min=3.0,
        burst_max=7.0,
        drift_step=0.0075,
        scenario_intensity=0.24,
        anomaly_probability=0.09,
        force_anomalous_label_on_intensity=True,
        label_burst_as_anomalous=False,
        label_http5xx_threshold=3.2,
        label_queue_threshold=120.0,
        label_latency_threshold=265.0,
    ),
}
