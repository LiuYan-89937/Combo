from __future__ import annotations

from typing import Any

from agent_factory.tooling.skills.registry import SkillRegistry
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolRiskResult, ToolSpec


SKILL_RESOURCE_KEY = "skills"
SKILL_TOOL_ID = "skill"


def build_skill_tool_spec(registry: SkillRegistry) -> ToolSpec:
    actions = ["list", "search", "describe", "load", "list_loaded", "read_resource"]
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
                        "load returns SKILL.md for one active todo. list_loaded returns loaded state. "
                        "read_resource reads one referenced skill resource."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": "Required for describe/load/read_resource. Do not pass this for list/search/list_loaded.",
                },
                "path": {
                    "type": "string",
                    "description": "Required only for read_resource.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["outline", "fragment", "content"],
                    "default": "outline",
                    "description": (
                        "Optional for read_resource. outline returns a compact resource index; "
                        "fragment returns one JSON pointer subtree; content returns truncated raw text."
                    ),
                },
                "pointer": {
                    "type": "string",
                    "description": "JSON pointer required when read_resource mode is fragment, such as /properties/nodes.",
                },
                "current_todo": {
                    "type": "string",
                    "description": "Required for describe/load/list_loaded/read_resource. Use the active todo_id.",
                },
                "reason": {
                    "type": "string",
                    "description": "Required for load. Explain why this skill is needed for the active todo.",
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
                {"properties": {"action": {"const": "describe"}}, "required": ["action", "name", "current_todo"]},
                {"properties": {"action": {"const": "load"}}, "required": ["action", "name", "current_todo", "reason"]},
                {"properties": {"action": {"const": "list_loaded"}}, "required": ["action", "current_todo"]},
                {
                    "properties": {"action": {"const": "read_resource"}},
                    "required": ["action", "name", "path", "current_todo"],
                },
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
                "loaded_state": {"type": ["object", "null"], "additionalProperties": True},
            },
            "required": ["action", "message", "skills", "skill", "resource", "loaded_state"],
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
            "loaded_state": None,
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
            "loaded_state": None,
        }
    if action == "list_loaded":
        current_todo = _required_string(arguments, "current_todo")
        return {
            "action": action,
            "message": f"Loaded skill state for todo: {current_todo}",
            "skills": [],
            "skill": None,
            "resource": None,
            "loaded_state": registry.list_loaded(current_todo=current_todo),
        }
    name = _required_string(arguments, "name")
    if action == "describe":
        current_todo = _required_string(arguments, "current_todo")
        described = registry.describe(name, current_todo=current_todo)
        _persist_registry(resources, registry)
        return {
            "action": action,
            "message": f"Skill described: {name}",
            "skills": [],
            "skill": described,
            "resource": None,
            "loaded_state": registry.list_loaded(current_todo=current_todo),
        }
    if action == "load":
        current_todo = _required_string(arguments, "current_todo")
        reason = _required_string(arguments, "reason")
        loaded = registry.load(name, current_todo=current_todo, reason=reason)
        _persist_registry(resources, registry)
        return {
            "action": action,
            "message": f"Skill loaded: {name}",
            "skills": [],
            "skill": loaded.model_dump(mode="json"),
            "resource": None,
            "loaded_state": registry.list_loaded(current_todo=current_todo),
        }
    if action == "read_resource":
        current_todo = _required_string(arguments, "current_todo")
        path = _required_string(arguments, "path")
        mode = _resource_mode(arguments.get("mode"))
        pointer = str(arguments.get("pointer") or "").strip()
        return {
            "action": action,
            "message": f"Skill resource loaded: {name}/{path} ({mode})",
            "skills": [],
            "skill": None,
            "resource": registry.read_resource(
                name,
                path,
                current_todo=current_todo,
                mode=mode,
                pointer=pointer,
            ),
            "loaded_state": registry.list_loaded(current_todo=current_todo),
        }
    raise ValueError("action must be one of: list, search, describe, load, list_loaded, read_resource")


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
        if action == "list_loaded":
            current_todo = _required_string(arguments, "current_todo")
            return ToolRiskResult(
                action="allow",
                risk_level="low",
                reasons=["skill loaded-state inspection exposes gateway state only"],
                facts={"current_todo": current_todo},
            ).model_dump(mode="json")
        name = _required_string(arguments, "name")
        registry.get(name)
        if action == "describe":
            current_todo = _required_string(arguments, "current_todo")
            return ToolRiskResult(
                action="allow",
                risk_level="low",
                reasons=["skill describe exposes metadata and resource index only"],
                facts={"skill": name, "current_todo": current_todo},
            ).model_dump(mode="json")
        if action == "load":
            current_todo = _required_string(arguments, "current_todo")
            reason = _required_string(arguments, "reason")
            registry.load(name, current_todo=current_todo, reason=reason)
            return ToolRiskResult(
                action="allow",
                risk_level="medium",
                reasons=["skill load exposes one enabled SKILL.md body to the model for the active todo"],
                facts={"skill": name, "current_todo": current_todo, "reason": reason},
            ).model_dump(mode="json")
        if action == "read_resource":
            current_todo = _required_string(arguments, "current_todo")
            path = _required_string(arguments, "path")
            mode = _resource_mode(arguments.get("mode"))
            pointer = str(arguments.get("pointer") or "").strip()
            registry.read_resource(name, path, current_todo=current_todo, mode=mode, pointer=pointer)
            return ToolRiskResult(
                action="allow",
                risk_level="medium",
                reasons=["skill resource read is restricted to enabled skill resources"],
                facts={"skill": name, "path": path, "mode": mode, "current_todo": current_todo},
            ).model_dump(mode="json")
        return ToolRiskResult(
            action="deny",
            risk_level="medium",
            reasons=["skill action must be one of: list, search, describe, load, list_loaded, read_resource"],
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


def _persist_registry(resources: dict[str, Any], registry: SkillRegistry) -> None:
    payload = resources.get("skills")
    if not isinstance(payload, dict):
        raise ValueError("skills runtime resource is missing")
    payload.clear()
    payload.update(registry.to_resource_payload())


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


def _resource_mode(value: Any) -> str:
    mode = str(value or "outline").strip()
    if mode not in {"outline", "fragment", "content"}:
        raise ValueError("mode must be one of: outline, fragment, content")
    return mode


def _tool_description(registry: SkillRegistry) -> str:
    lines = [
        "Skill Gateway for enabled skills using progressive disclosure.",
        (
            "Use action=list/search/describe to inspect metadata before loading content. "
            "Use action=load with current_todo and reason only when the active todo needs that SKILL.md body. "
            "Use action=list_loaded to inspect loaded state. "
            "Use action=read_resource with current_todo only for resources explicitly listed by describe/load. "
            "read_resource defaults to a compact outline; use mode=fragment for a JSON pointer subtree; "
            "use mode=content only when raw text is necessary."
        ),
        (
            "This tool does not execute scripts. If a loaded skill exposes scripts, "
            "execute them through a dedicated allowed execution tool so Gateway risk approval still applies."
        ),
    ]
    lines.append("Call action=list or action=search to inspect available skills for the active todo.")
    return "\n".join(lines)
