"""Common telemetry contract helpers for block 1B.2.

This module defines the runtime-reproducible event language shared by the
synthetic generator, the scenario engine, and downstream feature views.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid

SCHEMA_VERSION = "common_telemetry_event_v0_1"
ALLOWED_SERVICES = ("payments-api", "orders-api", "checkout-api", "redis")
ALLOWED_SOURCES = ("synthetic_generator", "runtime")
ALLOWED_CHAOS_SUITABILITY = (
    "not_suitable",
    "suitable_with_limits",
    "suitable_full_replay",
    "requires_review",
    None,
)


@dataclass(frozen=True)
class CommonTelemetryEvent:
    event_id: str
    timestamp: str
    sequence_number: int
    service_name: str
    metric_name: str
    metric_value: float
    unit: str
    source: str
    is_training_only_field: bool
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    window_id: str | None = None
    correlation_id: str | None = None
    scenario_tag: str | None = None
    chaos_suitability: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CommonTelemetryValidationError(ValueError):
    """Raised when a payload violates the common telemetry contract."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_common_telemetry_event(
    *,
    sequence_number: int,
    service_name: str,
    metric_name: str,
    metric_value: float,
    unit: str,
    source: str,
    metadata: dict[str, Any] | None = None,
    event_id: str | None = None,
    timestamp: str | None = None,
    window_id: str | None = None,
    correlation_id: str | None = None,
    scenario_tag: str | None = None,
    chaos_suitability: str | None = None,
    is_training_only_field: bool = False,
) -> CommonTelemetryEvent:
    event = CommonTelemetryEvent(
        event_id=event_id or str(uuid.uuid4()),
        timestamp=timestamp or utc_now_iso(),
        sequence_number=sequence_number,
        window_id=window_id,
        service_name=service_name,
        metric_name=metric_name,
        metric_value=float(metric_value),
        unit=unit,
        correlation_id=correlation_id,
        scenario_tag=scenario_tag,
        chaos_suitability=chaos_suitability,
        source=source,
        is_training_only_field=is_training_only_field,
        metadata=metadata or {},
    )
    validate_common_telemetry_event(event.to_dict(), raise_on_error=True)
    return event


def validate_common_telemetry_event(
    payload: dict[str, Any],
    *,
    raise_on_error: bool = False,
) -> list[str]:
    errors: list[str] = []

    required_fields = (
        "schema_version",
        "event_id",
        "timestamp",
        "sequence_number",
        "service_name",
        "metric_name",
        "metric_value",
        "unit",
        "source",
        "is_training_only_field",
        "metadata",
    )
    for field_name in required_fields:
        if field_name not in payload:
            errors.append(f"missing required field: {field_name}")

    if not errors:
        if payload.get("schema_version") != SCHEMA_VERSION:
            errors.append("schema_version mismatch")
        if payload.get("service_name") not in ALLOWED_SERVICES:
            errors.append("invalid service_name")
        if payload.get("source") not in ALLOWED_SOURCES:
            errors.append("invalid source")
        if payload.get("chaos_suitability") not in ALLOWED_CHAOS_SUITABILITY:
            errors.append("invalid chaos_suitability")
        if not isinstance(payload.get("sequence_number"), int) or payload["sequence_number"] < 0:
            errors.append("sequence_number must be a non-negative integer")
        if not isinstance(payload.get("metric_name"), str) or not payload["metric_name"].strip():
            errors.append("metric_name must be a non-empty string")
        try:
            float(payload.get("metric_value"))
        except (TypeError, ValueError):
            errors.append("metric_value must be numeric")
        if not isinstance(payload.get("unit"), str) or not payload["unit"].strip():
            errors.append("unit must be a non-empty string")
        if not isinstance(payload.get("is_training_only_field"), bool):
            errors.append("is_training_only_field must be boolean")
        if not isinstance(payload.get("metadata"), dict):
            errors.append("metadata must be an object")
        timestamp_value = payload.get("timestamp")
        if isinstance(timestamp_value, str):
            candidate = timestamp_value.replace("Z", "+00:00")
            try:
                datetime.fromisoformat(candidate)
            except ValueError:
                errors.append("timestamp must be ISO-8601 compatible")
        else:
            errors.append("timestamp must be a string")

    if errors and raise_on_error:
        raise CommonTelemetryValidationError("; ".join(errors))
    return errors


def sort_common_telemetry_events(events: list[CommonTelemetryEvent]) -> list[CommonTelemetryEvent]:
    return sorted(events, key=lambda item: (item.timestamp, item.sequence_number))
