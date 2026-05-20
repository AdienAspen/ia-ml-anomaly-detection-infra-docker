from src.build_temporal_windows import build_temporal_windows
from src.feature_calculator_v_02 import bfs_distance, build_hdbscan_feature_rows_v_02, get_upstream, load_topology, validate_feature_row_v_02
from src.scenario_engine import build_scenario_events


def test_topology_helpers_v_02_load_and_resolve_paths() -> None:
    topology = load_topology()
    assert topology["criticality"]["payments"] == 1
    assert bfs_distance(topology, "payments", "checkout") == 2
    assert bfs_distance(topology, "payments", "orders") == 2
    assert get_upstream(topology, "orders") == ["checkout", "payments", "redis"]


def test_feature_calculator_v_02_builds_rows_with_topological_and_temporal_features() -> None:
    events = build_scenario_events("S4_INTERSERVICE_CHAIN", seed=88, steps=8)
    windows = build_temporal_windows(events)
    rows = build_hdbscan_feature_rows_v_02(windows)
    assert rows
    sample = rows[0]
    assert sample["schema_version"] == "hdbscan_temporal_feature_view_v_02"
    assert "cache_health_score" in sample
    assert "degradation_intensity_payments" in sample
    assert "traffic_pressure_orders" in sample
    assert "flow_efficiency_checkout" in sample
    assert "stress_rate_payments" in sample
    assert "propagation_velocity_checkout" in sample
    assert "service_criticality_redis" in sample
    assert "topological_distance_orders" in sample
    assert "upstream_health_checkout" in sample
    assert "recovery_memory" in sample
    assert "lag_payments_to_redis" not in sample
    assert "lag_redis_to_checkout" not in sample
    assert "service_degradation_order_encoded" not in sample
    assert "window_data_quality_score" not in sample
    assert validate_feature_row_v_02(sample) == []
