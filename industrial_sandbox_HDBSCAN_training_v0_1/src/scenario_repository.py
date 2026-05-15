"""Scenario repository helpers for explicit training and validation partitions."""

from __future__ import annotations

from pathlib import Path
import json
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1] / "scenario_repository"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_partition(partition_name: str) -> dict[str, Any]:
    mapping = {
        "training": REPOSITORY_ROOT / "training_scenarios" / "training_scenarios_v0_1.json",
        "validation": REPOSITORY_ROOT / "validation_scenarios" / "validation_scenarios_v0_1.json",
        "chaos_eligible": REPOSITORY_ROOT / "chaos_eligible_scenarios" / "chaos_eligible_scenarios_v0_1.json",
        "chaos_safe_templates": REPOSITORY_ROOT / "chaos_safe_templates" / "chaos_template_placeholders_v0_0_1.json",
    }
    if partition_name not in mapping:
        raise KeyError(f"unknown scenario partition: {partition_name}")
    return _load_json(mapping[partition_name])


def load_training_scenarios() -> list[dict[str, Any]]:
    return list(load_partition("training").get("scenarios", []))


def load_validation_scenarios() -> list[dict[str, Any]]:
    return list(load_partition("validation").get("scenarios", []))


def load_chaos_eligible_scenarios() -> list[dict[str, Any]]:
    return list(load_partition("chaos_eligible").get("scenarios", []))


def load_chaos_template_placeholders() -> list[dict[str, Any]]:
    return list(load_partition("chaos_safe_templates").get("templates", []))


def summarize_repository() -> dict[str, Any]:
    training = load_training_scenarios()
    validation = load_validation_scenarios()
    chaos_eligible = load_chaos_eligible_scenarios()
    templates = load_chaos_template_placeholders()
    return {
        "training_count": len(training),
        "validation_count": len(validation),
        "chaos_eligible_count": len(chaos_eligible),
        "placeholder_template_count": len(templates),
        "training_scenarios": sorted({entry["scenario_name"] for entry in training}),
        "validation_scenarios": sorted({entry["scenario_name"] for entry in validation}),
    }
