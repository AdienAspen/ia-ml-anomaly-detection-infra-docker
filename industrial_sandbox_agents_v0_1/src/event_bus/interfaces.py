"""Event bus interfaces for the Block 1C agentic layer.

The rest of the agentic layer should talk to these interfaces rather than
directly to Redis commands.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class EventEnvelope:
    topic: str
    payload: dict[str, Any]
    message_id: str | None = None


@dataclass(frozen=True)
class PublishedEventReceipt:
    topic: str
    message_id: str


class EventPublisher(Protocol):
    def publish_event(self, event: EventEnvelope) -> PublishedEventReceipt:
        """Publish a validated event through the active bus implementation."""


class EventConsumer(Protocol):
    def consume_event(self, topic: str | None = None, count: int = 1) -> list[EventEnvelope]:
        """Consume one or more events from the active bus implementation."""
