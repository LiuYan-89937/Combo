from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_factory.collaboration_system.background_tasks import (
    get_background_task,
    list_background_tasks,
)
from agent_factory.collaboration_system.parent_controller import parent_agent_context
from agent_factory.collaboration_system.store import CollaborationStore, resolve_collaboration_store_path
from agent_factory.tooling.envelope import tool_envelope


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip()
    parent = parent_agent_context(resources, tool_id="background_tasks")
    store = CollaborationStore(_store_path(resources))
    if action == "list":
        tasks = list_background_tasks(store, parent_session_id=parent.session_id)
        output = {
            "action": "list",
            "tasks": tasks,
            "count": len(tasks),
            "message": f"已读取当前对话的 {len(tasks)} 个后台任务。",
        }
    elif action == "get":
        task_id = _required_text(arguments, "background_task_id")
        output = {
            "action": "get",
            "task": get_background_task(store, task_id, parent_session_id=parent.session_id),
            "message": "后台任务详情已读取。",
        }
    else:
        raise ValueError(f"unsupported background_tasks action: {action}")
    return tool_envelope(output, summary=output["message"])


def _store_path(resources: dict[str, Any]) -> Path:
    root = Path(_required_text(resources, "collaboration_root")).expanduser()
    return resolve_collaboration_store_path(root / "factory.sqlite")


def _required_text(values: dict[str, Any], key: str) -> str:
    text = str(values.get(key) or "").strip()
    if not text:
        raise ValueError(f"{key} is required")
    return text
