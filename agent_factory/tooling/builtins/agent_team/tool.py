from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_factory.collaboration_system.parent_controller import (
    create_parent_controlled_session,
    parent_agent_context,
    require_parent_owned_session,
)
from agent_factory.collaboration_system.result_delivery import DELIVERY_PROTOCOL
from agent_factory.collaboration_system.store import CollaborationStore, resolve_collaboration_store_path
from agent_factory.factory_graph.frontend_bridge.agent_package_repository import AgentPackageRepository
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskResult


PROTOCOL_OUTPUT_PATH = ".agent_delivery/result.json"


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip()
    store = CollaborationStore(_store_path(resources))
    if action == "start":
        output = _start(arguments, resources, store)
    elif action == "cancel":
        output = _cancel(arguments, resources, store)
    else:
        raise ValueError(f"unsupported agent_team action: {action}")
    return tool_envelope(output, summary=str(output.get("message") or ""))


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    action = str(arguments.get("action") or "").strip()
    if action in {"start", "cancel"}:
        return ToolRiskResult(
            action="inherit",
            risk_level="medium",
            reasons=["team delegation starts or cancels multiple independent Agent runs"],
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="deny", risk_level="medium", reasons=[f"unsupported action: {action}"]
    ).model_dump(mode="json")


def _start(arguments: dict[str, Any], resources: dict[str, Any], store: CollaborationStore) -> dict[str, Any]:
    strategy = _required_text(arguments, "strategy")
    tasks = _normalized_tasks(arguments.get("tasks"), strategy=strategy)
    ordered_tasks = _topological_tasks(tasks)
    parent = parent_agent_context(resources, tool_id="agent_team")
    package_repository = AgentPackageRepository.from_paths()
    for task in tasks:
        package_id = task["package_id"]
        if package_id == parent.package_id:
            raise ValueError("agent_team cannot assign the current Agent as its own worker")
        package_repository.load(package_id)
    session, parent = create_parent_controlled_session(
        store,
        resources,
        title=_required_text(arguments, "title"),
        tool_id="agent_team",
        task_kind="team",
        context=parent,
    )
    team_id = str(session["collaboration_id"])
    task_ids: dict[str, str] = {}
    for task in ordered_tasks:
        session = store.create_task(
            team_id,
            {
                "assignee_package_id": task["package_id"],
                "task_text": task["task"],
                "depends_on": [task_ids[key] for key in task["depends_on"]],
                "delivery_standard": {
                    "output_path": PROTOCOL_OUTPUT_PATH,
                    "acceptance_criteria": task["acceptance_criteria"],
                },
                "visible_context": {
                    "delivery_protocol": DELIVERY_PROTOCOL,
                    "team_strategy": strategy,
                    "task_key": task["task_key"],
                    "expected_artifacts": task["expected_artifacts"],
                    "parent_context": task["context"],
                },
            },
        )
        created = (session.get("tasks") or [])[-1]
        task_ids[task["task_key"]] = str(created.get("task_id") or "")
    return {
        "action": "start",
        "status": "accepted",
        "team_id": team_id,
        "background_task_id": team_id,
        "strategy": strategy,
        "tasks": [
            {
                "task_key": task["task_key"],
                "task_id": task_ids[task["task_key"]],
                "package_id": task["package_id"],
                "depends_on": task["depends_on"],
            }
            for task in tasks
        ],
        "message": f"已组建 {len(tasks)} 个子 Agent 的{('讨论' if strategy == 'discussion' else '交付')}团队；状态变化会自动回到当前会话。",
    }


def _cancel(arguments: dict[str, Any], resources: dict[str, Any], store: CollaborationStore) -> dict[str, Any]:
    team_id = _required_text(arguments, "team_id")
    session = require_parent_owned_session(store, resources, team_id, tool_id="agent_team")
    reason = str(arguments.get("reason") or "主 Agent 取消了团队任务。").strip()
    cancelled: list[str] = []
    for task in session.get("tasks") or []:
        if str(task.get("status") or "") in {"completed", "failed", "cancelled"}:
            continue
        task_id = str(task.get("task_id") or "")
        result_payload = task.get("result_payload") if isinstance(task.get("result_payload"), dict) else {}
        store.update_task(
            team_id,
            task_id,
            {
                "status": "cancelled",
                "result_summary": reason,
                "review_notes": reason,
                "result_payload": {
                    **result_payload,
                    "runtime_status": "cancelled",
                    "cancellation_requested": True,
                },
            },
        )
        cancelled.append(task_id)
    return {
        "action": "cancel",
        "status": "cancelled" if cancelled else "unchanged",
        "team_id": team_id,
        "cancelled_task_ids": cancelled,
        "message": f"{reason} 宿主正在停止对应子 Agent 请求。" if cancelled else "没有可取消的团队任务。",
    }


def _normalized_tasks(value: Any, *, strategy: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) < 2:
        raise ValueError("agent_team requires at least two tasks")
    tasks: list[dict[str, Any]] = []
    keys: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("agent_team task must be an object")
        task_key = _required_text(item, "task_key")
        if task_key in keys:
            raise ValueError(f"duplicate team task_key: {task_key}")
        keys.add(task_key)
        depends_on = _string_list(item.get("depends_on"))
        if strategy == "discussion" and depends_on:
            raise ValueError("discussion tasks must be independent and cannot declare depends_on")
        criteria = _string_list(item.get("acceptance_criteria"))
        if not criteria:
            raise ValueError(f"team task {task_key} requires acceptance_criteria")
        tasks.append(
            {
                "task_key": task_key,
                "package_id": _required_text(item, "package_id"),
                "task": _required_text(item, "task"),
                "acceptance_criteria": criteria,
                "depends_on": depends_on,
                "expected_artifacts": _artifact_expectations(item.get("expected_artifacts")),
                "context": item.get("context") if isinstance(item.get("context"), dict) else {},
            }
        )
    missing = sorted({dependency for task in tasks for dependency in task["depends_on"] if dependency not in keys})
    if missing:
        raise ValueError("unknown team task dependencies: " + ", ".join(missing))
    return tasks


def _topological_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {task["task_key"]: task for task in tasks}
    pending = set(by_key)
    ordered: list[dict[str, Any]] = []
    completed: set[str] = set()
    while pending:
        ready = sorted(key for key in pending if set(by_key[key]["depends_on"]) <= completed)
        if not ready:
            raise ValueError("agent_team task dependency graph contains a cycle")
        for key in ready:
            ordered.append(by_key[key])
            completed.add(key)
            pending.remove(key)
    return ordered


def _store_path(resources: dict[str, Any]) -> Path:
    root = Path(_required_text(resources, "collaboration_root")).expanduser()
    return resolve_collaboration_store_path(root / "factory.sqlite")


def _required_text(values: dict[str, Any], key: str) -> str:
    text = str(values.get(key) or "").strip()
    if not text:
        raise ValueError(f"{key} is required")
    return text


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(text for item in value if (text := str(item or "").strip())))


def _artifact_expectations(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return [
        {
            "description": str(item.get("description") or "").strip(),
            **(
                {"suggested_name": suggested}
                if (suggested := str(item.get("suggested_name") or "").strip())
                else {}
            ),
        }
        for item in value
        if isinstance(item, dict) and str(item.get("description") or "").strip()
    ]
