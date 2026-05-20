import unittest

from src.context_engine.consumer import (
    EventBusRuntimeSettings,
    consume_enriched_anomaly_events,
)
from src.event_bus import EventEnvelope, RedisEventPublisher
from src.event_bus.testing import FakeRedisStreams, build_sample_enriched_anomaly_event


class ContextConsumerTests(unittest.TestCase):
    def test_consumer_reads_from_enriched_event_bus(self) -> None:
        fake_redis = FakeRedisStreams()
        settings = EventBusRuntimeSettings(
            backend="redis",
            stream_prefix="agentic",
            input_stream="enriched_anomaly",
            output_stream="context_slice",
            redis_host="unused",
            redis_port=6379,
            redis_db=0,
            decode_responses=True,
            consumer_start_id="0-0",
            block_ms=None,
            report_path="/tmp/context_slices.jsonl",
            heartbeat_path="/tmp/context_engine_heartbeat",
            docker_container_name=None,
        )
        publisher = RedisEventPublisher(fake_redis, stream_prefix=settings.stream_prefix)
        publisher.publish_event(
            EventEnvelope(
                topic=settings.input_stream,
                payload=build_sample_enriched_anomaly_event("evt-consumer-001"),
            )
        )

        messages = consume_enriched_anomaly_events(
            count=1,
            settings=settings,
            redis_client=fake_redis,
        )

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].payload["event_id"], "evt-consumer-001")
        self.assertEqual(messages[0].topic, "enriched_anomaly")
