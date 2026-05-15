from src.build_temporal_windows import build_temporal_windows, load_windowing_policy, main
from src.common_telemetry import build_common_telemetry_event
from src.scenario_engine import build_scenario_events


def test_temporal_window_builder_scaffold_returns_success() -> None:
    assert main() == 0


def test_windowing_policy_loader_reads_core_values() -> None:
    policy = load_windowing_policy()
    assert policy.window_length_seconds == 120
    assert policy.stride_seconds == 60
    assert policy.max_missing_ratio == 0.20
    assert policy.late_discard_ratio_threshold == 0.05
    assert policy.late_event_policy_mode == "timestamp_tolerance_reassign_previous_window"


def test_temporal_window_builder_builds_windows_with_quality_metadata() -> None:
    events = build_scenario_events("S4_INTERSERVICE_CHAIN", seed=77, steps=8)
    windows = build_temporal_windows(events)
    assert windows
    sample = windows[0]
    assert sample["schema_version"] == "temporal_window_v0_1"
    assert "window_data_quality_score" in sample
    assert "training_metadata" in sample
    assert "payments-api__latency_p95" in sample["features"]
    assert "feature_inputs" in sample["training_metadata"]


def test_temporal_window_builder_orders_by_timestamp_then_sequence_number() -> None:
    events = [
        build_common_telemetry_event(
            event_id="evt-2",
            timestamp="2026-05-09T20:00:00+00:00",
            sequence_number=2,
            window_id="w0",
            service_name="payments-api",
            metric_name="latency_p95",
            metric_value=220.0,
            unit="milliseconds",
            source="synthetic_generator",
            scenario_tag="S1_LOCAL_ANOMALY_ONLY",
            metadata={},
        ),
        build_common_telemetry_event(
            event_id="evt-1",
            timestamp="2026-05-09T20:00:00+00:00",
            sequence_number=1,
            window_id="w0",
            service_name="payments-api",
            metric_name="error_rate",
            metric_value=0.03,
            unit="ratio",
            source="synthetic_generator",
            scenario_tag="S1_LOCAL_ANOMALY_ONLY",
            metadata={},
        ),
    ]
    windows = build_temporal_windows(events)
    assert windows
    assert windows[0]["training_metadata"]["ordering_strategy"] == "timestamp_then_sequence_number"


def test_temporal_window_builder_tracks_late_event_policy_and_quality_flags() -> None:
    events = [
        build_common_telemetry_event(
            event_id="evt-1",
            timestamp="2026-05-09T20:00:00+00:00",
            sequence_number=0,
            window_id="w0",
            service_name="payments-api",
            metric_name="latency_p95",
            metric_value=200.0,
            unit="milliseconds",
            source="synthetic_generator",
            scenario_tag="S2_SERVICE_TO_REDIS_PROPAGATION",
            metadata={},
        ),
        build_common_telemetry_event(
            event_id="evt-2",
            timestamp="2026-05-09T20:02:05+00:00",
            sequence_number=1,
            window_id="w0",
            service_name="redis",
            metric_name="redis_latency",
            metric_value=12.0,
            unit="milliseconds",
            source="synthetic_generator",
            scenario_tag="S2_SERVICE_TO_REDIS_PROPAGATION",
            metadata={},
        ),
        build_common_telemetry_event(
            event_id="evt-3",
            timestamp="2026-05-09T20:02:20+00:00",
            sequence_number=2,
            window_id="w0",
            service_name="redis",
            metric_name="redis_queue_depth",
            metric_value=48.0,
            unit="items",
            source="synthetic_generator",
            scenario_tag="S2_SERVICE_TO_REDIS_PROPAGATION",
            metadata={},
        ),
    ]
    windows = build_temporal_windows(events)
    assert windows
    metadata = windows[0]["training_metadata"]
    assert metadata["late_events_within_tolerance"] >= 1
    assert metadata["late_discarded_for_window_count"] >= 1
    assert metadata["late_event_policy"]["within_tolerance_action"] == "include_in_current_window"


def test_temporal_window_builder_marks_ordering_broken_when_sequence_regresses() -> None:
    events = [
        build_common_telemetry_event(
            event_id="evt-1",
            timestamp="2026-05-09T20:00:00+00:00",
            sequence_number=10,
            window_id="w0",
            service_name="payments-api",
            metric_name="latency_p95",
            metric_value=210.0,
            unit="milliseconds",
            source="synthetic_generator",
            scenario_tag="S1_LOCAL_ANOMALY_ONLY",
            metadata={},
        ),
        build_common_telemetry_event(
            event_id="evt-2",
            timestamp="2026-05-09T20:00:10+00:00",
            sequence_number=9,
            window_id="w0",
            service_name="payments-api",
            metric_name="error_rate",
            metric_value=0.04,
            unit="ratio",
            source="synthetic_generator",
            scenario_tag="S1_LOCAL_ANOMALY_ONLY",
            metadata={},
        ),
        build_common_telemetry_event(
            event_id="evt-3",
            timestamp="2026-05-09T20:00:15+00:00",
            sequence_number=11,
            window_id="w0",
            service_name="payments-api",
            metric_name="throughput",
            metric_value=160.0,
            unit="requests_per_interval",
            source="synthetic_generator",
            scenario_tag="S1_LOCAL_ANOMALY_ONLY",
            metadata={},
        ),
        build_common_telemetry_event(
            event_id="evt-4",
            timestamp="2026-05-09T20:00:05+00:00",
            sequence_number=20,
            window_id="w0",
            service_name="redis",
            metric_name="redis_latency",
            metric_value=12.0,
            unit="milliseconds",
            source="synthetic_generator",
            scenario_tag="S1_LOCAL_ANOMALY_ONLY",
            metadata={},
        ),
        build_common_telemetry_event(
            event_id="evt-5",
            timestamp="2026-05-09T20:00:06+00:00",
            sequence_number=21,
            window_id="w0",
            service_name="redis",
            metric_name="redis_queue_depth",
            metric_value=48.0,
            unit="items",
            source="synthetic_generator",
            scenario_tag="S1_LOCAL_ANOMALY_ONLY",
            metadata={},
        ),
    ]
    windows = build_temporal_windows(events)
    assert windows
    metadata = windows[0]["training_metadata"]
    assert metadata["ordering_broken"] is True
    assert metadata["ordering_violation_services"] == ["payments-api"]
    assert metadata["accepted_for_training"] is False
