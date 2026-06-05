from __future__ import annotations

from typing import Any

from agent_factory.tooling.skills.skill_tool_protocol import (
    registry_from_resources,
    repair_resource_mode,
    required_string,
    resource_mode,
    resource_paths,
    skill_error_facts,
    skill_error_guidance,
)
from agent_factory.tooling.spec import ToolRiskResult


def evaluate_skill_tool_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    resources = dict(context.get("resources") or {})
    try:
        registry = registry_from_resources(resources)
        action = str(arguments.get("action") or "").strip()
        if action == "list":
            return ToolRiskResult(action="allow", risk_level="low").model_dump(mode="json")
        if action == "search":
            required_string(arguments, "query")
            return ToolRiskResult(
                action="allow",
                risk_level="low",
                reasons=["skill search exposes enabled skill metadata only"],
            ).model_dump(mode="json")
        if action == "list_loaded":
            current_todo = required_string(arguments, "current_todo")
            return ToolRiskResult(
                action="allow",
                risk_level="low",
                reasons=["skill loaded-state inspection exposes gateway state only"],
                facts={"current_todo": current_todo},
            ).model_dump(mode="json")
        name = required_string(arguments, "name")
        registry.get(name)
        if action == "describe":
            current_todo = required_string(arguments, "current_todo")
            return ToolRiskResult(
                action="allow",
                risk_level="low",
                reasons=["skill describe exposes metadata and resource index only"],
                facts={"skill": name, "current_todo": current_todo},
            ).model_dump(mode="json")
        if action == "load":
            current_todo = required_string(arguments, "current_todo")
            reason = required_string(arguments, "reason")
            registry.load(name, current_todo=current_todo, reason=reason)
            return ToolRiskResult(
                action="allow",
                risk_level="medium",
                reasons=["skill load exposes one enabled SKILL.md body to the model for the active todo"],
                facts={"skill": name, "current_todo": current_todo, "reason": reason},
            ).model_dump(mode="json")
        if action == "read_resource":
            current_todo = required_string(arguments, "current_todo")
            path = required_string(arguments, "path")
            mode = resource_mode(arguments.get("mode"))
            pointer = str(arguments.get("pointer") or "").strip()
            registry.read_resource(name, path, current_todo=current_todo, mode=mode, pointer=pointer)
            return ToolRiskResult(
                action="allow",
                risk_level="medium",
                reasons=["skill resource read is restricted to enabled skill resources"],
                facts={"skill": name, "path": path, "mode": mode, "current_todo": current_todo},
            ).model_dump(mode="json")
        if action == "read_repair_resources":
            current_todo = required_string(arguments, "current_todo")
            paths = resource_paths(arguments.get("paths"))
            registry.describe(name, current_todo=current_todo)
            for path in paths:
                registry.read_resource(name, path, current_todo=current_todo, mode=repair_resource_mode(path))
            return ToolRiskResult(
                action="allow",
                risk_level="medium",
                reasons=["skill repair resource bundle is restricted to enabled skill resources"],
                facts={"skill": name, "paths": paths, "current_todo": current_todo},
            ).model_dump(mode="json")
        return ToolRiskResult(
            action="deny",
            risk_level="medium",
            reasons=["skill action must be one of: list, search, describe, load, list_loaded, read_resource, read_repair_resources"],
        ).model_dump(mode="json")
    except Exception as exc:
        guidance = skill_error_guidance(arguments, exc)
        return ToolRiskResult(
            action="deny",
            risk_level="medium",
            reasons=[
                f"skill request is invalid: {type(exc).__name__}: {exc}",
                guidance,
            ],
            facts=skill_error_facts(arguments, exc),
        ).model_dump(mode="json")
