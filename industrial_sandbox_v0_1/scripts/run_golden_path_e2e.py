from __future__ import annotations

import json
import subprocess
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import urlopen
from zoneinfo import ZoneInfo

import redis

REPO_ROOT = Path("/home/adien-i7-remote/workspace/anomaly-detection-iforest-docker")
COMPOSE_DIR = REPO_ROOT / "industrial_sandbox_v0_1"
REDIS_CONTAINER = "queue-broker"
ANOMALY_STREAM = "telemetry.anomaly.stream"
ENRICHED_STREAM = "enriched.correlation.stream"
CONTEXT_STREAM = "context_slice"
RAW_CHANNEL = "telemetry.raw"
TZ = ZoneInfo("America/Santiago")
REQUIRED_CONTAINERS = [
    "queue-broker",
    "anomaly-detector",
    "correlation-bridge",
    "agentic-layer",
    "otel-collector",
]
RESET_SERVICES = ["anomaly-detector", "correlation-bridge", "agentic-layer"]


class E2EFailure(RuntimeError):
    pass


def run(command: list[str], cwd: Path | None = None) -> str:
    completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=True)
    return completed.stdout.strip()


def redis_client() -> redis.Redis:
    ip = run(
        [
            "docker",
            "inspect",
            "-f",
            "{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            REDIS_CONTAINER,
        ]
    )
    return redis.Redis(host=ip, port=6379, db=0, decode_responses=True)


def container_health(container_name: str) -> tuple[str | None, str | None]:
    payload = run(["docker", "inspect", container_name, "--format", "{{json .State}}"])
    state = json.loads(payload)
    return state.get("Status"), (state.get("Health") or {}).get("Status")


def wait_healthy(container_name: str, timeout_seconds: int = 60) -> None:
    deadline = time.time() + timeout_seconds
    last = None
    while time.time() < deadline:
        last = container_health(container_name)
        if last == ("running", "healthy"):
            return
        time.sleep(2)
    raise E2EFailure(f"Container {container_name} did not become healthy in time. Last state={last}")


def ensure_runtime_ready() -> None:
    for container_name in REQUIRED_CONTAINERS:
        wait_healthy(container_name)


def restart_stateful_runtime() -> None:
    run(["docker", "compose", "stop", "telemetry-generator"], cwd=COMPOSE_DIR)
    run(["docker", "compose", "restart", *RESET_SERVICES], cwd=COMPOSE_DIR)
    for container_name in RESET_SERVICES:
        wait_healthy(container_name)


def detector_health() -> dict:
    with urlopen("http://127.0.0.1:18080/health", timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def build_raw_event(event_id: str, generated_at: str) -> dict:
    return {
        "event_id": event_id,
        "generated_at": generated_at,
        "source_node": "golden-path-e2e",
        "service_name": "payments-api",
        "status_code": 503,
        "is_synthetic": True,
        "scenario_tag": "golden_path_e2e",
        "telemetry_profile": "golden_path_v1",
        "cpu_pct": 99.0,
        "memory_pct": 98.0,
        "latency_ms": 1800.0,
        "disk_io_pct": 97.0,
        "net_error_rate": 15.0,
        "queue_length": 90.0,
        "throughput_rate": 4.0,
        "http_5xx_rate": 22.0,
    }


def wait_for_payload(stream_name: str, event_id: str, timeout_seconds: int = 30) -> dict:
    client = redis_client()
    deadline = time.time() + timeout_seconds
    last_count = 0
    while time.time() < deadline:
        messages = client.xrevrange(stream_name, count=200)
        last_count = len(messages)
        for _, fields in messages:
            payload = json.loads(fields["payload"])
            if payload.get("event_id") == event_id:
                return payload
        time.sleep(1)
    raise E2EFailure(f"Did not find event_id={event_id} in {stream_name}. Last tail count={last_count}")


def main() -> int:
    ensure_runtime_ready()
    restart_stateful_runtime()
    before = detector_health()
    client = redis_client()
    baseline_lengths = {
        ANOMALY_STREAM: client.xlen(ANOMALY_STREAM),
        ENRICHED_STREAM: client.xlen(ENRICHED_STREAM),
        CONTEXT_STREAM: client.xlen(CONTEXT_STREAM),
    }

    base_time = datetime.now(TZ)
    event_ids: list[str] = []
    for offset in range(3):
        event_id = f"golden-path-payments-{uuid.uuid4().hex[:10]}-{offset + 1}"
        event_ids.append(event_id)
        generated_at = (base_time + timedelta(seconds=offset)).isoformat()
        payload = build_raw_event(event_id, generated_at)
        client.publish(RAW_CHANNEL, json.dumps(payload, sort_keys=True))
        time.sleep(0.3)

    target_event_id = event_ids[-1]
    anomaly_payload = wait_for_payload(ANOMALY_STREAM, target_event_id)
    enriched_payload = wait_for_payload(ENRICHED_STREAM, target_event_id)
    context_payload = wait_for_payload(CONTEXT_STREAM, target_event_id)
    after = detector_health()

    if anomaly_payload.get("iforest_label") != "anomalous":
        raise E2EFailure(
            f"Expected anomalous detector label, got {anomaly_payload.get(iforest_label)}"
        )
    if not anomaly_payload.get("anomaly_flag"):
        raise E2EFailure("Expected anomaly_flag=true on the third detector signal")
    if enriched_payload.get("primary_service") != "payments-api":
        raise E2EFailure(
            f"Expected payments-api primary service, got {enriched_payload.get(primary_service)}"
        )
    if context_payload.get("primary_service") != "payments-api":
        raise E2EFailure(
            f"Expected payments-api context primary service, got {context_payload.get(primary_service)}"
        )
    if context_payload.get("event_id") != target_event_id:
        raise E2EFailure("Context slice event_id does not match the golden-path event")

    summary = {
        "status": "ok",
        "scenario": "golden_path_e2e_payments_local_chain",
        "published_raw_events": event_ids,
        "target_event_id": target_event_id,
        "baseline_stream_lengths": baseline_lengths,
        "final_stream_lengths": {
            ANOMALY_STREAM: client.xlen(ANOMALY_STREAM),
            ENRICHED_STREAM: client.xlen(ENRICHED_STREAM),
            CONTEXT_STREAM: client.xlen(CONTEXT_STREAM),
        },
        "detector_events_seen_before": before.get("events_seen"),
        "detector_events_seen_after": after.get("events_seen"),
        "detector_result": {
            "iforest_label": anomaly_payload.get("iforest_label"),
            "anomaly_flag": anomaly_payload.get("anomaly_flag"),
            "candidate_flag": anomaly_payload.get("candidate_flag"),
            "reason_codes": anomaly_payload.get("reason_codes"),
            "anomaly_score": anomaly_payload.get("anomaly_score"),
        },
        "enriched_result": {
            "primary_service": enriched_payload.get("primary_service"),
            "services_observed": enriched_payload.get("services_observed"),
            "severity_preliminary": enriched_payload.get("severity_preliminary"),
            "propagation_detected": enriched_payload.get("correlation_engine", {}).get("propagation_detected"),
            "propagation_signature_id": enriched_payload.get("correlation_engine", {}).get(
                "propagation_signature_id"
            ),
        },
        "context_result": {
            "primary_service": context_payload.get("primary_service"),
            "related_services": context_payload.get("related_services"),
            "estimated_tokens": context_payload.get("token_budget", {}).get("estimated_tokens"),
        },
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
