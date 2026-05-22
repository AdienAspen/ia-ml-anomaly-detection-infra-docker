import unittest

from src.event_bus import EventEnvelope, RedisEventConsumer, RedisEventPublisher
from src.event_bus.testing import FakeRedisStreams, build_sample_enriched_anomaly_event


class RedisEventBusAbstractionTests(unittest.TestCase):
    def test_publish_consume_roundtrip(self) -> None:
        fake_redis = FakeRedisStreams()
        publisher = RedisEventPublisher(fake_redis, stream_prefix="observability")
        consumer = RedisEventConsumer(fake_redis, stream_prefix="observability")

        payload = build_sample_enriched_anomaly_event()
        receipt = publisher.publish_event(EventEnvelope(topic="enriched_anomaly", payload=payload))
        consumed = consumer.consume_event("enriched_anomaly")

        self.assertEqual(receipt.topic, "enriched_anomaly")
        self.assertEqual(receipt.message_id, "1-0")
        self.assertEqual(len(consumed), 1)
        self.assertEqual(consumed[0].message_id, "1-0")
        self.assertEqual(consumed[0].payload["event_id"], payload["event_id"])

    def test_consumer_tracks_offsets_between_reads(self) -> None:
        fake_redis = FakeRedisStreams()
        publisher = RedisEventPublisher(fake_redis)
        consumer = RedisEventConsumer(fake_redis)

        first_event = build_sample_enriched_anomaly_event("evt-001")
        second_event = build_sample_enriched_anomaly_event("evt-002")

        publisher.publish_event(EventEnvelope(topic="enriched_anomaly", payload=first_event))
        publisher.publish_event(EventEnvelope(topic="enriched_anomaly", payload=second_event))

        first_batch = consumer.consume_event("enriched_anomaly", count=1)
        second_batch = consumer.consume_event("enriched_anomaly", count=1)

        self.assertEqual([item.payload["event_id"] for item in first_batch], ["evt-001"])
        self.assertEqual([item.payload["event_id"] for item in second_batch], ["evt-002"])


    def test_publish_consume_roundtrip_without_prefix(self) -> None:
        fake_redis = FakeRedisStreams()
        publisher = RedisEventPublisher(fake_redis, stream_prefix="")
        consumer = RedisEventConsumer(fake_redis, stream_prefix="")

        payload = build_sample_enriched_anomaly_event("evt-no-prefix")
        receipt = publisher.publish_event(EventEnvelope(topic="enriched.correlation.stream", payload=payload))
        consumed = consumer.consume_event("enriched.correlation.stream")

        self.assertEqual(receipt.topic, "enriched.correlation.stream")
        self.assertEqual(len(consumed), 1)
        self.assertEqual(consumed[0].payload["event_id"], "evt-no-prefix")

if __name__ == "__main__":
    unittest.main()
