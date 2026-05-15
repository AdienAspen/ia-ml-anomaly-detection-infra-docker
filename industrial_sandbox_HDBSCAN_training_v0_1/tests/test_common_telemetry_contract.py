from src.common_telemetry import SCHEMA_VERSION, build_common_telemetry_event, validate_common_telemetry_event


def test_common_telemetry_builder_produces_valid_payload() -> None:
    event = build_common_telemetry_event(
        sequence_number=0,
        service_name="payments-api",
        metric_name="latency_p95",
        metric_value=250.0,
        unit="milliseconds",
        source="synthetic_generator",
        scenario_tag="S4_INTERSERVICE_CHAIN",
        chaos_suitability="suitable_with_limits",
        metadata={"phase": "propagating"},
    )

    payload = event.to_dict()
    assert payload["schema_version"] == SCHEMA_VERSION
    assert validate_common_telemetry_event(payload) == []


def test_common_telemetry_validator_rejects_invalid_service() -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "event_id": "evt-1",
        "timestamp": "2026-05-09T20:00:00+00:00",
        "sequence_number": 1,
        "service_name": "unknown-service",
        "metric_name": "latency_p95",
        "metric_value": 200.0,
        "unit": "milliseconds",
        "source": "synthetic_generator",
        "is_training_only_field": False,
        "metadata": {},
    }

    errors = validate_common_telemetry_event(payload)
    assert errors
    assert "invalid service_name" in errors
