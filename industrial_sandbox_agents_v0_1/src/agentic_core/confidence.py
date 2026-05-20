"""Confidence validation stage for the Block 1C reasoning flow."""

from __future__ import annotations

from typing import Any

from src.agentic_core.contracts import validate_confidence_vector
from src.context_engine.contracts import validate_context_slice


def build_confidence_vector(
    context_slice: dict[str, Any],
    triage_record: dict[str, Any],
    diagnosis: dict[str, Any],
    tool_success_rate: float = 1.0,
) -> dict[str, Any]:
    """Estimate certainty before allowing a recommendation to be emitted."""

    validate_context_slice(context_slice)
    del diagnosis

    missing_context = []
    if not context_slice.get("runbook_refs"):
        missing_context.append("runbook_refs")
    if not context_slice.get("policy_refs"):
        missing_context.append("policy_refs")

    conflicting_signals = []
    if triage_record["severity"] == "high" and not context_slice.get("recent_anomalies"):
        conflicting_signals.append("High triage severity without recent anomalous services.")

    propagation_detected = bool(triage_record["propagation_detected"])
    anomaly_count = int(triage_record["anomaly_count"])

    evidence_strength = _derive_evidence_strength(propagation_detected, anomaly_count)
    retrieval_quality = "low" if missing_context else "medium"
    model_uncertainty = _derive_model_uncertainty(evidence_strength, retrieval_quality, conflicting_signals)
    policy_status = "warning" if missing_context else "pass"
    confidence_score = _compute_confidence_score(
        evidence_strength=evidence_strength,
        retrieval_quality=retrieval_quality,
        tool_success_rate=tool_success_rate,
        model_uncertainty=model_uncertainty,
        conflicting_signals=conflicting_signals,
        missing_context=missing_context,
        policy_status=policy_status,
    )
    human_review_required = (
        confidence_score < 0.8
        or bool(conflicting_signals)
        or policy_status != "pass"
        or triage_record["severity"] in {"high", "critical"}
    )
    reason = _build_reason(
        evidence_strength=evidence_strength,
        retrieval_quality=retrieval_quality,
        policy_status=policy_status,
        missing_context=missing_context,
        conflicting_signals=conflicting_signals,
    )

    payload = {
        "schema_version": "confidence_vector_v0_1",
        "event_id": context_slice["event_id"],
        "confidence_score": confidence_score,
        "evidence_strength": evidence_strength,
        "retrieval_quality": retrieval_quality,
        "tool_success_rate": round(float(tool_success_rate), 6),
        "model_uncertainty": model_uncertainty,
        "policy_status": policy_status,
        "human_review_required": human_review_required,
        "reason": reason,
        "conflicting_signals": conflicting_signals,
        "missing_context": missing_context,
    }
    return validate_confidence_vector(payload)


def _derive_evidence_strength(propagation_detected: bool, anomaly_count: int) -> str:
    if propagation_detected and anomaly_count >= 1:
        return "high"
    if propagation_detected or anomaly_count >= 1:
        return "medium"
    return "low"


def _derive_model_uncertainty(
    evidence_strength: str,
    retrieval_quality: str,
    conflicting_signals: list[str],
) -> str:
    if conflicting_signals:
        return "high"
    if evidence_strength == "high" and retrieval_quality == "medium":
        return "low"
    return "medium"


def _compute_confidence_score(
    *,
    evidence_strength: str,
    retrieval_quality: str,
    tool_success_rate: float,
    model_uncertainty: str,
    conflicting_signals: list[str],
    missing_context: list[str],
    policy_status: str,
) -> float:
    evidence_map = {"low": 0.45, "medium": 0.65, "high": 0.85}
    retrieval_map = {"low": 0.45, "medium": 0.65, "high": 0.85}
    uncertainty_penalty = {"low": 0.0, "medium": 0.08, "high": 0.18}
    score = (
        evidence_map[evidence_strength] * 0.45
        + retrieval_map[retrieval_quality] * 0.20
        + float(tool_success_rate) * 0.20
        + (1.0 - uncertainty_penalty[model_uncertainty]) * 0.15
    )
    if conflicting_signals:
        score -= 0.08 * len(conflicting_signals)
    if missing_context:
        score -= 0.04 * len(missing_context)
    if policy_status == "blocked":
        score = min(score, 0.25)
    return round(max(0.0, min(score, 1.0)), 6)


def _build_reason(
    *,
    evidence_strength: str,
    retrieval_quality: str,
    policy_status: str,
    missing_context: list[str],
    conflicting_signals: list[str],
) -> str:
    base = (
        f"Evidence strength is {evidence_strength} and retrieval quality is {retrieval_quality}; "
        f"policy status is {policy_status}."
    )
    if missing_context:
        base += f" Missing context: {', '.join(missing_context)}."
    if conflicting_signals:
        base += f" Conflicting signals: {', '.join(conflicting_signals)}."
    return base
