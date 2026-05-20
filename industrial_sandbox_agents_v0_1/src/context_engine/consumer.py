"""Consume enriched anomaly events through the event bus abstraction."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from typing import Any

import yaml

from src.event_bus import EventEnvelope, RedisEventConsumer

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "event_bus" / "redis_event_bus_v0_1.yaml"


@dataclass(frozen=True)
class EventBusRuntimeSettings:
    backend: str
    stream_prefix: str
    input_stream: str
    output_stream: str
    redis_host: str
    redis_port: int
    redis_db: int
    decode_responses: bool
    consumer_start_id: str
    block_ms: int | None
    report_path: str
    heartbeat_path: str
    docker_container_name: str | None = None


def load_event_bus_settings(
    env_path: Path = DEFAULT_ENV_PATH,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> EventBusRuntimeSettings:
    """Load the active 1C event-bus settings from config and environment."""

    config = _load_yaml(config_path)
    runtime_env = _load_runtime_env(env_path)

    backend = runtime_env.get("EVENT_BUS_BACKEND", str(config.get("backend", "redis")))
    stream_prefix = runtime_env.get("REDIS_STREAM_PREFIX", str(config.get("stream_prefix", "agentic")))
    input_stream = runtime_env.get(
        "EVENT_INPUT_STREAM",
        str(config.get("consume_stream") or config.get("consume_channel", "enriched_anomaly")),
    )
    output_stream = runtime_env.get(
        "EVENT_OUTPUT_STREAM",
        str(config.get("publish_stream") or config.get("publish_channel", "context_slice")),
    )
    docker_container_name = runtime_env.get(
        "REDIS_DOCKER_CONTAINER",
        _coalesce_string(config.get("docker_container_name")),
    )

    redis_host = runtime_env.get("REDIS_HOST")
    if not redis_host:
        redis_host = _resolve_docker_container_ip(docker_container_name)
    if not redis_host:
        redis_host = _coalesce_string(config.get("docker_network_alias")) or "redis"

    redis_port = int(runtime_env.get("REDIS_PORT", config.get("redis_port", 6379)))
    redis_db = int(runtime_env.get("REDIS_DB", config.get("redis_db", 0)))
    decode_responses = _parse_bool(
        runtime_env.get("REDIS_DECODE_RESPONSES"),
        bool(config.get("decode_responses", True)),
    )
    consumer_start_id = runtime_env.get(
        "REDIS_CONSUMER_START_ID",
        str(config.get("consumer_start_id", "0-0")),
    )
    block_ms_raw = runtime_env.get("REDIS_BLOCK_MS")
    if block_ms_raw is None:
        block_ms_raw = config.get("block_ms")
    block_ms = int(block_ms_raw) if block_ms_raw not in (None, "", "none", "null") else None
    report_path = runtime_env.get("CONTEXT_REPORT_PATH", "/app/reports/context_slices.jsonl")
    heartbeat_path = runtime_env.get("CONTEXT_HEARTBEAT_PATH", "/tmp/context_engine_heartbeat")

    return EventBusRuntimeSettings(
        backend=backend,
        stream_prefix=stream_prefix,
        input_stream=input_stream,
        output_stream=output_stream,
        redis_host=redis_host,
        redis_port=redis_port,
        redis_db=redis_db,
        decode_responses=decode_responses,
        consumer_start_id=consumer_start_id,
        block_ms=block_ms,
        report_path=report_path,
        heartbeat_path=heartbeat_path,
        docker_container_name=docker_container_name,
    )


def build_redis_client(settings: EventBusRuntimeSettings) -> Any:
    import redis

    return redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        db=settings.redis_db,
        decode_responses=settings.decode_responses,
    )


def build_event_consumer(
    settings: EventBusRuntimeSettings | None = None,
    redis_client: Any | None = None,
) -> RedisEventConsumer:
    effective_settings = settings or load_event_bus_settings()
    effective_client = redis_client or build_redis_client(effective_settings)
    return RedisEventConsumer(
        effective_client,
        stream_prefix=effective_settings.stream_prefix,
        default_topic=effective_settings.input_stream,
        start_id=effective_settings.consumer_start_id,
        block_ms=effective_settings.block_ms,
    )


def consume_enriched_anomaly_events(
    count: int = 1,
    topic: str | None = None,
    settings: EventBusRuntimeSettings | None = None,
    redis_client: Any | None = None,
) -> list[EventEnvelope]:
    effective_settings = settings or load_event_bus_settings()
    consumer = build_event_consumer(settings=effective_settings, redis_client=redis_client)
    effective_topic = topic or effective_settings.input_stream
    return consumer.consume_event(topic=effective_topic, count=count)


def main() -> int:
    settings = load_event_bus_settings()
    messages = consume_enriched_anomaly_events(count=1, settings=settings)
    print(
        "Context consumer ready using "
        f"{settings.backend} at {settings.redis_host}:{settings.redis_port} "
        f"for stream {settings.stream_prefix}:{settings.input_stream}. "
        f"Messages consumed in probe: {len(messages)}."
    )
    return 0


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected mapping in {path}, got {type(data).__name__}.")
    return data


def _load_runtime_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", maxsplit=1)
            values[key.strip()] = value.strip()
    for key, value in os.environ.items():
        values[key] = value
    return values


def _resolve_docker_container_ip(container_name: str | None) -> str | None:
    if not container_name:
        return None
    try:
        raw = subprocess.check_output(["docker", "inspect", container_name], stderr=subprocess.DEVNULL)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    try:
        payload = json.loads(raw)[0]
        networks = payload["NetworkSettings"]["Networks"]
        return next(iter(networks.values()))["IPAddress"]
    except (KeyError, IndexError, StopIteration, TypeError, json.JSONDecodeError):
        return None


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _coalesce_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
