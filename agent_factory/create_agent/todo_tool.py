from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agent_factory.create_agent.control_tool import CREATE_AGENT_WORKSPACE_RESOURCE
from agent_factory.create_agent.models import TodoItem, TodoList, TodoStatus
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolRiskResult, ToolSpec


CREATE_AGENT_TODO_TOOL_ID = "create_agent_todo"


def build_create_agent_todo_tool_spec() -> ToolSpec:
    return ToolSpec(
        id=CREATE_AGENT_TODO_TOOL_ID,
        description=(
            "Manage the create-agent manufacturing todo list through schema-validated actions. "
            "Use this instead of editing .factory/todo.json directly."
        ),
        entrypoint="agent_factory.create_agent.todo_tool:run",
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "add", "update", "upsert"],
                    "description": "Todo action to perform.",
                },
                "todo_id": {"type": "string", "description": "Required for update; optional stable id for add/upsert."},
                "title": {"type": "string", "description": "Todo title for add/upsert or title update."},
                "kind": {
                    "type": "string",
                    "enum": ["plan", "write", "verify", "repair", "question"],
                    "description": "Todo kind.",
                },
                "status": {
                    "type": "string",
                    "enum": [item.value for item in TodoStatus],
                    "description": "Todo status.",
                },
                "required": {"type": "boolean", "description": "Whether this todo is required for finalization."},
                "target_files": {"type": "array", "items": {"type": "string"}, "description": "Related package files."},
                "acceptance": {"type": "string", "description": "Evidence-based acceptance condition."},
                "source": {"type": "string", "description": "Source of the todo."},
                "details": {"type": "object", "additionalProperties": True, "description": "Structured details."},
                "evidence": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Evidence notes for status changes or completion.",
                },
            },
            "required": ["action"],
            "oneOf": [
                {"properties": {"action": {"const": "list"}}, "required": ["action"]},
                {"properties": {"action": {"const": "add"}}, "required": ["action", "title"]},
                {"properties": {"action": {"const": "update"}}, "required": ["action", "todo_id"]},
                {"properties": {"action": {"const": "upsert"}}, "required": ["action", "todo_id", "title"]},
            ],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "add", "update", "upsert"]},
                "message": {"type": "string"},
                "todo": {"type": "object", "additionalProperties": True},
                "item": {"type": ["object", "null"], "additionalProperties": True},
            },
            "required": ["action", "message", "todo", "item"],
            "additionalProperties": False,
        },
        resources={"workspace": CREATE_AGENT_WORKSPACE_RESOURCE},
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard="agent_factory.create_agent.todo_tool:evaluate_risk"),
        concurrent=False,
    )


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    workspace = _workspace(resources)
    todo = workspace.read_todo()
    action = str(arguments.get("action") or "").strip()
    if action == "list":
        return _output(action=action, message="Current create-agent todo list.", todo=todo, item=None)
    if action == "add":
        item = _item_from_arguments(arguments)
        todo = _write_items(workspace, todo, [*todo.items, item])
        return _output(action=action, message=f"Todo added: {item.todo_id}", todo=todo, item=item)
    if action == "update":
        todo_id = _required_string(arguments, "todo_id")
        items, item = _update_item(todo.items, todo_id=todo_id, arguments=arguments)
        todo = _write_items(workspace, todo, items)
        return _output(action=action, message=f"Todo updated: {todo_id}", todo=todo, item=item)
    if action == "upsert":
        todo_id = _required_string(arguments, "todo_id")
        if any(item.todo_id == todo_id for item in todo.items):
            items, item = _update_item(todo.items, todo_id=todo_id, arguments=arguments)
        else:
            item = _item_from_arguments(arguments)
            items = [*todo.items, item]
        todo = _write_items(workspace, todo, items)
        return _output(action=action, message=f"Todo upserted: {todo_id}", todo=todo, item=item)
    raise ValueError("action must be one of: list, add, update, upsert")


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    try:
        action = str(arguments.get("action") or "").strip()
        if action == "list":
            return ToolRiskResult(action="allow", risk_level="low").model_dump(mode="json")
        if action == "add":
            _item_from_arguments(arguments)
        elif action == "update":
            _required_string(arguments, "todo_id")
            _update_payload(arguments)
        elif action == "upsert":
            _required_string(arguments, "todo_id")
            _item_from_arguments(arguments)
        else:
            raise ValueError("action must be one of: list, add, update, upsert")
    except Exception as exc:
        return ToolRiskResult(
            action="deny",
            risk_level="low",
            reasons=[f"invalid create-agent todo action: {type(exc).__name__}: {exc}"],
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="allow",
        risk_level="low",
        reasons=["create-agent todo action is schema-validated"],
        facts={"action": action},
    ).model_dump(mode="json")


def _workspace(resources: dict[str, Any]) -> CreateAgentWorkspace:
    raw = resources.get("workspace")
    if isinstance(raw, str):
        return CreateAgentWorkspace(raw)
    if isinstance(raw, dict) and isinstance(raw.get("root"), str):
        return CreateAgentWorkspace(raw["root"])
    raise ValueError("create_agent workspace resource is missing")


def _item_from_arguments(arguments: dict[str, Any]) -> TodoItem:
    payload: dict[str, Any] = {
        "title": _required_string(arguments, "title"),
    }
    for key in ("todo_id", "kind", "status", "required", "target_files", "acceptance", "source", "details"):
        if key in arguments and arguments.get(key) is not None:
            payload[key] = arguments[key]
    payload["details"] = _details_with_evidence(payload.get("details"), arguments.get("evidence"))
    return TodoItem.model_validate(payload)


def _update_item(items: list[TodoItem], *, todo_id: str, arguments: dict[str, Any]) -> tuple[list[TodoItem], TodoItem]:
    payload = _update_payload(arguments)
    updated: list[TodoItem] = []
    target: TodoItem | None = None
    for item in items:
        if item.todo_id != todo_id:
            updated.append(item)
            continue
        details = payload.get("details", item.details)
        payload["details"] = _details_with_evidence(details, arguments.get("evidence"))
        target_payload = item.model_dump(mode="json")
        target_payload.update(payload)
        target = TodoItem.model_validate(target_payload)
        updated.append(target)
    if target is None:
        raise KeyError(f"unknown todo_id: {todo_id}")
    return updated, target


def _update_payload(arguments: dict[str, Any]) -> dict[str, Any]:
    allowed = ("title", "kind", "status", "required", "target_files", "acceptance", "source", "details")
    payload = {key: arguments[key] for key in allowed if key in arguments and arguments.get(key) is not None}
    if not payload and arguments.get("evidence") is None:
        raise ValueError("update requires at least one todo field or evidence")
    return payload


def _details_with_evidence(details: Any, evidence: Any) -> dict[str, Any]:
    payload = dict(details) if isinstance(details, dict) else {}
    if evidence is None:
        return payload
    if not isinstance(evidence, list) or not all(isinstance(item, str) and item.strip() for item in evidence):
        raise ValueError("evidence must be an array of non-empty strings")
    existing = payload.get("evidence", [])
    if not isinstance(existing, list):
        existing = [str(existing)]
    payload["evidence"] = [*existing, *[item.strip() for item in evidence]]
    return payload


def _write_items(workspace: CreateAgentWorkspace, todo: TodoList, items: list[TodoItem]) -> TodoList:
    updated = todo.model_copy(update={"items": items, "updated_at": datetime.now(UTC).isoformat()})
    updated = TodoList.model_validate(updated.model_dump(mode="json"))
    workspace.write_todo(updated)
    return updated


def _output(*, action: str, message: str, todo: TodoList, item: TodoItem | None) -> dict[str, Any]:
    return {
        "action": action,
        "message": message,
        "todo": todo.model_dump(mode="json"),
        "item": item.model_dump(mode="json") if item is not None else None,
    }


def _required_string(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()
