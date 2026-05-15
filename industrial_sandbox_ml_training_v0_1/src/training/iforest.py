from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from src.utils import FEATURE_COLUMNS, load_json, timestamp_utc, write_json


def train_iforest_artifact(
    *,
    frame: Any,
    dataset_path: Path,
    output_dir: Path,
    model_version: str,
    hyperparameters: dict[str, Any],
    feature_contract_path: Path,
    metrics_path: Path,
    report_path: Path,
) -> dict[str, Any]:
    x = frame.select(list(FEATURE_COLUMNS)).to_numpy()
    model = IsolationForest(
        n_estimators=hyperparameters["n_estimators"],
        max_samples=hyperparameters["max_samples"],
        contamination=hyperparameters["contamination"],
        random_state=hyperparameters["random_state"],
    )
    model.fit(x)
    raw_scores = model.score_samples(x)
    anomaly_scores = -raw_scores

    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "model.joblib"
    manifest_path = output_dir / "training_manifest.json"
    copied_contract_path = output_dir / "feature_contract.json"

    joblib.dump(model, model_path)
    write_json(copied_contract_path, load_json(feature_contract_path))

    training_metrics = {
        "trained_at": timestamp_utc(),
        "dataset_path": str(dataset_path),
        "row_count": frame.height,
        "feature_columns": list(FEATURE_COLUMNS),
        "raw_score_summary": {
            "min": float(np.min(raw_scores)),
            "mean": float(np.mean(raw_scores)),
            "std": float(np.std(raw_scores)),
            "p05": float(np.quantile(raw_scores, 0.05)),
            "p50": float(np.quantile(raw_scores, 0.50)),
            "p95": float(np.quantile(raw_scores, 0.95)),
            "max": float(np.max(raw_scores)),
        },
        "anomaly_score_summary": {
            "min": float(np.min(anomaly_scores)),
            "mean": float(np.mean(anomaly_scores)),
            "std": float(np.std(anomaly_scores)),
            "p05": float(np.quantile(anomaly_scores, 0.05)),
            "p50": float(np.quantile(anomaly_scores, 0.50)),
            "p95": float(np.quantile(anomaly_scores, 0.95)),
            "max": float(np.max(anomaly_scores)),
        },
    }
    write_json(metrics_path, training_metrics)

    training_manifest = {
        "model_name": "isolation_forest",
        "model_version": model_version,
        "created_at": timestamp_utc(),
        "dataset_path": str(dataset_path),
        "row_count": frame.height,
        "feature_columns": list(FEATURE_COLUMNS),
        "hyperparameters": hyperparameters,
        "artifact_path": str(model_path),
        "feature_contract_path": str(copied_contract_path),
        "metrics_path": str(metrics_path),
    }
    write_json(manifest_path, training_manifest)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        "\n".join(
            [
                "# Training Baseline Report",
                "",
                "## Summary",
                f"- trained_at: `{training_metrics['trained_at']}`",
                f"- dataset_path: `{dataset_path}`",
                f"- row_count: `{frame.height}`",
                f"- model_path: `{model_path}`",
                "",
                "## Hyperparameters",
                f"- n_estimators: `{hyperparameters['n_estimators']}`",
                f"- max_samples: `{hyperparameters['max_samples']}`",
                f"- contamination: `{hyperparameters['contamination']}`",
                f"- random_state: `{hyperparameters['random_state']}`",
                "",
                "## Raw Score Summary",
                f"- mean: `{training_metrics['raw_score_summary']['mean']:.6f}`",
                f"- p05: `{training_metrics['raw_score_summary']['p05']:.6f}`",
                f"- p50: `{training_metrics['raw_score_summary']['p50']:.6f}`",
                f"- p95: `{training_metrics['raw_score_summary']['p95']:.6f}`",
                "",
                "## Anomaly Score Summary",
                f"- mean: `{training_metrics['anomaly_score_summary']['mean']:.6f}`",
                f"- p05: `{training_metrics['anomaly_score_summary']['p05']:.6f}`",
                f"- p50: `{training_metrics['anomaly_score_summary']['p50']:.6f}`",
                f"- p95: `{training_metrics['anomaly_score_summary']['p95']:.6f}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    return {
        "model": model,
        "model_path": model_path,
        "manifest_path": manifest_path,
        "metrics_path": metrics_path,
        "report_path": report_path,
        "training_metrics": training_metrics,
        "training_manifest": training_manifest,
    }
