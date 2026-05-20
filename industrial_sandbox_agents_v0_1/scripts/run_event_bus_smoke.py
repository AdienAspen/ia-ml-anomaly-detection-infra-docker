"""Smoke entrypoint for the event bus abstraction."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.event_bus import EventEnvelope, RedisEventConsumer, RedisEventPublisher
from src.event_bus.testing import FakeRedisStreams, build_sample_enriched_anomaly_event


def main() -> int:
    fake_redis = FakeRedisStreams()
    publisher = RedisEventPublisher(fake_redis, stream_prefix="observability")
    consumer = RedisEventConsumer(fake_redis, stream_prefix="observability")

    payload = build_sample_enriched_anomaly_event()
    publisher.publish_event(EventEnvelope(topic="enriched_anomaly", payload=payload))
    consumed = consumer.consume_event("enriched_anomaly")

    if len(consumed) != 1:
        return 1
    if consumed[0].payload["event_id"] != payload["event_id"]:
        return 1

    print("Event bus smoke passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
