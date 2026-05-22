"""Minimal policy evaluation for the Layer 5 MVP."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.security.tool_allowlist import ToolAccessError, assert_tool_allowlisted

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = PROJECT_ROOT / "configs" / "policy" / "agent_policy_v0_1.yaml"
DEFAULT_SECURITY_PATH = PROJECT_ROOT / "configs" / "security" / "agentic_security_baseline_v0_1.yaml"


def load_policy_config(path: str | Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_security_baseline(path: str | Path = DEFAULT_SECURITY_PATH) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def evaluate_policy(
    *,
    confidence_vector: dict[str, Any],
    recommendation: dict[str, Any],
    tool_invocations: list[dict[str, Any]] | None = None,
    policy_config: dict[str, Any] | None = None,
    security_baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate the current decision bundle against MVP policy rules."""

    effective_policy = policy_config or load_policy_config()
    effective_security = security_baseline or load_security_baseline()
    invocations = tool_invocations or []

    violations: list[str] = []
    reviewed_tools: list[str] = []
    for invocation in invocations:
        tool_name = invocation.get("tool_name", "unknown_tool")
        reviewed_tools.append(tool_name)
        try:
            assert_tool_allowlisted(tool_name)
        except ToolAccessError as exc:
            violations.append(str(exc))

    status = "pass"
    if violations:
        status = "blocked"
    elif confidence_vector.get("policy_status") == "warning" or confidence_vector.get("human_review_required"):
        status = "warning"

    human_approval_required = bool(
        effective_policy.get("human_approval_required", False)
        or recommendation.get("requires_human_approval", False)
    )

    return {
        "schema_version": "policy_evaluation_v0_1",
        "status": status,
        "mode": effective_policy.get("mode", effective_security.get("mvp_mode", "read_only")),
        "human_approval_required": human_approval_required,
        "reviewed_tools": reviewed_tools,
        "prohibited_actions_checked": list(effective_policy.get("prohibited_actions", [])),
        "violations": violations,
        "safeguards": list(effective_security.get("safeguards", [])),
    }
