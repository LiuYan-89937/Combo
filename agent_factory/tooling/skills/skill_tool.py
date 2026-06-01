from __future__ import annotations

from typing import Any

from agent_factory.tooling.skills.registry import SkillRegistry
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolRiskResult, ToolSpec


SKILL_RESOURCE_KEY = "skills"
SKILL_TOOL_ID = "skill"


def build_skill_tool_spec(registry: SkillRegistry) -> ToolSpec:
    actions = ["list", "search", "describe", "load", "read_resource"]
    return ToolSpec(
        id=SKILL_TOOL_ID,
        description=_tool_description(registry),
        entrypoint="agent_factory.tooling.skills.skill_tool:run",
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": actions,
                    "description": (
                        "Skill Gateway action. list/search/describe expose metadata only. "
                        "load returns SKILL.md. read_resource reads one referenced skill resource."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": "Required for describe/load/read_resource. Do not pass this for list/search.",
                },
                "path": {
                    "type": "string",
                    "description": "Required only for read_resource.",
                },
                "query": {
                    "type": "string",
                    "description": "Required only for search. Searches enabled skill metadata and resource names.",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "description": "Optional search result limit. Defaults to 20.",
                },
            },
            "required": ["action"],
            "oneOf": [
                {"properties": {"action": {"const": "list"}}, "required": ["action"]},
                {"properties": {"action": {"const": "search"}}, "required": ["action", "query"]},
                {"properties": {"action": {"const": "describe"}}, "required": ["action", "name"]},
                {"properties": {"action": {"const": "load"}}, "required": ["action", "name"]},
                {"properties": {"action": {"const": "read_resource"}}, "required": ["action", "name", "path"]},
            ],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": actions},
                "message": {"type": "string"},
                "skills": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                "skill": {"type": ["object", "null"], "additionalProperties": True},
                "resource": {"type": ["object", "null"], "additionalProperties": True},
            },
            "required": ["action", "message", "skills", "skill", "resource"],
            "additionalProperties": False,
        },
        resources={"skills": SKILL_RESOURCE_KEY},
        risk_level="medium",
        risk_evaluator=ToolRiskEvaluatorConfig(hard="agent_factory.tooling.skills.skill_tool:evaluate_risk"),
        concurrent=True,
    )


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    registry = _registry(resources)
    action = str(arguments.get("action") or "").strip()
    if action == "list":
        return {
            "action": action,
            "message": "Available skills metadata.",
            "skills": registry.list_metadata(),
            "skill": None,
            "resource": None,
        }
    if action == "search":
        query = _required_string(arguments, "query")
        limit = _limit(arguments.get("limit"))
        return {
            "action": action,
            "message": f"Skill search results for: {query}",
            "skills": registry.search(query, limit=limit),
            "skill": None,
            "resource": None,
        }
    name = _required_string(arguments, "name")
    if action == "describe":
        return {
            "action": action,
            "message": f"Skill described: {name}",
            "skills": [],
            "skill": registry.describe(name),
            "resource": None,
        }
    if action == "load":
        loaded = registry.load(name)
        return {
            "action": action,
            "message": f"Skill loaded: {name}",
            "skills": [],
            "skill": loaded.model_dump(mode="json"),
            "resource": None,
        }
    if action == "read_resource":
        path = _required_string(arguments, "path")
        return {
            "action": action,
            "message": f"Skill resource loaded: {name}/{path}",
            "skills": [],
            "skill": None,
            "resource": registry.read_resource(name, path),
        }
    raise ValueError("action must be one of: list, search, describe, load, read_resource")


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    resources = dict(context.get("resources") or {})
    try:
        registry = _registry(resources)
        action = str(arguments.get("action") or "").strip()
        if action == "list":
            return ToolRiskResult(action="allow", risk_level="low").model_dump(mode="json")
        if action == "search":
            _required_string(arguments, "query")
            return ToolRiskResult(
                action="allow",
                risk_level="low",
                reasons=["skill search exposes enabled skill metadata only"],
            ).model_dump(mode="json")
        name = _required_string(arguments, "name")
        registry.get(name)
        if action == "describe":
            return ToolRiskResult(
                action="allow",
                risk_level="low",
                reasons=["skill describe exposes metadata and resource index only"],
                facts={"skill": name},
            ).model_dump(mode="json")
        if action == "load":
            return ToolRiskResult(
                action="allow",
                risk_level="medium",
                reasons=["skill load exposes enabled SKILL.md content to the model"],
                facts={"skill": name},
            ).model_dump(mode="json")
        if action == "read_resource":
            path = _required_string(arguments, "path")
            registry.read_resource(name, path)
            return ToolRiskResult(
                action="allow",
                risk_level="medium",
                reasons=["skill resource read is restricted to enabled skill resources"],
                facts={"skill": name, "path": path},
            ).model_dump(mode="json")
        return ToolRiskResult(
            action="deny",
            risk_level="medium",
            reasons=["skill action must be one of: list, search, describe, load, read_resource"],
        ).model_dump(mode="json")
    except Exception as exc:
        return ToolRiskResult(
            action="deny",
            risk_level="medium",
            reasons=[f"skill request is invalid: {type(exc).__name__}: {exc}"],
        ).model_dump(mode="json")


def _registry(resources: dict[str, Any]) -> SkillRegistry:
    payload = resources.get("skills")
    if not isinstance(payload, dict):
        raise ValueError("skills runtime resource is missing")
    return SkillRegistry.from_resource_payload(payload)


def _required_string(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _limit(value: Any) -> int:
    if value is None:
        return 20
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("limit must be an integer")
    return max(1, min(50, value))


def _tool_description(registry: SkillRegistry) -> str:
    lines = [
        "Skill Gateway for enabled skills using progressive disclosure.",
        (
            "Use action=list/search/describe to inspect metadata before loading content. "
            "Use action=load only when the current task needs that SKILL.md body. "
            "Use action=read_resource only for resources explicitly listed by describe/load."
        ),
        (
            "This tool does not execute scripts. If a loaded skill exposes scripts, "
            "execute them through bash so Gateway risk approval still applies."
        ),
        "<available_skills>",
    ]
    for item in registry.list_metadata():
        lines.extend(
            [
                "  <skill>",
                f"    <name>{item.get('name', '')}</name>",
                f"    <description>{item.get('description', '')}</description>",
                "  </skill>",
            ]
        )
    lines.append("</available_skills>")
    return "\n".join(lines)
