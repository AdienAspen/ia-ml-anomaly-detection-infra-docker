"""Audit trace generation and bundle writing for Layer 5."""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from src.agentic_core.contracts import (
    validate_confidence_vector,
    validate_incident_card,
    validate_recommendation,
)
from src.audit_policy.contracts import validate_audit_trace
from src.audit_policy.provenance import (
    build_agent_identity,
    build_cognitive_provenance,
    build_context_snapshot,
    summarize_tool_usage,
)
from src.context_engine.contracts import validate_context_slice

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPORTS_ROOT = PROJECT_ROOT / "reports"


def build_audit_trace(
    *,
    context_slice: dict[str, Any],
    confidence_vector: dict[str, Any],
    incident_card: dict[str, Any],
    recommendation: dict[str, Any],
    policy_evaluation: dict[str, Any],
    tool_invocations: list[dict[str, Any]] | None = None,
    agent_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the Layer 5 audit trace for a decision bundle."""

    validate_context_slice(context_slice)
    validate_confidence_vector(confidence_vector)
    validate_incident_card(incident_card)
    validate_recommendation(recommendation)

    payload = {
        "schema_version": "audit_trace_v0_1",
        "event_id": context_slice["event_id"],
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "agent_identity": agent_identity or build_agent_identity(),
        "context_snapshot": build_context_snapshot(context_slice),
        "tools_used": summarize_tool_usage(tool_invocations),
        "outputs_generated": [
            "incident_card.json",
            "confidence_vector.json",
            "recommendation.json",
            "audit_trace.json",
            "report.md",
        ],
        "policy_evaluation": {
            "status": policy_evaluation["status"],
            "mode": policy_evaluation["mode"],
            "human_approval_required": policy_evaluation["human_approval_required"],
            "reviewed_tools": list(policy_evaluation.get("reviewed_tools", [])),
            "prohibited_actions_checked": list(policy_evaluation.get("prohibited_actions_checked", [])),
            "violations": list(policy_evaluation.get("violations", [])),
        },
        "cognitive_provenance": build_cognitive_provenance(
            confidence_vector=confidence_vector,
            tool_invocations=tool_invocations,
        ),
        "decision_rationale": {
            "summary": incident_card["summary"],
            "severity": incident_card["severity"],
            "recommendation_type": recommendation["recommendation_type"],
            "recommendation_text": recommendation["recommendation_text"],
            "human_review_required": confidence_vector["human_review_required"],
        },
    }
    return validate_audit_trace(payload)


def write_audit_bundle(
    *,
    audit_trace: dict[str, Any],
    incident_card: dict[str, Any],
    confidence_vector: dict[str, Any],
    recommendation: dict[str, Any],
    output_dir: str | Path | None = None,
    report_markdown: str | None = None,
) -> dict[str, Any]:
    """Persist the full Layer 5 decision bundle into the reports workspace."""

    validate_audit_trace(audit_trace)
    validate_incident_card(incident_card)
    validate_confidence_vector(confidence_vector)
    validate_recommendation(recommendation)

    event_id = audit_trace["event_id"]
    target_dir = Path(output_dir) if output_dir else REPORTS_ROOT / "incidents" / event_id
    target_dir.mkdir(parents=True, exist_ok=True)

    written_files = [
        _write_json(target_dir / "incident_card.json", incident_card),
        _write_json(target_dir / "confidence_vector.json", confidence_vector),
        _write_json(target_dir / "recommendation.json", recommendation),
        _write_json(target_dir / "audit_trace.json", audit_trace),
    ]

    report_content = report_markdown or build_audit_report_markdown(
        audit_trace=audit_trace,
        incident_card=incident_card,
        confidence_vector=confidence_vector,
        recommendation=recommendation,
    )
    report_path = target_dir / "report.md"
    report_path.write_text(report_content, encoding="utf-8")
    written_files.append(str(report_path))

    return {
        "status": "ok",
        "event_id": event_id,
        "output_dir": str(target_dir),
        "written_files": written_files,
    }


def build_audit_report_markdown(
    *,
    audit_trace: dict[str, Any],
    incident_card: dict[str, Any],
    confidence_vector: dict[str, Any],
    recommendation: dict[str, Any],
) -> str:
    """Render a compact report aligned with the audit trace."""

    tools = audit_trace.get("tools_used", [])
    tool_names = ", ".join(item.get("tool_name", "unknown_tool") for item in tools) or "none"
    policy = audit_trace["policy_evaluation"]
    lines = [
        "# Agentic Audit Report",
        "",
        f"- Event ID: {audit_trace['event_id']}",
        f"- Summary: {incident_card['summary']}",
        f"- Severity: {incident_card['severity']}",
        f"- Recommendation Type: {recommendation['recommendation_type']}",
        f"- Recommendation: {recommendation['recommendation_text']}",
        f"- Confidence Score: {confidence_vector['confidence_score']}",
        f"- Policy Status: {policy['status']}",
        f"- Human Approval Required: {policy['human_approval_required']}",
        f"- Tools Used: {tool_names}",
        "",
        "This report captures the context, policy state, and rationale used to produce the current operator-facing recommendation.",
    ]
    return "\n".join(lines) + "\n"


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return str(path)
