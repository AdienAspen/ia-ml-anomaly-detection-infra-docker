"""Redis-first event bus adapters with Kafka-ready boundaries."""

from __future__ import annotations

import json
from typing import Any, Callable, Protocol

from src.event_bus.interfaces import EventConsumer, EventEnvelope, EventPublisher, PublishedEventReceipt
from src.event_bus.schemas import validate_enriched_anomaly_event

PayloadValidator = Callable[[dict[str, Any]], dict[str, Any]]


class SupportsRedisStreamWrite(Protocol):
    def xadd(self, name: str, fields: dict[str, str]) -> str:
        """Append a message to a Redis stream."""


class SupportsRedisStreamRead(Protocol):
    def xread(
        self,
        streams: dict[str, str],
        count: int = 1,
        block: int | None = None,
    ) -> list[Any]:
        """Read messages from one or more Redis streams."""


class RedisEventPublisher(EventPublisher):
    """Publish schema-validated payloads to Redis Streams."""

    def __init__(
        self,
        redis_client: SupportsRedisStreamWrite,
        stream_prefix: str = "events",
        validator: PayloadValidator | None = validate_enriched_anomaly_event,
    ) -> None:
        self._redis_client = redis_client
        self._stream_prefix = stream_prefix
        self._validator = validator

    def publish_event(self, event: EventEnvelope) -> PublishedEventReceipt:
        topic = _normalize_topic(event.topic)
        if self._validator is not None:
            self._validator(event.payload)
        stream_name = _build_stream_name(self._stream_prefix, topic)
        payload = {"payload": json.dumps(event.payload, sort_keys=True)}
        message_id = self._redis_client.xadd(stream_name, payload)
        return PublishedEventReceipt(topic=topic, message_id=str(message_id))


class RedisEventConsumer(EventConsumer):
    """Consume schema-validated payloads from Redis Streams."""

    def __init__(
        self,
        redis_client: SupportsRedisStreamRead,
        stream_prefix: str = "events",
        default_topic: str | None = None,
        start_id: str = "0-0",
        block_ms: int | None = None,
        validator: PayloadValidator | None = validate_enriched_anomaly_event,
    ) -> None:
        self._redis_client = redis_client
        self._stream_prefix = stream_prefix
        self._default_topic = default_topic
        self._default_start_id = start_id
        self._block_ms = block_ms
        self._validator = validator
        self._last_ids: dict[str, str] = {}

    def consume_event(self, topic: str | None = None, count: int = 1) -> list[EventEnvelope]:
        effective_topic = _normalize_topic(topic or self._default_topic)
        if count <= 0:
            raise ValueError("count must be a positive integer.")

        stream_name = _build_stream_name(self._stream_prefix, effective_topic)
        last_id = self._last_ids.get(effective_topic, self._default_start_id)
        response = self._redis_client.xread(
            streams={stream_name: last_id},
            count=count,
            block=self._block_ms,
        )

        envelopes: list[EventEnvelope] = []
        for _, messages in response:
            for message_id, fields in messages:
                payload = _extract_payload(fields)
                if self._validator is not None:
                    self._validator(payload)
                envelopes.append(
                    EventEnvelope(
                        topic=effective_topic,
                        payload=payload,
                        message_id=str(message_id),
                    )
                )
                self._last_ids[effective_topic] = str(message_id)

        return envelopes


def _normalize_topic(topic: str | None) -> str:
    if topic is None or not isinstance(topic, str) or not topic.strip():
        raise ValueError("topic must be a non-empty string.")
    return topic.strip()


def _build_stream_name(prefix: str, topic: str) -> str:
    return f"{prefix}:{topic}"


def _extract_payload(fields: dict[str, Any]) -> dict[str, Any]:
    if "payload" not in fields:
        raise ValueError("Redis message is missing payload field.")

    raw_payload = fields["payload"]
    if isinstance(raw_payload, bytes):
        raw_payload = raw_payload.decode("utf-8")

    payload = json.loads(raw_payload)
    if not isinstance(payload, dict):
        raise ValueError("Decoded payload must be a dictionary.")

    return payload
