"""Redis-backed event bus adapter scaffold."""

from src.event_bus.interfaces import EventConsumer, EventEnvelope, EventPublisher


class RedisEventPublisher(EventPublisher):
    def publish_event(self, event: EventEnvelope) -> None:
        raise NotImplementedError("Redis publisher scaffold only.")


class RedisEventConsumer(EventConsumer):
    def consume_event(self) -> EventEnvelope:
        raise NotImplementedError("Redis consumer scaffold only.")
