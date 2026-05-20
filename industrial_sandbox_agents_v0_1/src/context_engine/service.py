"""Runtime service loop for the containerized 1C context engine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.context_engine.builder import build_context_slice
from src.context_engine.consumer import (
    EventBusRuntimeSettings,
    build_event_consumer,
    build_redis_client,
    load_event_bus_settings,
)
from src.context_engine.contracts import validate_context_slice
from src.event_bus import EventEnvelope, RedisEventPublisher


def build_context_publisher(
    settings: EventBusRuntimeSettings,
    redis_client: Any | None = None,
) -> RedisEventPublisher:
    client = redis_client or build_redis_client(settings)
    return RedisEventPublisher(
        client,
        stream_prefix=settings.stream_prefix,
        validator=validate_context_slice,
    )


def run_context_service_iteration(
    settings: EventBusRuntimeSettings | None = None,
    redis_client: Any | None = None,
    count: int = 1,
) -> int:
    effective_settings = settings or load_event_bus_settings()
    client = redis_client or build_redis_client(effective_settings)
    consumer = build_event_consumer(settings=effective_settings, redis_client=client)
    publisher = build_context_publisher(effective_settings, redis_client=client)

    messages = consumer.consume_event(count=count)
    processed = 0
    for message in messages:
        context_slice = build_context_slice(message.payload)
        publisher.publish_event(
            EventEnvelope(
                topic=effective_settings.output_stream,
                payload=context_slice,
            )
        )
        _append_jsonl(Path(effective_settings.report_path), context_slice)
        processed += 1

    _touch_heartbeat(Path(effective_settings.heartbeat_path))
    return processed


def run_context_engine_service(
    settings: EventBusRuntimeSettings | None = None,
    redis_client: Any | None = None,
) -> int:
    effective_settings = settings or load_event_bus_settings()
    processed_total = 0
    while True:
        processed_total += run_context_service_iteration(
            settings=effective_settings,
            redis_client=redis_client,
            count=1,
        )
        if processed_total and processed_total % 10 == 0:
            print(f"Processed {processed_total} enriched anomaly events into context slices.")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True))
        handle.write("\n")


def _touch_heartbeat(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
