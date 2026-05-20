"""Schema helpers for bus-carried enriched anomaly events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema


EVENT_SCHEMA_VERSION = "enriched_anomaly_event_v0_1"
FORBIDDEN_FIELDS = {"chaos_template", "chaos_execution_plan", "replay_metadata"}
ALLOWED_SEVERITIES = {"low", "medium", "high", "critical"}
ALLOWED_LABELS = {"normal", "anomalous"}
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "contracts" / "enriched_anomaly_event_v0_1.json"


class ValidationError(ValueError):
    """Raised when an event does not satisfy the runtime contract."""


def load_enriched_anomaly_event_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_enriched_anomaly_event(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValidationError("Event payload must be a dictionary.")

    forbidden = FORBIDDEN_FIELDS.intersection(event.keys())
    if forbidden:
        raise ValidationError(f"Forbidden runtime fields present: {sorted(forbidden)!r}")

    schema = load_enriched_anomaly_event_schema()
    validator_class = jsonschema.validators.validator_for(schema)
    validator = validator_class(schema)
    errors = sorted(validator.iter_errors(event), key=lambda err: list(err.path))
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.path) or "<root>"
        raise ValidationError(f"Schema validation failed at {path}: {first.message}")

    primary_service = event["primary_service"]
    if primary_service not in event["services_observed"]:
        raise ValidationError("primary_service must be included in services_observed.")

    if event["severity_preliminary"] not in ALLOWED_SEVERITIES:
        raise ValidationError("severity_preliminary is outside the allowed set.")

    for service, label in event["iforest_labels"].items():
        if label not in ALLOWED_LABELS:
            raise ValidationError(
                f"iforest_labels[{service!r}] must be one of {sorted(ALLOWED_LABELS)!r}."
            )

    return event
