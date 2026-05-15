#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils import FEATURE_COLUMNS, get_project_paths, load_json, timestamp_utc, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Promote the validated detector policy into a clean artifact bundle.")
    parser.add_argument(
        "--source-model-package",
        type=Path,
        default=Path("artifacts/models/isolation_forest/packages/baseline_v1"),
        help="Packaged model source directory.",
    )
    parser.add_argument(
        "--decision-diagnostics-report",
        type=Path,
        default=Path("artifacts/reports/decision_diagnostics_v1.json"),
        help="Decision diagnostics report JSON.",
    )
    parser.add_argument(
        "--shadow-report",
        type=Path,
        default=Path("artifacts/reports/shadow_service_thresholds_v1.json"),
        help="Prolonged shadow report JSON.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/promoted/detector_policy/shadow_threshold_service_v1"),
        help="Promotion output directory.",
    )
    return parser.parse_args()


def _promoted_policy(decision_report: dict, shadow_report: dict) -> dict:
    thresholds = shadow_report["service_threshold_metrics"]["threshold_by_service"]
    shadow_metrics = shadow_report["service_threshold_metrics"]
    return {
        "schema_version": "iforest_detector_policy_v1",
        "policy_name": "iforest_detector_policy_v1",
        "policy_version": "shadow_threshold_service_v1",
        "runtime_mode": "shadow",
        "model_path": "model.joblib",
        "scoring_policy": "score_samples",
        "threshold_mode": "service_specific",
        "threshold_by_service": thresholds,
        "min_flag_window": 3,
        "expected_features": list(FEATURE_COLUMNS),
        "validation_summary": {
            "true_positive_rate_on_anomalous": shadow_metrics["true_positive_rate_on_anomalous"],
            "false_positive_rate_on_normal": shadow_metrics["false_positive_rate_on_normal"],
            "service_flag_rate_span": shadow_metrics["service_flag_rate_span"],
            "burst_proxy_flag_rate": shadow_metrics["burst_proxy_detection"]["flag_rate"],
            "late_drift_flag_rate": shadow_metrics["drift_detection"]["late_flag_rate"],
        },
        "promoted_from": {
            "block": "1B",
            "model_package": decision_report["model_path"],
            "decision_diagnostics_report": "artifacts/reports/decision_diagnostics_v1.json",
            "shadow_report": "artifacts/reports/shadow_service_thresholds_v1.json",
        },
        "promoted_at": timestamp_utc(),
    }


def main() -> int:
    args = parse_args()
    paths = get_project_paths()

    source_model_package = args.source_model_package if args.source_model_package.is_absolute() else paths.root / args.source_model_package
    decision_report_path = (
        args.decision_diagnostics_report
        if args.decision_diagnostics_report.is_absolute()
        else paths.root / args.decision_diagnostics_report
    )
    shadow_report_path = args.shadow_report if args.shadow_report.is_absolute() else paths.root / args.shadow_report
    output_dir = args.output_dir if args.output_dir.is_absolute() else paths.root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    decision_report = load_json(decision_report_path)
    shadow_report = load_json(shadow_report_path)

    for filename in ("model.joblib", "feature_contract.json", "training_manifest.json", "validation_metrics.json", "manifest.json"):
        source_path = source_model_package / filename
        if source_path.exists():
            shutil.copy2(source_path, output_dir / filename)

    policy = _promoted_policy(decision_report, shadow_report)
    policy_path = output_dir / "iforest_detector_policy_v1.json"
    alias_path = output_dir / "active_detector_policy.json"
    promotion_notes_path = output_dir / "promotion_notes.md"

    write_json(policy_path, policy)
    write_json(
        alias_path,
        {
            "schema_version": "detector_policy_alias_v1",
            "active_policy_path": "iforest_detector_policy_v1.json",
            "updated_at": timestamp_utc(),
        },
    )

    promotion_notes_path.write_text(
        "\n".join(
            [
                "# Detector Policy Promotion Notes",
                "",
                "- 1B discovers and validates; 1A executes the validated detector policy.",
                "- promoted runtime mode: `shadow`",
                "- scoring policy: `score_samples`",
                "- threshold mode: `service_specific`",
                "- 1A must load this policy at startup and keep it cached in memory during inference.",
                f"- checkout-api threshold: `{policy['threshold_by_service']['checkout-api']}`",
                f"- orders-api threshold: `{policy['threshold_by_service']['orders-api']}`",
                f"- payments-api threshold: `{policy['threshold_by_service']['payments-api']}`",
                f"- TPR anomalous: `{policy['validation_summary']['true_positive_rate_on_anomalous']:.6f}`",
                f"- FPR normal: `{policy['validation_summary']['false_positive_rate_on_normal']:.6f}`",
                f"- service span: `{policy['validation_summary']['service_flag_rate_span']:.6f}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "status": "ok",
                "output_dir": str(output_dir),
                "policy_path": str(policy_path),
                "alias_path": str(alias_path),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
