"""Train the temporal HDBSCAN correlation model on runtime-reproducible features only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import dist
from pathlib import Path
from typing import Any
import importlib.util
import json
import pickle

from src.build_hdbscan_temporal_feature_view_v_02 import build_hdbscan_temporal_feature_view_v_02, export_hdbscan_temporal_feature_view_v_02
from src.build_temporal_windows import build_temporal_windows, export_temporal_windows
from src.scenario_engine import build_scenario_events
from src.window_scaling_v_02 import build_training_profiles_v_02, build_windowing_policy_v_02

PROJECT_ROOT = Path(__file__).resolve().parents[1]
WINDOWS_PATH = PROJECT_ROOT / "data" / "processed" / "temporal_windows_v_02.json"
FEATURE_VIEW_PATH = PROJECT_ROOT / "data" / "processed" / "hdbscan_temporal_feature_view_v_02.json"
MODEL_PATH = PROJECT_ROOT / "artifacts" / "models" / "hdbscan_temporal_v_02" / "hdbscan_temporal_model_v_02.pkl"
MANIFEST_PATH = PROJECT_ROOT / "artifacts" / "correlation_engine_manifest_v_02.json"
METRICS_PATH = PROJECT_ROOT / "artifacts" / "metrics" / "hdbscan_temporal_training_summary_v_02.json"

EXCLUDED_FEATURE_COLUMNS = (
    "scenario_tag",
    "chaos_suitability",
    "source_signature_id",
    "eligibility_score",
    "ground_truth",
    "label",
    "training_label",
)

PRIORITY_FEATURE_KEYS = (
    "latency_p95_payments",
    "latency_p95_orders",
    "latency_p95_checkout",
    "delta_latency_orders",
    "delta_latency_checkout",
    "error_rate_payments",
    "error_rate_orders",
    "error_rate_checkout",
    "redis_queue_depth",
    "redis_latency",
    "window_anomaly_density",
    "cache_health_score",
    "degradation_intensity_payments",
    "degradation_intensity_orders",
    "degradation_intensity_checkout",
    "propagation_velocity_payments",
    "propagation_velocity_orders",
    "propagation_velocity_checkout",
    "traffic_pressure_payments",
    "traffic_pressure_orders",
    "traffic_pressure_checkout",
    "flow_efficiency_payments",
    "flow_efficiency_orders",
    "flow_efficiency_checkout",
    "stress_rate_payments",
    "stress_rate_orders",
    "stress_rate_checkout",
    "service_criticality_payments",
    "service_criticality_redis",
    "service_criticality_checkout",
    "service_criticality_orders",
    "topological_distance_payments",
    "topological_distance_redis",
    "topological_distance_checkout",
    "topological_distance_orders",
    "upstream_health_payments",
    "upstream_health_redis",
    "upstream_health_checkout",
    "upstream_health_orders",
    "recovery_memory",
)


@dataclass(frozen=True)
class TrainingConfig:
    min_cluster_size: int
    min_samples: int
    cluster_selection_method: str
    metric: str
    normalize_numeric_features: bool
    exclude_training_only_metadata: bool
    fallback_density_eps: float
    training_min_window_quality_score: float
    validation_min_window_quality_score: float
    log_low_quality_windows_separately: bool


@dataclass(frozen=True)
class ClusterOutput:
    backend_requested: str
    backend_executed: str
    fallback_reason: str | None
    assignments: list[dict[str, Any]]


@dataclass(frozen=True)
class TrainingResult:
    backend_requested: str
    backend_executed: str
    feature_keys: list[str]
    eligible_window_count: int
    noise_window_count: int
    cluster_count: int
    assignments: list[dict[str, Any]]
    manifest: dict[str, Any]
    model_payload: dict[str, Any]
    metrics: dict[str, Any]


def load_training_config() -> TrainingConfig:
    config_path = PROJECT_ROOT / "configs" / "hdbscan_config.yaml"
    parsed: dict[str, str] = {}
    with config_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or line.endswith(":"):
                continue
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            parsed[key.strip()] = value.strip()
    return TrainingConfig(
        min_cluster_size=int(parsed["min_cluster_size"]),
        min_samples=int(parsed["min_samples"]),
        cluster_selection_method=parsed.get("cluster_selection_method", "eom"),
        metric=parsed["metric"],
        normalize_numeric_features=parsed["normalize_numeric_features"].lower() == "true",
        exclude_training_only_metadata=parsed["exclude_training_only_metadata"].lower() == "true",
        fallback_density_eps=float(parsed["fallback_density_eps"]),
        training_min_window_quality_score=float(parsed["training_min_window_quality_score"]),
        validation_min_window_quality_score=float(parsed["validation_min_window_quality_score"]),
        log_low_quality_windows_separately=parsed["log_low_quality_windows_separately"].lower() == "true",
    )


def ensure_training_inputs() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    training_profiles = build_training_profiles_v_02()
    training_events = build_events_from_profiles(training_profiles, start_anchor=datetime(2026, 1, 1, tzinfo=timezone.utc))
    windows = build_temporal_windows(training_events, policy=build_windowing_policy_v_02())
    export_temporal_windows(windows, output_path=WINDOWS_PATH)
    feature_rows = build_hdbscan_temporal_feature_view_v_02(windows)
    export_hdbscan_temporal_feature_view_v_02(feature_rows)
    return _load_json(WINDOWS_PATH), _load_json(FEATURE_VIEW_PATH)


def build_events_from_profiles(profiles: list[dict[str, Any]], *, start_anchor: datetime) -> list[Any]:
    cursor = start_anchor
    combined_events: list[Any] = []
    for profile in profiles:
        scenario_events = build_scenario_events(
            profile["scenario_name"],
            seed=int(profile.get("seed", 7)),
            steps=int(profile.get("steps", 12)),
            interval_seconds=int(profile.get("interval_seconds", 30)),
            start_at=cursor,
        )
        combined_events.extend(scenario_events)
        cursor = cursor + timedelta(seconds=(int(profile.get("steps", 12)) * int(profile.get("interval_seconds", 30))) + 300)
    return combined_events


def train_baseline() -> TrainingResult:
    config = load_training_config()
    windows, feature_rows = ensure_training_inputs()
    eligible_windows, low_quality_windows = filter_windows_for_training(windows, config)
    feature_index = {row["window_id"]: row for row in feature_rows}
    matrix_rows, feature_keys, metadata_rows = prepare_training_rows(eligible_windows, feature_index)
    cluster_output = cluster_feature_matrix(matrix_rows, metadata_rows, config)

    cluster_ids = {entry["cluster_id"] for entry in cluster_output.assignments if entry["cluster_id"] != -1}
    noise_count = sum(1 for entry in cluster_output.assignments if entry["cluster_id"] == -1)
    cluster_count = len(cluster_ids)
    metrics = {
        "schema_version": "hdbscan_temporal_training_summary_v_02",
        "backend_requested": cluster_output.backend_requested,
        "backend_executed": cluster_output.backend_executed,
        "eligible_window_count": len(eligible_windows),
        "feature_count": len(feature_keys),
        "cluster_count": cluster_count,
        "noise_window_count": noise_count,
        "clustered_window_count": len(cluster_output.assignments) - noise_count,
        "fallback_reason": cluster_output.fallback_reason,
        "training_min_window_quality_score": config.training_min_window_quality_score,
        "low_quality_window_count": len(low_quality_windows),
    }
    manifest = {
        "schema_version": "correlation_engine_manifest_v_02",
        "engine_name": "hdbscan_temporal",
        "engine_version": "baseline_v_02",
        "training_config": str((PROJECT_ROOT / "configs" / "hdbscan_config.yaml").resolve()),
        "feature_sources": [
            str(WINDOWS_PATH.resolve()),
            str(FEATURE_VIEW_PATH.resolve()),
        ],
        "artifact_paths": {
            "model": str(MODEL_PATH.resolve()),
            "metrics": str(METRICS_PATH.resolve()),
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "backend_requested": cluster_output.backend_requested,
        "backend_executed": cluster_output.backend_executed,
        "fallback_reason": cluster_output.fallback_reason,
        "eligible_window_count": len(eligible_windows),
        "cluster_count": cluster_count,
        "noise_window_count": noise_count,
        "training_min_window_quality_score": config.training_min_window_quality_score,
        "low_quality_window_count": len(low_quality_windows),
    }
    model_payload = {
        "model_name": "hdbscan_temporal_v_02",
        "model_version": "baseline_v_02",
        "backend_requested": cluster_output.backend_requested,
        "backend_executed": cluster_output.backend_executed,
        "fallback_reason": cluster_output.fallback_reason,
        "feature_keys": feature_keys,
        "assignments": cluster_output.assignments,
        "excluded_feature_columns": list(EXCLUDED_FEATURE_COLUMNS),
        "config": {
            "min_cluster_size": config.min_cluster_size,
            "min_samples": config.min_samples,
            "cluster_selection_method": config.cluster_selection_method,
            "metric": config.metric,
            "fallback_density_eps": config.fallback_density_eps,
            "training_min_window_quality_score": config.training_min_window_quality_score,
            "validation_min_window_quality_score": config.validation_min_window_quality_score,
        },
        "low_quality_windows": [window["window_id"] for window in low_quality_windows] if config.log_low_quality_windows_separately else [],
    }
    return TrainingResult(
        backend_requested=cluster_output.backend_requested,
        backend_executed=cluster_output.backend_executed,
        feature_keys=feature_keys,
        eligible_window_count=len(eligible_windows),
        noise_window_count=noise_count,
        cluster_count=cluster_count,
        assignments=cluster_output.assignments,
        manifest=manifest,
        model_payload=model_payload,
        metrics=metrics,
    )


def export_training_result(result: TrainingResult) -> None:
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MODEL_PATH.open("wb") as handle:
        pickle.dump(result.model_payload, handle)
    with METRICS_PATH.open("w", encoding="utf-8") as handle:
        json.dump(result.metrics, handle, indent=2)
    with MANIFEST_PATH.open("w", encoding="utf-8") as handle:
        json.dump(result.manifest, handle, indent=2)


def main() -> int:
    result = train_baseline()
    export_training_result(result)
    print(
        "HDBSCAN temporal v_02 baseline ready: "
        f"backend={result.backend_executed}, windows={result.eligible_window_count}, "
        f"clusters={result.cluster_count}, noise={result.noise_window_count}"
    )
    return 0




def filter_windows_for_training(
    windows: list[dict[str, Any]],
    config: TrainingConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    eligible: list[dict[str, Any]] = []
    low_quality: list[dict[str, Any]] = []
    for window in windows:
        metadata = window.get("training_metadata", {})
        accepted = bool(metadata.get("accepted_for_training"))
        quality_score = float(window.get("window_data_quality_score", 0.0))
        if accepted and quality_score >= config.training_min_window_quality_score:
            eligible.append(window)
        else:
            low_quality.append(window)
    return eligible, low_quality


def filter_windows_for_validation(
    windows: list[dict[str, Any]],
    config: TrainingConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    eligible: list[dict[str, Any]] = []
    low_quality: list[dict[str, Any]] = []
    for window in windows:
        metadata = window.get("training_metadata", {})
        accepted = bool(metadata.get("accepted_for_training"))
        quality_score = float(window.get("window_data_quality_score", 0.0))
        if accepted and quality_score >= config.validation_min_window_quality_score:
            eligible.append(window)
        else:
            low_quality.append(window)
    return eligible, low_quality

def prepare_training_rows(
    windows: list[dict[str, Any]],
    feature_index: dict[str, dict[str, Any]],
    *,
    feature_keys: list[str] | None = None,
) -> tuple[list[list[float]], list[str], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    for window in windows:
        window_id = window["window_id"]
        source_row = feature_index.get(window_id)
        numeric_features = _extract_numeric_features(source_row) if source_row is not None else _extract_numeric_features(window.get("features", {}))
        rows.append(
            {
                "window_id": window_id,
                "scenario_tag": window.get("scenario_tag"),
                "window_data_quality_score": window.get("window_data_quality_score"),
                "numeric_features": numeric_features,
            }
        )

    resolved_feature_keys = feature_keys or [key for key in PRIORITY_FEATURE_KEYS if any(key in row["numeric_features"] for row in rows)]
    if not resolved_feature_keys:
        resolved_feature_keys = sorted({key for row in rows for key in row["numeric_features"].keys()})

    validate_no_target_leakage(resolved_feature_keys)
    matrix = [[row["numeric_features"].get(key, 0.0) for key in resolved_feature_keys] for row in rows]
    normalized = _normalize_matrix(matrix)
    metadata_rows = [
        {
            "window_id": row["window_id"],
            "scenario_tag": row["scenario_tag"],
            "window_data_quality_score": row["window_data_quality_score"],
        }
        for row in rows
    ]
    return normalized, resolved_feature_keys, metadata_rows


def cluster_feature_matrix(
    matrix: list[list[float]],
    metadata_rows: list[dict[str, Any]],
    config: TrainingConfig,
) -> ClusterOutput:
    backend_requested = "hdbscan"
    if matrix and importlib.util.find_spec("hdbscan") is not None:
        import hdbscan  # type: ignore

        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=config.min_cluster_size,
            min_samples=config.min_samples,
            metric=config.metric,
            cluster_selection_method=config.cluster_selection_method,
            prediction_data=True,
        )
        labels = clusterer.fit_predict(matrix).tolist()
        probabilities = [round(float(value), 6) for value in clusterer.probabilities_.tolist()]
        assignments = []
        for index, label in enumerate(labels):
            assignments.append(
                {
                    "window_id": metadata_rows[index]["window_id"],
                    "cluster_id": int(label),
                    "noise": int(label) == -1,
                    "cluster_strength": probabilities[index],
                    "scenario_tag": metadata_rows[index]["scenario_tag"],
                    "window_data_quality_score": metadata_rows[index]["window_data_quality_score"],
                }
            )
        return ClusterOutput(
            backend_requested=backend_requested,
            backend_executed="hdbscan",
            fallback_reason=None,
            assignments=assignments,
        )

    assignments = _cluster_with_density_fallback(
        matrix,
        metadata_rows,
        min_samples=config.min_samples,
        eps=config.fallback_density_eps,
    )
    return ClusterOutput(
        backend_requested=backend_requested,
        backend_executed="density_fallback_dbscan",
        fallback_reason="hdbscan package unavailable in current environment",
        assignments=assignments,
    )




def validate_no_target_leakage(feature_keys: list[str]) -> None:
    leaked = sorted(key for key in feature_keys if key in EXCLUDED_FEATURE_COLUMNS)
    if leaked:
        raise ValueError(f"target leakage detected in training features: {leaked}")

def _extract_numeric_features(source: dict[str, Any] | None) -> dict[str, float]:
    if not source:
        return {}
    numeric: dict[str, float] = {}
    for key, value in source.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            numeric[key] = float(value)
    return numeric


def _normalize_matrix(matrix: list[list[float]]) -> list[list[float]]:
    if not matrix:
        return []
    feature_count = len(matrix[0])
    mins = [min(row[index] for row in matrix) for index in range(feature_count)]
    maxs = [max(row[index] for row in matrix) for index in range(feature_count)]
    normalized: list[list[float]] = []
    for row in matrix:
        normalized_row: list[float] = []
        for index, value in enumerate(row):
            minimum = mins[index]
            maximum = maxs[index]
            if maximum == minimum:
                normalized_row.append(0.0)
            else:
                normalized_row.append(round((value - minimum) / (maximum - minimum), 6))
        normalized.append(normalized_row)
    return normalized


def _cluster_with_density_fallback(
    matrix: list[list[float]],
    metadata_rows: list[dict[str, Any]],
    *,
    min_samples: int,
    eps: float,
) -> list[dict[str, Any]]:
    if not matrix:
        return []

    labels = [-99 for _ in matrix]
    visited = [False for _ in matrix]
    cluster_id = 0

    for index in range(len(matrix)):
        if visited[index]:
            continue
        visited[index] = True
        neighbors = _region_query(matrix, index, eps)
        if len(neighbors) < min_samples:
            labels[index] = -1
            continue
        labels[index] = cluster_id
        seeds = [neighbor for neighbor in neighbors if neighbor != index]
        pointer = 0
        while pointer < len(seeds):
            neighbor_index = seeds[pointer]
            if not visited[neighbor_index]:
                visited[neighbor_index] = True
                neighbor_neighbors = _region_query(matrix, neighbor_index, eps)
                if len(neighbor_neighbors) >= min_samples:
                    for candidate in neighbor_neighbors:
                        if candidate not in seeds:
                            seeds.append(candidate)
            if labels[neighbor_index] in (-99, -1):
                labels[neighbor_index] = cluster_id
            pointer += 1
        cluster_id += 1

    cluster_sizes: dict[int, int] = {}
    for label in labels:
        if label != -1:
            cluster_sizes[label] = cluster_sizes.get(label, 0) + 1

    assignments: list[dict[str, Any]] = []
    for index, label in enumerate(labels):
        size = cluster_sizes.get(label, 0)
        assignments.append(
            {
                "window_id": metadata_rows[index]["window_id"],
                "cluster_id": label,
                "noise": label == -1,
                "cluster_strength": round(size / max(len(matrix), 1), 6) if label != -1 else 0.0,
                "scenario_tag": metadata_rows[index]["scenario_tag"],
                "window_data_quality_score": metadata_rows[index]["window_data_quality_score"],
            }
        )
    return assignments


def _region_query(matrix: list[list[float]], index: int, eps: float) -> list[int]:
    return [candidate for candidate, vector in enumerate(matrix) if dist(matrix[index], vector) <= eps]


def _load_json(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)
