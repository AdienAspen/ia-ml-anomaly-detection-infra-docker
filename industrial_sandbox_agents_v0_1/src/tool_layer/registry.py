"""Allowlisted tool registry for the Layer 4 MVP."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import Path
from typing import Any, Callable

import yaml

from src.security.tool_allowlist import assert_tool_allowlisted

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY_PATH = PROJECT_ROOT / "configs" / "tool_registry" / "tool_registry_v0_1.yaml"


class RegistryError(ValueError):
    """Raised when the tool registry configuration is invalid."""


@dataclass(frozen=True)
class ToolDefinition:
    """Executable tool metadata."""

    tool_name: str
    description: str
    entrypoint: str
    allowlisted: bool
    mcp_compatible: bool
    required_approval: bool
    mode: str
    outputs: list[str]
    constraints: list[str]


@dataclass(frozen=True)
class SkillDefinition:
    """Logical capability metadata."""

    skill_name: str
    description: str
    default_tool: str
    allowed_tools: list[str]


class ToolRegistry:
    """Load and execute allowlisted tools behind stable skill names."""

    def __init__(
        self,
        tools: dict[str, ToolDefinition],
        skills: dict[str, SkillDefinition],
        mcp_compatible: bool,
    ) -> None:
        self._tools = tools
        self._skills = skills
        self.mcp_compatible = mcp_compatible

    @classmethod
    def from_file(cls, config_path: str | Path = DEFAULT_REGISTRY_PATH) -> "ToolRegistry":
        path = Path(config_path)
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}

        if payload.get("schema_version") != "tool_registry_v0_1":
            raise RegistryError("tool_registry_v0_1 schema_version is required.")

        tools = {
            item["tool_name"]: ToolDefinition(
                tool_name=item["tool_name"],
                description=item["description"],
                entrypoint=item["entrypoint"],
                allowlisted=bool(item["allowlisted"]),
                mcp_compatible=bool(item["mcp_compatible"]),
                required_approval=bool(item.get("required_approval", False)),
                mode=item.get("mode", "local"),
                outputs=list(item.get("outputs", [])),
                constraints=list(item.get("constraints", [])),
            )
            for item in payload.get("tools", [])
        }
        skills = {
            item["skill_name"]: SkillDefinition(
                skill_name=item["skill_name"],
                description=item["description"],
                default_tool=item["default_tool"],
                allowed_tools=list(item.get("allowed_tools", [])),
            )
            for item in payload.get("skills", [])
        }

        registry = cls(
            tools=tools,
            skills=skills,
            mcp_compatible=bool(payload.get("mcp_compatible", False)),
        )
        registry._validate()
        return registry

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def list_skills(self) -> list[SkillDefinition]:
        return list(self._skills.values())

    def get_tool(self, tool_name: str) -> ToolDefinition:
        try:
            return self._tools[tool_name]
        except KeyError as exc:
            raise RegistryError(f"Unknown tool: {tool_name}") from exc

    def get_skill(self, skill_name: str) -> SkillDefinition:
        try:
            return self._skills[skill_name]
        except KeyError as exc:
            raise RegistryError(f"Unknown skill: {skill_name}") from exc

    def execute_tool(self, tool_name: str, **kwargs: Any) -> dict[str, Any]:
        definition = self.get_tool(tool_name)
        assert_tool_allowlisted(tool_name)
        function = _resolve_entrypoint(definition.entrypoint)
        result = function(**kwargs)
        if not isinstance(result, dict):
            raise RegistryError(f"Tool {tool_name} returned a non-dict result.")
        return result

    def execute_skill(self, skill_name: str, **kwargs: Any) -> dict[str, Any]:
        skill = self.get_skill(skill_name)
        return self.execute_tool(skill.default_tool, **kwargs)

    def _validate(self) -> None:
        if not self._tools:
            raise RegistryError("Tool registry must declare at least one tool.")
        if not self._skills:
            raise RegistryError("Tool registry must declare at least one skill.")

        for tool_name, tool in self._tools.items():
            if not tool.allowlisted:
                raise RegistryError(f"Tool {tool_name} must be allowlisted for the MVP.")
            _resolve_entrypoint(tool.entrypoint)

        for skill_name, skill in self._skills.items():
            if skill.default_tool not in self._tools:
                raise RegistryError(
                    f"Skill {skill_name} references unknown default tool {skill.default_tool}."
                )
            if skill.default_tool not in skill.allowed_tools:
                raise RegistryError(
                    f"Skill {skill_name} must include its default tool in allowed_tools."
                )
            missing = [tool_name for tool_name in skill.allowed_tools if tool_name not in self._tools]
            if missing:
                raise RegistryError(
                    f"Skill {skill_name} references unknown allowed tools: {', '.join(missing)}."
                )


def load_tool_registry(config_path: str | Path = DEFAULT_REGISTRY_PATH) -> ToolRegistry:
    """Convenience loader for the default registry."""

    return ToolRegistry.from_file(config_path)


def _resolve_entrypoint(entrypoint: str) -> Callable[..., dict[str, Any]]:
    if ":" not in entrypoint:
        raise RegistryError(f"Entrypoint must use module:function format, got {entrypoint}.")

    module_name, function_name = entrypoint.split(":", 1)
    module = importlib.import_module(module_name)

    try:
        function = getattr(module, function_name)
    except AttributeError as exc:
        raise RegistryError(f"Entrypoint target not found: {entrypoint}") from exc

    if not callable(function):
        raise RegistryError(f"Entrypoint target is not callable: {entrypoint}")

    return function
