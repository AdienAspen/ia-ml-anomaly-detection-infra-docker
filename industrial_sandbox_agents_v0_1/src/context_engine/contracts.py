"""Schema validation for context slices."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema


SCHEMA_PATH = Path(__file__).resolve().parents[2] / "contracts" / "context_slice_v0_1.json"


class ValidationError(ValueError):
    """Raised when a context slice does not satisfy the runtime contract."""


def load_context_slice_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_context_slice(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValidationError("Context slice payload must be a dictionary.")

    schema = load_context_slice_schema()
    validator_class = jsonschema.validators.validator_for(schema)
    validator = validator_class(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda err: list(err.path))
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.path) or "<root>"
        raise ValidationError(f"Schema validation failed at {path}: {first.message}")

    if payload["schema_version"] != "context_slice_v0_1":
        raise ValidationError("schema_version must be 'context_slice_v0_1'.")

    token_budget = payload["token_budget"]
    if int(token_budget["estimated_tokens"]) > int(token_budget["max_tokens"]):
        raise ValidationError("token_budget.estimated_tokens cannot exceed token_budget.max_tokens.")

    return payload
