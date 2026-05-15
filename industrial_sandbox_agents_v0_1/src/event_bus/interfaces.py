"""Event bus interfaces.

The rest of the agentic layer should talk to these interfaces rather than directly to Redis.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EventEnvelope:
    topic: str
    payload: dict


class EventPublisher(Protocol):
    def publish_event(self, event: EventEnvelope) -> None:
        ...


class EventConsumer(Protocol):
    def consume_event(self) -> EventEnvelope:
        ...
