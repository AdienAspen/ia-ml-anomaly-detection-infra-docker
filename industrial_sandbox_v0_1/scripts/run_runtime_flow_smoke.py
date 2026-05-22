from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_DIR = REPO_ROOT / "industrial_sandbox_v0_1"

REQUIRED_CONTAINERS = {
    "queue-broker": "healthy",
    "anomaly-detector": "healthy",
    "correlation-bridge": "healthy",
    "agentic-layer": "healthy",
    "otel-collector": "healthy",
}

STREAMS = {
    "telemetry.anomaly.stream": "detector_signals",
    "enriched.correlation.stream": "enriched_events",
    "context_slice": "context_slices",
}


class SmokeFailure(RuntimeError):
    pass


def run(command: list[str], cwd: Path | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def inspect_container_health(container_name: str) -> dict[str, str | None]:
    payload = run(
        [
            "docker",
            "inspect",
            container_name,
            "--format",
            "{{json .State}}",
        ]
    )
    state = json.loads(payload)
    health = state.get("Health") or {}
    return {
        "status": state.get("Status"),
        "health": health.get("Status"),
    }


def ensure_required_containers() -> None:
    failures: list[str] = []
    for container_name, expected_health in REQUIRED_CONTAINERS.items():
        inspected = inspect_container_health(container_name)
        status = inspected["status"]
        health = inspected["health"]
        if status != "running":
            failures.append(f"{container_name}: expected running, got {status}")
            continue
        if health != expected_health:
            failures.append(f"{container_name}: expected health={expected_health}, got {health}")
    if failures:
        raise SmokeFailure("Container health check failed:\n- " + "\n- ".join(failures))


def stream_length(stream_name: str) -> int:
    payload = run(
        [
            "docker",
            "exec",
            "queue-broker",
            "redis-cli",
            "XLEN",
            stream_name,
        ]
    )
    return int(payload or "0")


def anomaly_detector_health() -> dict:
    with urlopen("http://127.0.0.1:18080/health", timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def start_generator() -> None:
    run(["docker", "compose", "up", "-d", "telemetry-generator"], cwd=COMPOSE_DIR)


def wait_for_flow_growth(baseline: dict[str, int], timeout_seconds: int = 45) -> dict[str, int]:
    deadline = time.time() + timeout_seconds
    last_seen = baseline.copy()

    while time.time() < deadline:
        current = {stream_name: stream_length(stream_name) for stream_name in STREAMS}
        last_seen = current
        if all(current[name] > baseline[name] for name in STREAMS):
            return current
        time.sleep(3)

    raise SmokeFailure(
        "Runtime flow did not advance across every required stream within timeout.\n"
        f"Baseline: {baseline}\nCurrent: {last_seen}"
    )


def main() -> int:
    ensure_required_containers()
    baseline = {stream_name: stream_length(stream_name) for stream_name in STREAMS}

    try:
        detector_health_before = anomaly_detector_health()
    except URLError as exc:
        raise SmokeFailure(f"Could not reach anomaly-detector health endpoint: {exc}") from exc

    start_generator()
    advanced = wait_for_flow_growth(baseline)
    detector_health_after = anomaly_detector_health()

    summary = {
        "status": "ok",
        "baseline_stream_lengths": baseline,
        "advanced_stream_lengths": advanced,
        "detector_events_seen_before": detector_health_before.get("events_seen"),
        "detector_events_seen_after": detector_health_after.get("events_seen"),
        "detector_candidate_rate_after": detector_health_after.get("service_candidate_rate"),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SmokeFailure as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
