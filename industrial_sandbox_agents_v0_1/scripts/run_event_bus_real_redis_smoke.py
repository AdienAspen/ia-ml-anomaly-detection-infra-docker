"""Smoke the event bus against the real Redis runtime."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.context_engine.consumer import build_redis_client, load_event_bus_settings
from src.event_bus import EventEnvelope, RedisEventConsumer, RedisEventPublisher
from src.event_bus.testing import build_sample_enriched_anomaly_event


def main() -> int:
    settings = load_event_bus_settings()
    client = build_redis_client(settings)
    topic = "smoke_enriched_anomaly"
    payload = build_sample_enriched_anomaly_event("evt-real-smoke-001")

    publisher = RedisEventPublisher(client, stream_prefix=settings.stream_prefix)
    consumer = RedisEventConsumer(client, stream_prefix=settings.stream_prefix)

    receipt = publisher.publish_event(EventEnvelope(topic=topic, payload=payload))
    messages = consumer.consume_event(topic=topic, count=1)

    if len(messages) != 1 or messages[0].payload["event_id"] != payload["event_id"]:
        return 1

    print(
        "Real Redis smoke passed on "
        f"{settings.redis_host}:{settings.redis_port} with message {receipt.message_id}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
