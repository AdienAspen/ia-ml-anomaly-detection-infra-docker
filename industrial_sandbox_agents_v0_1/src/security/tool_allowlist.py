"""Allowlist enforcement for Layer 4 tools."""

from __future__ import annotations

from dataclasses import dataclass


class ToolAccessError(PermissionError):
    """Raised when a tool is not permitted in the MVP."""


FORBIDDEN_CAPABILITIES = {
    "restart_services",
    "delete_files",
    "change_configs",
    "edit_production_rules",
    "commit_to_main",
    "access_secrets",
    "modify_host",
}


@dataclass(frozen=True)
class ToolPolicy:
    """Small policy surface for allowlisted tools."""

    tool_name: str
    mode: str
    capabilities: tuple[str, ...]
    side_effect_level: str


ALLOWLISTED_TOOLS: dict[str, ToolPolicy] = {
    "metrics_query_tool": ToolPolicy(
        tool_name="metrics_query_tool",
        mode="read_only",
        capabilities=("read_metrics", "query_iforest_scores"),
        side_effect_level="none",
    ),
    "logs_query_tool": ToolPolicy(
        tool_name="logs_query_tool",
        mode="read_only",
        capabilities=("read_logs",),
        side_effect_level="none",
    ),
    "propagation_signature_reader": ToolPolicy(
        tool_name="propagation_signature_reader",
        mode="read_only",
        capabilities=("query_propagation_signatures",),
        side_effect_level="none",
    ),
    "topology_lookup_tool": ToolPolicy(
        tool_name="topology_lookup_tool",
        mode="read_only",
        capabilities=("query_service_topology",),
        side_effect_level="none",
    ),
    "recent_changes_reader": ToolPolicy(
        tool_name="recent_changes_reader",
        mode="read_only",
        capabilities=("read_recent_changes",),
        side_effect_level="none",
    ),
    "runbook_reader": ToolPolicy(
        tool_name="runbook_reader",
        mode="read_only",
        capabilities=("read_runbook",),
        side_effect_level="none",
    ),
    "incident_artifact_writer": ToolPolicy(
        tool_name="incident_artifact_writer",
        mode="controlled_write",
        capabilities=("generate_incident_card", "generate_report"),
        side_effect_level="workspace_reports_only",
    ),
    "notification_sink_tool": ToolPolicy(
        tool_name="notification_sink_tool",
        mode="controlled_write",
        capabilities=("send_notification",),
        side_effect_level="workspace_reports_only",
    ),
}


def assert_tool_allowlisted(tool_name: str) -> ToolPolicy:
    """Return policy for an allowed tool or raise if forbidden."""

    try:
        policy = ALLOWLISTED_TOOLS[tool_name]
    except KeyError as exc:
        raise ToolAccessError(f"Tool {tool_name} is not allowlisted for the MVP.") from exc

    forbidden = FORBIDDEN_CAPABILITIES.intersection(policy.capabilities)
    if forbidden:
        denied = ", ".join(sorted(forbidden))
        raise ToolAccessError(f"Tool {tool_name} requests forbidden capabilities: {denied}")

    return policy


def list_allowlisted_tools() -> list[str]:
    """Expose the current MVP allowlist."""

    return sorted(ALLOWLISTED_TOOLS)
