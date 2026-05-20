from __future__ import annotations

import json
from pathlib import Path

from src.export_correlation_artifacts import POLICY_FILENAME, SOURCE_CHECKPOINT_ID, SOURCE_PRODUCTION_ID, export_package


def test_export_package_builds_shared_runtime_bundle(tmp_path: Path) -> None:
    shared_root = tmp_path / "shared_artifacts" / "correlation_engine"
    package_dir = export_package(shared_root)

    assert package_dir == shared_root / SOURCE_PRODUCTION_ID
    assert (package_dir / "model.pkl").exists()
    assert (package_dir / "feature_contract.json").exists()
    assert (package_dir / POLICY_FILENAME).exists()
    assert (package_dir / "validation_metrics.json").exists()
    assert (shared_root / "active_correlation_engine.json").exists()

    policy = json.loads((package_dir / POLICY_FILENAME).read_text())
    assert policy["source_checkpoint"] == SOURCE_CHECKPOINT_ID
    assert policy["post_filter"]["effective_threshold"] == 0.3
    assert policy["post_filter"]["aggregation"] == "percentile_25"

    manifest = json.loads((package_dir / "manifest.json").read_text())
    assert manifest["model_version"] == SOURCE_PRODUCTION_ID
    assert manifest["metrics"]["recall"] == 0.847619

    top_alias = json.loads((shared_root / "active_correlation_engine.json").read_text())
    assert top_alias["active_policy_path"] == f"{SOURCE_PRODUCTION_ID}/{POLICY_FILENAME}"
