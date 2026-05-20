"""Window volume scaling helpers for the HDBSCAN v_02 feature lane."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json

from src.build_temporal_windows import WindowingPolicy, load_windowing_policy
from src.scenario_repository import load_training_scenarios, load_validation_scenarios

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "configs" / "window_scaling_v_02.yaml"
SUMMARY_PATH = PROJECT_ROOT / "artifacts" / "metrics" / "window_scaling_summary_v_02.json"


@dataclass(frozen=True)
class WindowScalingConfig:
    schema_version: str
    training_profiles_target: int
    validation_profiles_target: int
    chaos_eligible_profiles_target: int
    stride_seconds_target: int
    window_length_seconds: int
    min_events_per_window: int
    max_missing_ratio: float
    late_event_tolerance_seconds: int
    discard_window_if_quality_below: float
    seed_start: int
    steps_per_profile_target: int
    interval_seconds: int
    scenarios: tuple[str, ...]


def load_window_scaling_config(path: Path = CONFIG_PATH) -> WindowScalingConfig:
    parsed: dict[str, str] = {}
    current_section: str | None = None
    scenarios: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.endswith(":"):
                section_name = stripped[:-1]
                if section_name == "scenarios" and current_section == "profile_expansion":
                    current_section = "profile_expansion.scenarios"
                else:
                    current_section = section_name
                continue
            if stripped.startswith("- ") and current_section == "profile_expansion.scenarios":
                scenarios.append(stripped[2:].strip())
                continue
            if stripped.startswith("- ") and current_section == "profile_expansion":
                scenarios.append(stripped[2:].strip())
                continue
            if ":" not in stripped:
                continue
            key, value = stripped.split(":", 1)
            full_key = f"{current_section}.{key.strip()}" if current_section else key.strip()
            parsed[full_key] = value.strip()
            if full_key == "profile_expansion.scenarios":
                current_section = "profile_expansion.scenarios"
    return WindowScalingConfig(
        schema_version=parsed.get("schema_version", "window_scaling_v_02"),
        training_profiles_target=int(parsed["profile_expansion.training_profiles_target"]),
        validation_profiles_target=int(parsed["profile_expansion.validation_profiles_target"]),
        chaos_eligible_profiles_target=int(parsed["profile_expansion.chaos_eligible_profiles_target"]),
        stride_seconds_target=int(parsed["window_sampling.stride_seconds_target"]),
        window_length_seconds=int(parsed["window_sampling.window_length_seconds"]),
        min_events_per_window=int(parsed["window_sampling.min_events_per_window"]),
        max_missing_ratio=float(parsed["window_sampling.max_missing_ratio"]),
        late_event_tolerance_seconds=int(parsed["window_sampling.late_event_tolerance_seconds"]),
        discard_window_if_quality_below=float(parsed["window_sampling.discard_window_if_quality_below"]),
        seed_start=int(parsed["scenario_profile_defaults.seed_start"]),
        steps_per_profile_target=int(parsed["scenario_profile_defaults.steps_per_profile_target"]),
        interval_seconds=int(parsed["scenario_profile_defaults.interval_seconds"]),
        scenarios=tuple(scenarios),
    )


def build_windowing_policy_v_02(config: WindowScalingConfig | None = None) -> WindowingPolicy:
    scaling = config or load_window_scaling_config()
    base_policy = load_windowing_policy()
    return WindowingPolicy(
        window_length_seconds=scaling.window_length_seconds,
        stride_seconds=scaling.stride_seconds_target,
        max_missing_ratio=scaling.max_missing_ratio,
        late_event_tolerance_seconds=scaling.late_event_tolerance_seconds,
        late_discard_ratio_threshold=base_policy.late_discard_ratio_threshold,
        min_events_per_window=scaling.min_events_per_window,
        discard_window_if_quality_below=scaling.discard_window_if_quality_below,
        late_event_policy_mode=base_policy.late_event_policy_mode,
        within_tolerance_action=base_policy.within_tolerance_action,
        beyond_tolerance_action=base_policy.beyond_tolerance_action,
    )


def build_training_profiles_v_02(config: WindowScalingConfig | None = None) -> list[dict[str, Any]]:
    scaling = config or load_window_scaling_config()
    templates = _build_template_index(load_training_scenarios(), load_validation_scenarios(), scaling=scaling)
    return _expand_profiles(
        templates=templates,
        scenario_names=scaling.scenarios,
        target_count=scaling.training_profiles_target,
        seed_start=scaling.seed_start,
        partition_prefix="train_v_02",
    )


def build_validation_profiles_v_02(config: WindowScalingConfig | None = None) -> list[dict[str, Any]]:
    scaling = config or load_window_scaling_config()
    templates = _build_template_index(load_training_scenarios(), load_validation_scenarios(), scaling=scaling)
    return _expand_profiles(
        templates=templates,
        scenario_names=scaling.scenarios,
        target_count=scaling.validation_profiles_target,
        seed_start=scaling.seed_start + 10_000,
        partition_prefix="val_v_02",
    )


def export_window_scaling_summary_v_02(training_profiles: list[dict[str, Any]], validation_profiles: list[dict[str, Any]], path: Path = SUMMARY_PATH) -> Path:
    payload = {
        "schema_version": "window_scaling_summary_v_02",
        "training_profile_count": len(training_profiles),
        "validation_profile_count": len(validation_profiles),
        "training_scenario_distribution": dict(Counter(item["scenario_name"] for item in training_profiles)),
        "validation_scenario_distribution": dict(Counter(item["scenario_name"] for item in validation_profiles)),
        "training_seed_range": [training_profiles[0]["seed"], training_profiles[-1]["seed"]] if training_profiles else [],
        "validation_seed_range": [validation_profiles[0]["seed"], validation_profiles[-1]["seed"]] if validation_profiles else [],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _build_template_index(*profile_lists: list[dict[str, Any]], scaling: WindowScalingConfig) -> dict[str, dict[str, Any]]:
    templates: dict[str, dict[str, Any]] = {}
    for profiles in profile_lists:
        for profile in profiles:
            scenario_name = str(profile["scenario_name"])
            existing = templates.get(scenario_name)
            if existing is None or int(profile.get("steps", 0)) > int(existing.get("steps", 0)):
                templates[scenario_name] = {
                    "scenario_name": scenario_name,
                    "steps": int(profile.get("steps", scaling.steps_per_profile_target)),
                    "interval_seconds": int(profile.get("interval_seconds", scaling.interval_seconds)),
                    "notes": list(profile.get("notes", [])),
                }
    for scenario_name in scaling.scenarios:
        templates.setdefault(
            scenario_name,
            {
                "scenario_name": scenario_name,
                "steps": scaling.steps_per_profile_target,
                "interval_seconds": scaling.interval_seconds,
                "notes": ["generated from v_02 scaling defaults"],
            },
        )
    return templates


def _expand_profiles(*, templates: dict[str, dict[str, Any]], scenario_names: tuple[str, ...], target_count: int, seed_start: int, partition_prefix: str) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    if not scenario_names or target_count <= 0:
        return expanded
    for index in range(target_count):
        scenario_name = scenario_names[index % len(scenario_names)]
        template = templates[scenario_name]
        expanded.append(
            {
                "profile_id": f"{partition_prefix}_{index:03d}",
                "scenario_name": scenario_name,
                "seed": seed_start + index,
                "steps": int(template["steps"]),
                "interval_seconds": int(template["interval_seconds"]),
                "notes": list(template.get("notes", [])) + ["window_scaling_v_02", f"replica_index={index}"],
            }
        )
    return expanded
