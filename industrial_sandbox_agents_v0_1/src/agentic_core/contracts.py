"""Schema validation helpers for agentic-core outputs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ValidationError(ValueError):
    """Raised when an agentic-core output violates its contract."""


def validate_incident_card(payload: dict[str, Any]) -> dict[str, Any]:
    return _validate_schema_payload("incident_card_v0_1.json", payload)


def validate_recommendation(payload: dict[str, Any]) -> dict[str, Any]:
    return _validate_schema_payload("recommendation_v0_1.json", payload)


def validate_confidence_vector(payload: dict[str, Any]) -> dict[str, Any]:
    return _validate_schema_payload("confidence_vector_v0_1.json", payload)


def _validate_schema_payload(schema_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValidationError("Payload must be a dictionary.")

    schema_path = PROJECT_ROOT / "contracts" / schema_name
    with schema_path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)

    validator_class = jsonschema.validators.validator_for(schema)
    validator = validator_class(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.path) or "<root>"
        raise ValidationError(f"Schema validation failed at {path}: {first.message}")

    return payload
