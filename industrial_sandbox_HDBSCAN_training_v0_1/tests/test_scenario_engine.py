from src.common_telemetry import validate_common_telemetry_event
from src.scenario_engine import SCENARIO_NAMES, build_scenario_events, scenario_summary


def test_scenario_catalog_covers_expected_names() -> None:
    assert len(SCENARIO_NAMES) == 9
    assert "S0_NORMAL_BASELINE" in SCENARIO_NAMES
    assert "S8_HIGH_DENSITY_UNCORRELATED_NOISE" in SCENARIO_NAMES


def test_scenario_engine_generates_valid_events() -> None:
    events = build_scenario_events("S4_INTERSERVICE_CHAIN", seed=21, steps=6)
    assert events
    assert all(validate_common_telemetry_event(event.to_dict()) == [] for event in events)

    summary = scenario_summary(events)
    assert summary["scenario_tag"] == "S4_INTERSERVICE_CHAIN"
    assert summary["invalid_events"] == 0
    assert set(summary["services_covered"]) == {"payments-api", "orders-api", "checkout-api", "redis"}


def test_negative_scenario_still_produces_common_contract_events() -> None:
    events = build_scenario_events("S6_NOISE_FALSE_POSITIVE", seed=9, steps=5)
    assert events
    assert all(event.scenario_tag == "S6_NOISE_FALSE_POSITIVE" for event in events)
    assert all(validate_common_telemetry_event(event.to_dict()) == [] for event in events)
