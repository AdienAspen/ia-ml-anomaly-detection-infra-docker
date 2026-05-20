"""Local or mock-first tool implementations for the Layer 4 MVP."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any, Iterable

from src.agentic_core.contracts import (
    validate_confidence_vector,
    validate_incident_card,
    validate_recommendation,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MONOREPO_ROOT = PROJECT_ROOT.parent
REPORTS_ROOT = PROJECT_ROOT / "reports"
DETECTOR_DECISIONS_PATH = MONOREPO_ROOT / "industrial_sandbox_v0_1" / "reports" / "detector_decisions.jsonl"
CORRELATION_DIR = MONOREPO_ROOT / "shared_artifacts" / "correlation_engine" / "hdbscan_production_v1"
CORRELATION_POLICY_PATH = CORRELATION_DIR / "hdbscan_correlation_policy_v1.json"
ACTIVE_CORRELATION_PATH = MONOREPO_ROOT / "shared_artifacts" / "correlation_engine" / "active_correlation_engine.json"
TOPOLOGY_GRAPH_PATH = CORRELATION_DIR / "topology_graph_v_02.json"


def metrics_query_tool(
    service_name: str | None = None,
    event_id: str | None = None,
    limit: int = 5,
    anomalous_only: bool = False,
) -> dict[str, Any]:
    """Return detector-policy observations filtered by service or event."""

    records = []
    normalized_service = _normalize_service_name(service_name) if service_name else None
    for payload in _iter_jsonl(DETECTOR_DECISIONS_PATH):
        if normalized_service and _normalize_service_name(payload.get("service_name")) != normalized_service:
            continue
        if event_id and payload.get("event_id") != event_id:
            continue
        if anomalous_only and not payload.get("anomaly_flag"):
            continue
        records.append(
            {
                "event_id": payload.get("event_id"),
                "service_name": payload.get("service_name"),
                "generated_at": payload.get("generated_at"),
                "anomaly_score": payload.get("anomaly_score"),
                "anomaly_flag": payload.get("anomaly_flag"),
                "candidate_flag": payload.get("candidate_flag"),
                "reason_codes": payload.get("reason_codes", []),
                "scenario_tag": payload.get("scenario_tag"),
            }
        )
        if len(records) >= max(limit, 1):
            break

    return {
        "tool_name": "metrics_query_tool",
        "status": "ok",
        "filters": {
            "service_name": service_name,
            "event_id": event_id,
            "limit": limit,
            "anomalous_only": anomalous_only,
        },
        "records_found": len(records),
        "records": records,
    }


def logs_query_tool(
    service_name: str | None = None,
    event_id: str | None = None,
    severity: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Project detector decisions into synthetic, read-only log summaries."""

    log_entries = []
    for record in metrics_query_tool(service_name=service_name, event_id=event_id, limit=limit * 2)["records"]:
        inferred_severity = _severity_from_flags(record.get("anomaly_flag"), record.get("candidate_flag"))
        if severity and inferred_severity != severity:
            continue
        log_entries.append(
            {
                "timestamp": record.get("generated_at"),
                "service_name": record.get("service_name"),
                "severity": inferred_severity,
                "event_id": record.get("event_id"),
                "message": (
                    f"Detector observed service={record.get('service_name')} "
                    f"score={record.get('anomaly_score')} reasons={','.join(record.get('reason_codes', []))}"
                ),
            }
        )
        if len(log_entries) >= max(limit, 1):
            break

    return {
        "tool_name": "logs_query_tool",
        "status": "ok",
        "filters": {
            "service_name": service_name,
            "event_id": event_id,
            "severity": severity,
            "limit": limit,
        },
        "records_found": len(log_entries),
        "logs": log_entries,
    }


def propagation_signature_reader(signature_id: str | None = None) -> dict[str, Any]:
    """Read the active published correlation policy and related metadata."""

    policy = _read_json(CORRELATION_POLICY_PATH)
    active_alias = _read_json(ACTIVE_CORRELATION_PATH) if ACTIVE_CORRELATION_PATH.exists() else {}
    active_id = active_alias.get("active_correlation_engine") or policy.get("source_production_id")
    requested = signature_id or active_id

    return {
        "tool_name": "propagation_signature_reader",
        "status": "ok",
        "requested_signature_id": requested,
        "matched": requested in {policy.get("source_production_id"), active_id},
        "active_correlation_engine": active_id,
        "policy_name": policy.get("policy_name"),
        "runtime_mode": policy.get("runtime_mode"),
        "selected_metrics": policy.get("selected_metrics", {}),
        "post_filter": policy.get("post_filter", {}),
        "consumer_notes": policy.get("consumer_notes", []),
    }


def topology_lookup_tool(service_name: str | None = None) -> dict[str, Any]:
    """Return topology context from the shared published graph."""

    graph = _read_json(TOPOLOGY_GRAPH_PATH)
    nodes = list(graph.get("nodes", []))
    edges = list(graph.get("edges", []))
    criticality = dict(graph.get("criticality", {}))
    target = _normalize_topology_node(service_name) if service_name else None

    if not target:
        return {
            "tool_name": "topology_lookup_tool",
            "status": "ok",
            "service_name": None,
            "nodes": nodes,
            "edges": edges,
            "criticality": criticality,
        }

    upstream = [edge["source"] for edge in edges if edge.get("target") == target]
    downstream = [edge["target"] for edge in edges if edge.get("source") == target]
    return {
        "tool_name": "topology_lookup_tool",
        "status": "ok",
        "service_name": service_name,
        "normalized_service_name": target,
        "upstream": upstream,
        "downstream": downstream,
        "criticality": criticality.get(target),
        "redis_dependency": "redis" in upstream or "redis" in downstream or target == "redis",
    }


def recent_changes_reader(limit: int = 5) -> dict[str, Any]:
    """Read recent git changes relevant to the 1C workspace."""

    command = [
        "git",
        "-C",
        str(MONOREPO_ROOT),
        "log",
        "--oneline",
        f"-n{max(limit, 1)}",
        "--",
        "industrial_sandbox_agents_v0_1",
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return {
            "tool_name": "recent_changes_reader",
            "status": "warning",
            "changes": [],
            "warning": completed.stderr.strip() or "git log unavailable",
        }

    changes = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    return {
        "tool_name": "recent_changes_reader",
        "status": "ok",
        "changes_found": len(changes),
        "changes": changes,
    }


def runbook_reader(service_name: str | None = None, limit: int = 3) -> dict[str, Any]:
    """Search for runbook-like markdown references without exposing arbitrary files."""

    candidates = list((PROJECT_ROOT / "docs").glob("*.md"))
    candidates.extend((MONOREPO_ROOT / "industrial_sandbox_v0_1" / "reports").glob("*audit*.md"))

    normalized_service = _normalize_service_name(service_name) if service_name else None
    matches = []
    for path in candidates:
        lowered = path.name.lower()
        if normalized_service and normalized_service.replace("-api", "").replace("redis", "redis") not in lowered:
            continue
        matches.append(
            {
                "path": str(path),
                "title": path.stem,
            }
        )
        if len(matches) >= max(limit, 1):
            break

    return {
        "tool_name": "runbook_reader",
        "status": "ok",
        "service_name": service_name,
        "runbooks_found": len(matches),
        "runbook_refs": matches,
    }


def incident_artifact_writer(
    event_id: str,
    incident_card: dict[str, Any] | None = None,
    confidence_vector: dict[str, Any] | None = None,
    recommendation: dict[str, Any] | None = None,
    report_markdown: str | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Write validated incident artifacts into a controlled reports directory."""

    if incident_card is None and confidence_vector is None and recommendation is None and report_markdown is None:
        raise ValueError("At least one incident artifact must be provided.")

    target_dir = Path(output_dir) if output_dir else REPORTS_ROOT / "incidents" / event_id
    target_dir.mkdir(parents=True, exist_ok=True)

    written_files = []
    if incident_card is not None:
        validate_incident_card(incident_card)
        written_files.append(_write_json(target_dir / "incident_card.json", incident_card))
    if confidence_vector is not None:
        validate_confidence_vector(confidence_vector)
        written_files.append(_write_json(target_dir / "confidence_vector.json", confidence_vector))
    if recommendation is not None:
        validate_recommendation(recommendation)
        written_files.append(_write_json(target_dir / "recommendation.json", recommendation))

    report_content = report_markdown or _build_report_markdown(
        event_id=event_id,
        incident_card=incident_card,
        confidence_vector=confidence_vector,
        recommendation=recommendation,
    )
    report_path = target_dir / "report.md"
    report_path.write_text(report_content, encoding="utf-8")
    written_files.append(str(report_path))

    return {
        "tool_name": "incident_artifact_writer",
        "status": "ok",
        "event_id": event_id,
        "output_dir": str(target_dir),
        "written_files": written_files,
    }


def notification_sink_tool(
    event_id: str,
    message: str,
    severity: str = "medium",
    channel: str = "ops-console",
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Persist notification intents without performing external side effects."""

    target_dir = Path(output_dir) if output_dir else REPORTS_ROOT / "notifications"
    target_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "event_id": event_id,
        "severity": severity,
        "channel": channel,
        "message": message,
    }
    output_path = target_dir / "notification_intents.jsonl"
    with output_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True))
        handle.write("\n")
    return {
        "tool_name": "notification_sink_tool",
        "status": "ok",
        "output_path": str(output_path),
        "notification": payload,
    }


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return str(path)


def _normalize_service_name(service_name: str | None) -> str:
    if not service_name:
        return ""
    return service_name.strip().lower()


def _normalize_topology_node(service_name: str | None) -> str:
    normalized = _normalize_service_name(service_name)
    return normalized.replace("-api", "")


def _severity_from_flags(anomaly_flag: Any, candidate_flag: Any) -> str:
    if anomaly_flag:
        return "high"
    if candidate_flag:
        return "medium"
    return "low"


def _build_report_markdown(
    event_id: str,
    incident_card: dict[str, Any] | None,
    confidence_vector: dict[str, Any] | None,
    recommendation: dict[str, Any] | None,
) -> str:
    lines = [
        "# Agentic Incident Report",
        "",
        f"- Event ID: {event_id}",
    ]
    if incident_card:
        lines.extend(
            [
                f"- Summary: {incident_card.get('summary')}",
                f"- Severity: {incident_card.get('severity')}",
                f"- Suspected Scope: {incident_card.get('suspected_scope')}",
            ]
        )
    if confidence_vector:
        lines.extend(
            [
                f"- Confidence Score: {confidence_vector.get('confidence_score')}",
                f"- Evidence Strength: {confidence_vector.get('evidence_strength')}",
                f"- Policy Status: {confidence_vector.get('policy_status')}",
            ]
        )
    if recommendation:
        lines.extend(
            [
                f"- Recommendation Type: {recommendation.get('recommendation_type')}",
                f"- Recommendation: {recommendation.get('recommendation_text')}",
            ]
        )
    lines.extend(
        [
            "",
            "This report was generated by the Layer 4 incident_artifact_writer in observe/explain/recommend mode.",
        ]
    )
    return "\n".join(lines) + "\n"
