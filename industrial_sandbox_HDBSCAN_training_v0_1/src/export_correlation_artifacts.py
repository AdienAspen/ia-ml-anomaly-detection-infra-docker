"""Export correlation engine artifacts into a shared package consumable by block 1C."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import pickle
import shutil
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PROJECT_ROOT.parent
SHARED_ROOT = REPO_ROOT / "shared_artifacts" / "correlation_engine"
SOURCE_PRODUCTION_ID = "hdbscan_production_v1"
SOURCE_CHECKPOINT_ID = "post_filter_operating_point_v_02"
POLICY_FILENAME = "hdbscan_correlation_policy_v1.json"
PACKAGE_ALIAS_FILENAME = "active_correlation_engine.json"
FEATURE_CONTRACT_FILENAME = "feature_contract.json"
EVENT_CONTRACT_FILENAME = "enriched_anomaly_event_contract_v0_1.json"
MANIFEST_FILENAME = "manifest.json"
PROMOTION_NOTES_FILENAME = "promotion_notes.md"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n")

def _load_model_payload(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        payload = pickle.load(handle)
    if not isinstance(payload, dict):
        raise TypeError(f"Expected dict model payload, got {type(payload)!r}")
    return payload


def build_feature_contract(model_payload: dict[str, Any]) -> dict[str, Any]:
    feature_keys = list(model_payload.get("feature_keys", []))
    excluded = list(model_payload.get("excluded_feature_columns", []))
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "contract_name": "hdbscan_temporal_feature_contract_v_02",
        "contract_type": "feature_contract",
        "version": "1.0.0",
        "source_alignment": {
            "source_repo": str(PROJECT_ROOT),
            "source_contract": str(PROJECT_ROOT / "contracts" / "propagation_signature_v0_1.schema.json"),
            "window_contract": str(PROJECT_ROOT / "data" / "processed" / "temporal_windows_v_02.json"),
        },
        "model_name": "HDBSCANTemporal",
        "frozen_feature_columns": feature_keys,
        "excluded_columns": excluded,
        "post_filter_columns": ["iforest_score_mean"],
        "window_context_columns": [
            "window_id",
            "start_timestamp",
            "end_timestamp",
            "scenario_tag",
            "expected_propagation",
            "window_data_quality_score",
        ],
        "features": {
            key: {
                "dtype": "float64",
                "model_role": "input",
            }
            for key in feature_keys
        },
        "notes": [
            "iforest scores are not direct HDBSCAN inputs in v_02; they are consumed as post-filter confidence signals.",
            "training-only metadata remains excluded from the HDBSCAN feature vector.",
            "This package intentionally preserves the 40-feature operating point selected before the final stability-only experiments.",
        ],
    }


def build_event_contract() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "contract_name": "enriched_anomaly_event_v0_1",
        "contract_type": "runtime_event_contract",
        "version": "1.0.0",
        "producer": "correlation_engine_hdbscan_v_02",
        "intended_consumer": "block_1c_agentic_layer",
        "allowed_fields": [
            "iforest_scores",
            "propagation_signature_id",
            "window_data_quality_score",
            "severity_preliminary",
            "evidence_refs",
        ],
        "forbidden_fields": [
            "chaos_template",
            "chaos_execution_plan",
            "replay_metadata",
        ],
        "notes": [
            "This contract is runtime-oriented and intentionally excludes any direct chaos execution payload.",
            "1C may enrich or route this event, but it must preserve the defensive boundary established in 1B.2.",
        ],
    }


def build_runtime_policy(
    production_manifest: dict[str, Any],
    validation_summary: dict[str, Any],
) -> dict[str, Any]:
    metrics = production_manifest.get("metrics", {})
    return {
        "schema_version": "hdbscan_correlation_policy_v1",
        "policy_name": "hdbscan_production_v1",
        "runtime_mode": "shadow_preprod_candidate",
        "source_checkpoint": SOURCE_CHECKPOINT_ID,
        "source_production_id": SOURCE_PRODUCTION_ID,
        "model_artifact": "model.pkl",
        "feature_contract": FEATURE_CONTRACT_FILENAME,
        "event_contract": EVENT_CONTRACT_FILENAME,
        "post_filter": {
            "enabled": True,
            "score_field": "iforest_score_mean",
            "requested_threshold": metrics.get("post_filter_requested_threshold"),
            "effective_threshold": metrics.get("post_filter_effective_threshold"),
            "aggregation": metrics.get("post_filter_aggregation"),
            "kept_cluster_ids": metrics.get("post_filter_kept_cluster_ids", []),
        },
        "selected_metrics": {
            "precision": validation_summary.get("precision"),
            "recall": validation_summary.get("propagation_detection_rate"),
            "false_propagation_rate": validation_summary.get("false_propagation_rate"),
            "noise_rejection_rate": validation_summary.get("noise_rejection_rate"),
            "propagation_order_accuracy": validation_summary.get("propagation_order_accuracy"),
            "cluster_stability": validation_summary.get("cluster_stability"),
        },
        "consumer_notes": [
            "Load this policy as a shadow/pre-production candidate for block 1C.",
            "Do not reinterpret the post-filter threshold without an explicit promotion decision.",
            "The selected candidate favors recall over stability based on the agreed project policy.",
        ],
    }


def build_manifest(
    package_dir: Path,
    production_manifest: dict[str, Any],
    validation_summary: dict[str, Any],
    feature_contract: dict[str, Any],
) -> dict[str, Any]:
    metrics = production_manifest.get("metrics", {})
    copied_files = sorted(
        p.name for p in package_dir.iterdir() if p.is_file()
    )
    return {
        "model_name": "hdbscan_temporal",
        "model_version": SOURCE_PRODUCTION_ID,
        "artifact_type": "pickle",
        "feature_contract": feature_contract.get("contract_name"),
        "training_dataset": str(PROJECT_ROOT / "data" / "processed" / "temporal_windows_v_02.json"),
        "validation_dataset": str(PROJECT_ROOT / "data" / "processed" / "hdbscan_temporal_feature_view_v_02.json"),
        "runtime_policy": POLICY_FILENAME,
        "metrics": {
            "training_metrics_path": "training_summary.json",
            "validation_metrics_path": "validation_metrics.json",
            "precision": validation_summary.get("precision"),
            "recall": validation_summary.get("propagation_detection_rate"),
            "false_propagation_rate": validation_summary.get("false_propagation_rate"),
            "noise_rejection_rate": validation_summary.get("noise_rejection_rate"),
            "propagation_order_accuracy": validation_summary.get("propagation_order_accuracy"),
            "cluster_stability": validation_summary.get("cluster_stability"),
        },
        "created_at": _utc_now(),
        "package_metadata": {
            "source_dir": str(PROJECT_ROOT / "artifacts" / "production" / SOURCE_PRODUCTION_ID),
            "target_dir": str(package_dir),
            "source_checkpoint": SOURCE_CHECKPOINT_ID,
            "copied_files": copied_files,
            "selected_feature_count": metrics.get("feature_count"),
            "post_filter_policy": {
                "threshold": metrics.get("post_filter_effective_threshold"),
                "aggregation": metrics.get("post_filter_aggregation"),
            },
        },
    }


def build_promotion_notes(validation_summary: dict[str, Any]) -> str:
    return """# Correlation Engine Promotion Notes

- block 1B.2 validates and exports; block 1C consumes this package as a pre-production/shadow candidate.
- selected candidate: `hdbscan_production_v1`
- selected source checkpoint: `post_filter_operating_point_v_02`
- rationale: this is the agreed operating point before the final stability-only experiments, preserving high recall.
- post-filter policy: `iforest_score_mean`, threshold `0.30`, aggregation `percentile_25`
- recall: `{recall}`
- precision: `{precision}`
- noise rejection: `{noise}`
- propagation order accuracy: `{order}`
- cluster stability: `{stability}`
- 1C should treat this package as read-only and load it through the active alias under `shared_artifacts/correlation_engine`.
- 1C must not append `chaos_template`, `chaos_execution_plan`, or `replay_metadata` to the exported runtime event.
""".format(
        recall=validation_summary.get("propagation_detection_rate"),
        precision=validation_summary.get("precision"),
        noise=validation_summary.get("noise_rejection_rate"),
        order=validation_summary.get("propagation_order_accuracy"),
        stability=validation_summary.get("cluster_stability"),
    )


def export_package(shared_root: Path = SHARED_ROOT) -> Path:
    source_root = PROJECT_ROOT / "artifacts" / "production" / SOURCE_PRODUCTION_ID
    package_dir = shared_root / SOURCE_PRODUCTION_ID
    package_dir.mkdir(parents=True, exist_ok=True)

    production_manifest = _load_json(source_root / "production_manifest.json")
    training_manifest = _load_json(source_root / "artifacts" / "correlation_engine_manifest_v_02.json")
    training_summary = _load_json(source_root / "artifacts" / "hdbscan_temporal_training_summary_v_02.json")
    validation_summary = _load_json(source_root / "artifacts" / "correlation_engine_validation_summary_v_02.json")
    model_source = source_root / "artifacts" / "hdbscan_temporal_v_02" / "hdbscan_temporal_model_v_02.pkl"
    model_payload = _load_model_payload(model_source)
    feature_contract = build_feature_contract(model_payload)
    event_contract = build_event_contract()
    runtime_policy = build_runtime_policy(production_manifest, validation_summary)

    copy_map = {
        source_root / "production_manifest.json": package_dir / "production_manifest.json",
        source_root / "artifacts" / "correlation_engine_manifest_v_02.json": package_dir / "training_manifest.json",
        source_root / "artifacts" / "hdbscan_temporal_training_summary_v_02.json": package_dir / "training_summary.json",
        source_root / "artifacts" / "correlation_engine_validation_summary_v_02.json": package_dir / "validation_metrics.json",
        source_root / "configs" / "hdbscan_config.yaml": package_dir / "hdbscan_config.yaml",
        source_root / "configs" / "topology_graph_v_02.json": package_dir / "topology_graph_v_02.json",
        source_root / "reports" / "correlation_engine_validation_report_v_02.md": package_dir / "validation_report.md",
        model_source: package_dir / "model.pkl",
    }
    for source, target in copy_map.items():
        shutil.copy2(source, target)

    _write_json(package_dir / FEATURE_CONTRACT_FILENAME, feature_contract)
    _write_json(package_dir / EVENT_CONTRACT_FILENAME, event_contract)
    _write_json(package_dir / POLICY_FILENAME, runtime_policy)
    _write_json(
        package_dir / PACKAGE_ALIAS_FILENAME,
        {
            "schema_version": "correlation_engine_alias_v1",
            "active_policy_path": POLICY_FILENAME,
            "updated_at": _utc_now(),
        },
    )
    (package_dir / PROMOTION_NOTES_FILENAME).write_text(build_promotion_notes(validation_summary))
    manifest = build_manifest(package_dir, production_manifest, validation_summary, feature_contract)
    _write_json(package_dir / MANIFEST_FILENAME, manifest)
    _write_json(
        shared_root / PACKAGE_ALIAS_FILENAME,
        {
            "schema_version": "correlation_engine_alias_v1",
            "active_policy_path": f"{SOURCE_PRODUCTION_ID}/{POLICY_FILENAME}",
            "updated_at": _utc_now(),
        },
    )
    return package_dir


def main() -> int:
    package_dir = export_package()
    print(f"Exported correlation engine package to {package_dir}")
    return 0
