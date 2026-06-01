from __future__ import annotations

from typing import Any

from agent_factory.create_agent.models import CreateAgentAction
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolRiskResult, ToolSpec


CREATE_AGENT_CONTROL_TOOL_ID = "create_agent_control"
CREATE_AGENT_WORKSPACE_RESOURCE = "create_agent_workspace"


def build_create_agent_control_tool_spec() -> ToolSpec:
    return ToolSpec(
        id=CREATE_AGENT_CONTROL_TOOL_ID,
        description=(
            "Control the create-agent manufacturing loop. Use this instead of editing "
            ".factory/action.json directly when asking the user, continuing, or finalizing."
        ),
        entrypoint="agent_factory.create_agent.control_tool:run",
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["continue", "ask_user", "finalize"],
                    "description": "The next create-agent control action.",
                },
                "message": {
                    "type": "string",
                    "description": "Natural-language user question or finalization summary.",
                },
                "resource_facts": {
                    "type": "array",
                    "items": _resource_fact_schema(),
                    "default": [],
                    "description": "Optional resource facts already established by the conversation.",
                },
            },
            "required": ["action"],
            "oneOf": [
                {"properties": {"action": {"const": "continue"}}, "required": ["action"]},
                {"properties": {"action": {"const": "ask_user"}}, "required": ["action", "message"]},
                {"properties": {"action": {"const": "finalize"}}, "required": ["action"]},
            ],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["continue", "ask_user", "finalize"]},
                "message": {"type": "string"},
                "action_path": {"type": "string"},
                "resource_fact_count": {"type": "integer"},
            },
            "required": ["action", "message", "action_path", "resource_fact_count"],
            "additionalProperties": False,
        },
        resources={"workspace": CREATE_AGENT_WORKSPACE_RESOURCE},
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard="agent_factory.create_agent.control_tool:evaluate_risk"),
        concurrent=False,
    )


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    workspace = _workspace(resources)
    action = CreateAgentAction.model_validate(
        {
            "action": arguments.get("action"),
            "message": str(arguments.get("message") or "").strip(),
            "resource_facts": arguments.get("resource_facts") or [],
        }
    )
    if action.action == "ask_user" and not action.message.strip():
        raise ValueError("message is required when action is ask_user")
    workspace.write_action(action)
    return {
        "action": action.action,
        "message": action.message,
        "action_path": str(workspace.action_path),
        "resource_fact_count": len(action.resource_facts),
    }


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    try:
        action = str(arguments.get("action") or "").strip()
        if action not in {"continue", "ask_user", "finalize"}:
            raise ValueError("action must be one of: continue, ask_user, finalize")
        message = str(arguments.get("message") or "").strip()
        if action == "ask_user" and not message:
            raise ValueError("message is required when action is ask_user")
        CreateAgentAction.model_validate(
            {
                "action": action,
                "message": message,
                "resource_facts": arguments.get("resource_facts") or [],
            }
        )
    except Exception as exc:
        return ToolRiskResult(
            action="deny",
            risk_level="low",
            reasons=[f"invalid create-agent control action: {type(exc).__name__}: {exc}"],
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="allow",
        risk_level="low",
        reasons=["create-agent control action is schema-validated"],
        facts={"action": action},
    ).model_dump(mode="json")


def _workspace(resources: dict[str, Any]) -> CreateAgentWorkspace:
    raw = resources.get("workspace")
    if isinstance(raw, str):
        return CreateAgentWorkspace(raw)
    if isinstance(raw, dict) and isinstance(raw.get("root"), str):
        return CreateAgentWorkspace(raw["root"])
    raise ValueError("create_agent workspace resource is missing")


def _resource_fact_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "value": {},
            "secret": {"type": "boolean", "default": False},
            "source": {
                "type": "string",
                "enum": ["user", "tool", "mcp", "skill", "default", "system"],
                "default": "user",
            },
            "confidence": {"type": "number", "default": 1.0},
            "evidence_refs": {"type": "array", "items": {"type": "string"}, "default": []},
        },
        "required": ["key"],
        "additionalProperties": False,
    }
