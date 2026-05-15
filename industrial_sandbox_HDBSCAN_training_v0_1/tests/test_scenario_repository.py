from src.scenario_repository import load_chaos_eligible_scenarios, load_chaos_template_placeholders, load_training_scenarios, load_validation_scenarios, summarize_repository


def test_scenario_repository_partitions_exist() -> None:
    summary = summarize_repository()
    assert summary["training_count"] >= 4
    assert summary["validation_count"] >= 4
    assert summary["chaos_eligible_count"] >= 2
    assert summary["placeholder_template_count"] >= 1


def test_training_and_validation_scenarios_are_explicit() -> None:
    training = load_training_scenarios()
    validation = load_validation_scenarios()
    assert all("profile_id" in entry for entry in training)
    assert all("profile_id" in entry for entry in validation)
    assert any(entry["scenario_name"] == "S4_INTERSERVICE_CHAIN" for entry in training)
    assert any(entry["scenario_name"] == "S3_REDIS_TO_MULTISERVICE_PROPAGATION" for entry in validation)


def test_chaos_readiness_placeholders_are_nonempty() -> None:
    eligible = load_chaos_eligible_scenarios()
    placeholders = load_chaos_template_placeholders()
    assert eligible
    assert placeholders
