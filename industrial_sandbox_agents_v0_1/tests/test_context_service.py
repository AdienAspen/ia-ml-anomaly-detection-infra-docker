import tempfile
import unittest

from src.context_engine.consumer import EventBusRuntimeSettings
from src.context_engine.contracts import validate_context_slice
from src.context_engine.service import run_context_service_iteration
from src.event_bus import EventEnvelope, RedisEventConsumer, RedisEventPublisher
from src.event_bus.testing import FakeRedisStreams, build_sample_enriched_anomaly_event


class ContextServiceTests(unittest.TestCase):
    def test_service_iteration_consumes_and_publishes_context_slice(self) -> None:
        fake_redis = FakeRedisStreams()
        with tempfile.TemporaryDirectory() as tmpdir:
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
                report_path=f"{tmpdir}/context_slices.jsonl",
                heartbeat_path=f"{tmpdir}/heartbeat",
                docker_container_name=None,
            )
            input_publisher = RedisEventPublisher(fake_redis, stream_prefix=settings.stream_prefix)
            input_publisher.publish_event(
                EventEnvelope(
                    topic=settings.input_stream,
                    payload=build_sample_enriched_anomaly_event("evt-service-001"),
                )
            )

            processed = run_context_service_iteration(settings=settings, redis_client=fake_redis, count=1)

            output_consumer = RedisEventConsumer(
                fake_redis,
                stream_prefix=settings.stream_prefix,
                default_topic=settings.output_stream,
                start_id="0-0",
                block_ms=None,
                validator=validate_context_slice,
            )
            output_messages = output_consumer.consume_event()

            self.assertEqual(processed, 1)
            self.assertEqual(len(output_messages), 1)
            self.assertEqual(output_messages[0].payload["schema_version"], "context_slice_v0_1")


if __name__ == "__main__":
    unittest.main()
