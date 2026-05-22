"""Cognitive provenance helpers for Layer 5 audit traces."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def build_agent_identity(
    *,
    agent_name: str = "agentic-layer",
    runtime: str = "block_1c_mvp",
    mode: str = "read_only",
    version: str = "0.1.0",
) -> dict[str, Any]:
    """Describe the actor that generated the audit trace."""

    return {
        "agent_name": agent_name,
        "runtime": runtime,
        "mode": mode,
        "version": version,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


def build_context_snapshot(context_slice: dict[str, Any]) -> dict[str, Any]:
    """Capture the minimum context slice used by the reasoning flow."""

    return {
        "primary_service": context_slice["primary_service"],
        "related_services": list(context_slice.get("related_services", [])),
        "topology_summary": context_slice.get("topology_summary", ""),
        "propagation_summary": context_slice.get("propagation_summary", ""),
        "recent_anomalies_count": len(context_slice.get("recent_anomalies", [])),
        "runbook_refs_count": len(context_slice.get("runbook_refs", [])),
        "policy_refs_count": len(context_slice.get("policy_refs", [])),
        "token_budget": dict(context_slice.get("token_budget", {})),
    }


def summarize_tool_usage(tool_invocations: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Reduce raw tool invocations into compact, auditable summaries."""

    if not tool_invocations:
        return []

    summaries = []
    for invocation in tool_invocations:
        payload = dict(invocation)
        summaries.append(
            {
                "tool_name": payload.get("tool_name", "unknown_tool"),
                "status": payload.get("status", "unknown"),
                "records_found": int(payload.get("records_found", 0)),
                "source": _infer_tool_source(payload),
            }
        )
    return summaries


def build_cognitive_provenance(
    *,
    confidence_vector: dict[str, Any],
    tool_invocations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Summarize what the system knew and where certainty came from."""

    return {
        "confidence_score": confidence_vector["confidence_score"],
        "evidence_strength": confidence_vector["evidence_strength"],
        "retrieval_quality": confidence_vector["retrieval_quality"],
        "tool_success_rate": confidence_vector["tool_success_rate"],
        "model_uncertainty": confidence_vector["model_uncertainty"],
        "missing_context": list(confidence_vector.get("missing_context", [])),
        "conflicting_signals": list(confidence_vector.get("conflicting_signals", [])),
        "evidence_sources": _build_evidence_sources(tool_invocations or []),
        "reason": confidence_vector["reason"],
    }


def _build_evidence_sources(tool_invocations: list[dict[str, Any]]) -> list[str]:
    if not tool_invocations:
        return ["context_slice_only"]
    return [invocation.get("tool_name", "unknown_tool") for invocation in tool_invocations]


def _infer_tool_source(invocation: dict[str, Any]) -> str:
    if "records" in invocation:
        return "detector_decisions"
    if "logs" in invocation:
        return "detector_logs_projection"
    if "policy_name" in invocation:
        return "correlation_engine_policy"
    if "upstream" in invocation or "nodes" in invocation:
        return "service_topology"
    return "workspace_local"
