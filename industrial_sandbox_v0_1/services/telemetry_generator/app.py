import csv
import json
import math
import os
import random
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import redis

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_CHANNEL = os.getenv("REDIS_CHANNEL", "telemetry.raw")
INTERVAL = float(os.getenv("TELEMETRY_INTERVAL_SECONDS", "2"))
SCENARIO = os.getenv("TELEMETRY_SCENARIO", "normal").lower()
PROFILE = os.getenv("TELEMETRY_PROFILE", "simple").lower()
RUN_DURATION_MINUTES = float(os.getenv("TELEMETRY_RUN_DURATION_MINUTES", "60"))
MAX_EVENTS = int(os.getenv("TELEMETRY_MAX_EVENTS", "0"))
SOURCE_NODE = os.getenv("TELEMETRY_SOURCE_NODE", "node-01")
HEARTBEAT_PATH = "/tmp/telemetry_generator_heartbeat"
EXPORT_ENABLED = os.getenv("TELEMETRY_EXPORT_ENABLED", "false").lower() == "true"
EXPORT_PATH = Path(os.getenv("TELEMETRY_EXPORT_PATH", "/app/data/synthetic/telemetry_events.csv"))
EXPORT_VERSIONED = os.getenv("TELEMETRY_EXPORT_VERSIONED", "true").lower() == "true"
APP_TIMEZONE = os.getenv("APP_TIMEZONE", os.getenv("TZ", "America/Santiago"))

client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

try:
    APP_TZ = ZoneInfo(APP_TIMEZONE)
except ZoneInfoNotFoundError:
    APP_TZ = ZoneInfo("UTC")

FEATURE_FIELDS = [
    "cpu_pct",
    "memory_pct",
    "latency_ms",
    "disk_io_pct",
    "net_error_rate",
    "queue_length",
    "throughput_rate",
    "http_5xx_rate",
]

EVENT_FIELDS = [
    "event_id",
    "generated_at",
    "source_node",
    "service_name",
    "status_code",
    "is_synthetic",
    "scenario_tag",
    "telemetry_profile",
    *FEATURE_FIELDS,
]

SIMPLE_SERVICES = ["payments-api"]
MARKET_SERVICES = ["payments-api", "orders-api", "checkout-api"]

MARKET_SERVICE_PROFILES = {
    "payments-api": {
        "cpu_base": 41.0,
        "memory_base": 49.0,
        "latency_base": 36.0,
        "disk_base": 26.0,
        "queue_base": 24.0,
        "throughput_base": 84.0,
        "http5xx_base": 0.45,
        "net_error_base": 0.11,
        "latency_bias": 1.15,
    },
    "orders-api": {
        "cpu_base": 47.0,
        "memory_base": 44.0,
        "latency_base": 28.0,
        "disk_base": 31.0,
        "queue_base": 18.0,
        "throughput_base": 118.0,
        "http5xx_base": 0.28,
        "net_error_base": 0.08,
        "latency_bias": 0.95,
    },
    "checkout-api": {
        "cpu_base": 45.0,
        "memory_base": 47.0,
        "latency_base": 33.0,
        "disk_base": 29.0,
        "queue_base": 20.0,
        "throughput_base": 96.0,
        "http5xx_base": 0.52,
        "net_error_base": 0.16,
        "latency_bias": 1.05,
    },
}

SCENARIO_ADJUSTMENTS = {
    "normal": {
        "burst_chance": 0.05,
        "burst_strength": 0.35,
        "burst_min": 4.0,
        "burst_max": 12.0,
        "drift_step": 0.03,
        "scenario_intensity": 0.0,
        "anomaly_probability": 0.0,
        "force_anomalous_label_on_intensity": True,
        "label_burst_as_anomalous": True,
        "label_http5xx_threshold": 1.8,
        "label_queue_threshold": 85.0,
        "label_latency_threshold": 220.0,
    },
    "anomalous": {
        "burst_chance": 0.18,
        "burst_strength": 1.0,
        "burst_min": 4.0,
        "burst_max": 12.0,
        "drift_step": 0.08,
        "scenario_intensity": 0.9,
        "anomaly_probability": 0.3,
        "force_anomalous_label_on_intensity": True,
        "label_burst_as_anomalous": True,
        "label_http5xx_threshold": 1.8,
        "label_queue_threshold": 85.0,
        "label_latency_threshold": 220.0,
    },
    "training_normal_v1": {
        "burst_chance": 0.004,
        "burst_strength": 0.08,
        "burst_min": 3.0,
        "burst_max": 7.0,
        "drift_step": 0.0015,
        "scenario_intensity": 0.12,
        "anomaly_probability": 0.015,
        "force_anomalous_label_on_intensity": False,
        "label_burst_as_anomalous": False,
        "label_http5xx_threshold": 5.5,
        "label_queue_threshold": 180.0,
        "label_latency_threshold": 360.0,
    },
    "validation_mixed_v1": {
        "burst_chance": 0.045,
        "burst_strength": 0.28,
        "burst_min": 3.0,
        "burst_max": 7.0,
        "drift_step": 0.0075,
        "scenario_intensity": 0.24,
        "anomaly_probability": 0.09,
        "force_anomalous_label_on_intensity": True,
        "label_burst_as_anomalous": False,
        "label_http5xx_threshold": 3.2,
        "label_queue_threshold": 120.0,
        "label_latency_threshold": 265.0,
    },
}

random.seed()
RUN_STARTED_AT = datetime.now(APP_TZ)
EXPORT_RUN_ID = RUN_STARTED_AT.strftime("%Y%m%dT%H%M%S%z")


def resolve_export_path(base_path: Path) -> Path:
    if not EXPORT_VERSIONED:
        return base_path

    suffix = base_path.suffix or ".csv"
    return base_path.with_name(f"{base_path.stem}_{EXPORT_RUN_ID}{suffix}")


EFFECTIVE_EXPORT_PATH = resolve_export_path(EXPORT_PATH)


def bounded(value: float, lower: float, upper: float) -> float:
    return round(max(lower, min(upper, value)), 3)


def write_export_row(event: dict) -> None:
    if not EXPORT_ENABLED:
        return
    EFFECTIVE_EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    file_exists = EFFECTIVE_EXPORT_PATH.exists()
    with EFFECTIVE_EXPORT_PATH.open("a", newline="", encoding="utf-8") as export_file:
        writer = csv.DictWriter(export_file, fieldnames=EVENT_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow({field: event[field] for field in EVENT_FIELDS})


def choose_service(iteration: int) -> str:
    services = SIMPLE_SERVICES if PROFILE == "simple" else MARKET_SERVICES
    return services[iteration % len(services)]


def simple_event(service_name: str) -> dict:
    scenario_profile = SCENARIO_ADJUSTMENTS.get(SCENARIO, SCENARIO_ADJUSTMENTS["normal"])
    anomaly_mode = random.random() < scenario_profile["anomaly_probability"]
    cpu = bounded(random.gauss(35 if not anomaly_mode else 89, 8), 0.0, 100.0)
    memory = bounded(random.gauss(42 if not anomaly_mode else 93, 7), 0.0, 100.0)
    latency = bounded(random.gauss(22 if not anomaly_mode else 280, 9), 0.0, 5000.0)
    disk = bounded(random.gauss(28 if not anomaly_mode else 81, 10), 0.0, 100.0)
    net_errors = bounded(random.gauss(0.02 if not anomaly_mode else 2.8, 0.06), 0.0, 1000.0)
    queue_length = bounded(latency * 0.35 + cpu * 0.12 + random.uniform(0.0, 8.0), 0.0, 5000.0)
    throughput_rate = bounded(max(5.0, 120.0 - latency * 0.7 + random.uniform(-6.0, 6.0)), 0.0, 5000.0)
    http_5xx_rate = bounded((0.03 if not anomaly_mode else 3.1) + net_errors * 0.18, 0.0, 100.0)
    status_code = 200 if not anomaly_mode else random.choice([429, 500, 502, 503])
    return {
        "service_name": service_name,
        "cpu_pct": cpu,
        "memory_pct": memory,
        "latency_ms": latency,
        "disk_io_pct": disk,
        "net_error_rate": net_errors,
        "queue_length": queue_length,
        "throughput_rate": throughput_rate,
        "http_5xx_rate": http_5xx_rate,
        "status_code": status_code,
        "scenario_tag": "anomalous" if anomaly_mode else "normal",
    }


def market_event(service_name: str, iteration: int) -> dict:
    service_profile = MARKET_SERVICE_PROFILES[service_name]
    scenario_profile = SCENARIO_ADJUSTMENTS.get(SCENARIO, SCENARIO_ADJUSTMENTS["normal"])

    phase = iteration / 6.0
    seasonal = math.sin(phase) * 4.0 + math.cos(phase / 2.0) * 2.0

    scenario_intensity = 0.0
    if random.random() < scenario_profile["anomaly_probability"]:
        scenario_intensity = scenario_profile["scenario_intensity"]

    burst_active = random.random() < scenario_profile["burst_chance"]
    burst = (
        scenario_profile["burst_strength"]
        * random.uniform(scenario_profile["burst_min"], scenario_profile["burst_max"])
        if burst_active
        else 0.0
    )
    drift = scenario_profile["drift_step"] * iteration

    cpu = service_profile["cpu_base"] + seasonal + drift + scenario_intensity * 14.0 + burst + random.gauss(0.0, 2.2)
    memory = service_profile["memory_base"] + seasonal * 0.65 + drift * 0.4 + scenario_intensity * 9.0 + burst * 0.5 + random.gauss(0.0, 1.8)
    disk = service_profile["disk_base"] + seasonal * 0.35 + scenario_intensity * 6.5 + burst * 0.45 + random.gauss(0.0, 1.3)
    queue = service_profile["queue_base"] + cpu * 0.45 + drift * 3.0 + burst * 5.0 + scenario_intensity * 18.0 + random.gauss(0.0, 4.5)
    throughput = service_profile["throughput_base"] + seasonal * 1.5 - queue * 0.42 - scenario_intensity * 16.0 + burst * 1.8 + random.gauss(0.0, 3.2)
    http_5xx = service_profile["http5xx_base"] + scenario_intensity * 1.7 + burst * 0.22 + max(queue - 35.0, 0.0) * 0.03 + random.gauss(0.0, 0.08)
    net_errors = service_profile["net_error_base"] + http_5xx * 0.33 + scenario_intensity * 0.7 + random.gauss(0.0, 0.04)
    latency = (
        service_profile["latency_base"]
        + cpu * 0.58 * service_profile["latency_bias"]
        + queue * 0.9
        - throughput * 0.17
        + http_5xx * 9.0
        + burst * 3.1
        + drift * 2.0
        + random.gauss(0.0, 6.0)
    )

    queue_length = bounded(queue, 0.0, 5000.0)
    throughput_rate = bounded(throughput, 0.0, 5000.0)
    http_5xx_rate = bounded(http_5xx, 0.0, 100.0)
    net_error_rate = bounded(net_errors, 0.0, 1000.0)
    cpu_pct = bounded(cpu, 0.0, 100.0)
    memory_pct = bounded(memory, 0.0, 100.0)
    disk_io_pct = bounded(disk, 0.0, 100.0)
    latency_ms = bounded(latency, 0.0, 5000.0)

    if http_5xx_rate >= 2.0:
        status_code = random.choice([429, 500, 502, 503])
    elif latency_ms > 120.0 or queue_length > 55.0:
        status_code = random.choice([200, 200, 200, 429])
    else:
        status_code = 200

    if (
        (
            scenario_profile["force_anomalous_label_on_intensity"]
            and scenario_intensity > 0.0
        )
        or (scenario_profile["label_burst_as_anomalous"] and burst_active)
        or http_5xx_rate >= scenario_profile["label_http5xx_threshold"]
        or queue_length >= scenario_profile["label_queue_threshold"]
        or latency_ms >= scenario_profile["label_latency_threshold"]
    ):
        scenario_tag = "anomalous"
    else:
        scenario_tag = "normal"

    return {
        "service_name": service_name,
        "cpu_pct": cpu_pct,
        "memory_pct": memory_pct,
        "latency_ms": latency_ms,
        "disk_io_pct": disk_io_pct,
        "net_error_rate": net_error_rate,
        "queue_length": queue_length,
        "throughput_rate": throughput_rate,
        "http_5xx_rate": http_5xx_rate,
        "status_code": status_code,
        "scenario_tag": scenario_tag,
    }


def build_event(iteration: int) -> dict:
    service_name = choose_service(iteration)
    payload = simple_event(service_name) if PROFILE == "simple" else market_event(service_name, iteration)
    return {
        "event_id": str(uuid.uuid4()),
        "generated_at": datetime.now(APP_TZ).isoformat(),
        "source_node": SOURCE_NODE,
        "is_synthetic": True,
        "telemetry_profile": PROFILE,
        **payload,
    }


run_duration_seconds = max(0.0, RUN_DURATION_MINUTES * 60)
deadline_epoch = time.time() + run_duration_seconds if run_duration_seconds and MAX_EVENTS <= 0 else None
events_published = 0

while True:
    if MAX_EVENTS > 0 and events_published >= MAX_EVENTS:
        print(
            json.dumps(
                {
                    "status": "completed",
                    "completion_mode": "count_bound",
                    "events_published": events_published,
                    "target_events": MAX_EVENTS,
                    "run_duration_minutes": RUN_DURATION_MINUTES,
                    "telemetry_profile": PROFILE,
                    "telemetry_scenario": SCENARIO,
                    "export_path": str(EFFECTIVE_EXPORT_PATH) if EXPORT_ENABLED else None,
                }
            ),
            flush=True,
        )
        break

    if deadline_epoch is not None and time.time() >= deadline_epoch:
        print(
            json.dumps(
                {
                    "status": "completed",
                    "completion_mode": "time_bound",
                    "events_published": events_published,
                    "run_duration_minutes": RUN_DURATION_MINUTES,
                    "telemetry_profile": PROFILE,
                    "telemetry_scenario": SCENARIO,
                    "export_path": str(EFFECTIVE_EXPORT_PATH) if EXPORT_ENABLED else None,
                }
            ),
            flush=True,
        )
        break

    event = build_event(events_published)
    client.publish(REDIS_CHANNEL, json.dumps(event))
    write_export_row(event)
    events_published += 1
    with open(HEARTBEAT_PATH, "w", encoding="utf-8") as heartbeat_file:
        heartbeat_file.write(str(time.time()))
    print(
        json.dumps(
            {
                "published": event["event_id"],
                "scenario": event["scenario_tag"],
                "service_name": event["service_name"],
                "telemetry_profile": event["telemetry_profile"],
            }
        ),
        flush=True,
    )
    time.sleep(INTERVAL)
