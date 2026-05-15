import json
from pathlib import Path

from src.score_propagation_signatures import OUTPUT_PATH, build_propagation_signatures, main


def test_propagation_signature_contract_exists() -> None:
    path = Path("contracts/propagation_signature_v0_1.schema.json")
    assert path.exists()


def test_propagation_signature_builder_emits_defensive_fields_only() -> None:
    signatures = build_propagation_signatures()
    assert signatures
    sample = signatures[0]
    assert sample["schema_version"] == "propagation_signature_v0_1"
    assert "services_chain_observed" in sample
    assert "lag_pattern_seconds_ci" in sample
    assert "lag_ci_metadata" in sample
    assert sample["lag_ci_metadata"]["lag_ci_method"] == "observed_percentiles_p10_p50_p90"
    assert sample["lag_ci_metadata"]["minimum_windows_for_precision"] == 30
    assert sample["lag_ci_metadata"]["precision"] in {"precise", "imprecise"}
    serialized = json.dumps(sample)
    assert "chaos_" not in serialized
    assert "replay" not in serialized


def test_propagation_signature_main_exports_artifact() -> None:
    assert main() == 0
    assert Path(OUTPUT_PATH).exists()
