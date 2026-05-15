"""Evaluate whether a defensive signature could become a future chaos template.

This validator is strictly read-only. It inspects defensive propagation
signatures and emits a bounded readiness assessment for future, separate chaos
planning. It must never execute scenarios.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SIGNATURES_PATH = PROJECT_ROOT / "artifacts" / "propagation_signatures_v0_1.json"
OUTPUT_PATH = PROJECT_ROOT / "artifacts" / "eligibility_report_v0_1.json"
REPORT_PATH = PROJECT_ROOT / "reports" / "chaos_readiness_foundation_report.md"


def load_propagation_signatures() -> list[dict[str, Any]]:
    return json.loads(SIGNATURES_PATH.read_text(encoding="utf-8"))


def build_eligibility_report() -> list[dict[str, Any]]:
    signatures = load_propagation_signatures()
    reports: list[dict[str, Any]] = []
    for signature in signatures:
        eligibility_score = _eligibility_score(signature)
        risk_score = _risk_score(signature)
        recommended_status = _recommended_status(eligibility_score, risk_score)
        warnings = _warnings(signature, risk_score)
        preconditions = _preconditions(signature)
        reports.append(
            {
                "schema_version": "eligibility_report_v0_1",
                "source_signature_id": signature["signature_id"],
                "eligible": eligibility_score >= 0.55 and recommended_status != "not_suitable",
                "eligibility_score": eligibility_score,
                "risk_score": risk_score,
                "recommended_status": recommended_status,
                "preconditions": preconditions,
                "warnings": warnings,
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return reports


def export_eligibility_artifacts(reports: list[dict[str, Any]]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(reports, indent=2), encoding="utf-8")
    REPORT_PATH.write_text(_render_report(reports), encoding="utf-8")


def main() -> int:
    reports = build_eligibility_report()
    export_eligibility_artifacts(reports)
    print(f"Eligibility validator ready: {len(reports)} reports -> {OUTPUT_PATH}")
    return 0


def _eligibility_score(signature: dict[str, Any]) -> float:
    base = 0.0
    if signature.get("detected") and not signature.get("noise"):
        base += 0.35
    chain_len = len(signature.get("services_chain_observed", []))
    base += min(chain_len / 6.0, 0.20)
    quality = float(signature.get("window_data_quality_score", 0.0))
    base += quality * 0.25
    confidence = float(signature.get("propagation_order_confidence", 0.0))
    base += confidence * 0.20
    return round(min(base, 1.0), 6)


def _risk_score(signature: dict[str, Any]) -> float:
    risk = 0.10
    chain_len = len(signature.get("services_chain_observed", []))
    if chain_len >= 4:
        risk += 0.25
    elif chain_len >= 3:
        risk += 0.15
    confidence = float(signature.get("propagation_order_confidence", 0.0))
    risk += max(0.0, 0.20 - (confidence * 0.20))
    quality = float(signature.get("window_data_quality_score", 0.0))
    risk += max(0.0, 0.20 - (quality * 0.20))
    lag_ci = signature.get("lag_pattern_seconds_ci", {})
    for lag_stats in lag_ci.values():
        if not lag_stats:
            continue
        p10 = lag_stats.get("p10")
        p90 = lag_stats.get("p90")
        if p10 is not None and p90 is not None and abs(float(p90) - float(p10)) > 30.0:
            risk += 0.10
            break
    return round(min(risk, 1.0), 6)


def _recommended_status(eligibility_score: float, risk_score: float) -> str:
    if eligibility_score < 0.40:
        return "not_suitable"
    if risk_score > 0.55:
        return "requires_review"
    return "draft"


def _warnings(signature: dict[str, Any], risk_score: float) -> list[str]:
    warnings: list[str] = []
    if signature.get("noise"):
        warnings.append("signature flagged as noise in the defensive lane")
    if float(signature.get("window_data_quality_score", 0.0)) < 0.85:
        warnings.append("window quality is below preferred replay threshold")
    if risk_score > 0.55:
        warnings.append("risk score is elevated and requires human review")
    lag_ci = signature.get("lag_pattern_seconds_ci", {})
    for lag_name, lag_stats in lag_ci.items():
        p10 = lag_stats.get("p10") if isinstance(lag_stats, dict) else None
        p90 = lag_stats.get("p90") if isinstance(lag_stats, dict) else None
        if p10 is not None and p90 is not None and abs(float(p90) - float(p10)) > 30.0:
            warnings.append(f"{lag_name} shows moderate or high variance")
    return warnings


def _preconditions(signature: dict[str, Any]) -> list[str]:
    conditions = [
        "requires isolated lab environment",
        "requires Redis test instance",
        "requires non-production service endpoints",
    ]
    services = signature.get("services_chain_observed", [])
    if "redis" in services:
        conditions.append("requires Redis dependency isolation before replay")
    if len(services) >= 4:
        conditions.append("requires bounded multi-service blast-radius controls")
    return conditions


def _render_report(reports: list[dict[str, Any]]) -> str:
    lines = [
        "# Chaos Readiness Foundation Report",
        "",
        "This report is read-only and does not execute any scenario.",
        "",
    ]
    for report in reports[:10]:
        lines.extend(
            [
                f"## {report['source_signature_id']}",
                f"- eligible: {report['eligible']}",
                f"- eligibility_score: {report['eligibility_score']}",
                f"- risk_score: {report['risk_score']}",
                f"- recommended_status: {report['recommended_status']}",
                f"- preconditions: {', '.join(report['preconditions'])}",
                f"- warnings: {', '.join(report['warnings']) if report['warnings'] else 'none'}",
                "",
            ]
        )
    return "\n".join(lines)
