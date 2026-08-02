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
        raise ValueError(f"unsupported agent_delegate action: {action}")
    return tool_envelope(output, summary=str(output.get("message") or ""))


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    action = str(arguments.get("action") or "").strip()
    if action in {"start", "cancel"}:
        return ToolRiskResult(
            action="inherit",
            risk_level="medium",
            reasons=["delegation starts or cancels an independent Agent run"],
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="deny", risk_level="medium", reasons=[f"unsupported action: {action}"]
    ).model_dump(mode="json")


def _start(arguments: dict[str, Any], resources: dict[str, Any], store: CollaborationStore) -> dict[str, Any]:
    task_text = _required_text(arguments, "task")
    parent = parent_agent_context(resources, tool_id="agent_delegate")
    package_id = _required_text(arguments, "package_id")
    if package_id == parent.package_id:
        raise ValueError("agent_delegate cannot delegate a task back to the current Agent")
    AgentPackageRepository.from_paths().load(package_id)
    session, parent = create_parent_controlled_session(
        store,
        resources,
        title=f"{package_id}: {task_text[:80]}",
        tool_id="agent_delegate",
        task_kind="delegate",
        context=parent,
    )
    criteria = _string_list(arguments.get("acceptance_criteria"))
    if not criteria:
        raise ValueError("acceptance_criteria must contain at least one item")
    expected_artifacts = _artifact_expectations(arguments.get("expected_artifacts"))
    collaboration_id = str(session["collaboration_id"])
    session = store.create_task(
        collaboration_id,
        {
            "assignee_package_id": package_id,
            "task_text": task_text,
            "delivery_standard": {
                "output_path": PROTOCOL_OUTPUT_PATH,
                "acceptance_criteria": criteria,
            },
            "visible_context": {
                "delivery_protocol": DELIVERY_PROTOCOL,
                "expected_artifacts": expected_artifacts,
                "parent_context": arguments.get("context") if isinstance(arguments.get("context"), dict) else {},
            },
        },
    )
    task = (session.get("tasks") or [])[-1]
    return {
        "action": "start",
        "status": "accepted",
        "delegation_id": collaboration_id,
        "background_task_id": collaboration_id,
        "task_id": task.get("task_id"),
        "package_id": package_id,
        "child_session_id": task.get("assignee_session_id"),
        "message": f"任务已交给 {package_id} 异步执行；完成后会自动交付并唤醒当前会话。",
    }


def _cancel(arguments: dict[str, Any], resources: dict[str, Any], store: CollaborationStore) -> dict[str, Any]:
    delegation_id = _required_text(arguments, "delegation_id")
    session = require_parent_owned_session(store, resources, delegation_id, tool_id="agent_delegate")
    reason = str(arguments.get("reason") or "主 Agent 取消了委派任务。").strip()
    cancelled: list[str] = []
    for task in session.get("tasks") or []:
        if str(task.get("status") or "") in {"completed", "failed", "cancelled"}:
            continue
        task_id = str(task.get("task_id") or "")
        result_payload = task.get("result_payload") if isinstance(task.get("result_payload"), dict) else {}
        store.update_task(
            delegation_id,
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
        "delegation_id": delegation_id,
        "cancelled_task_ids": cancelled,
        "message": f"{reason} 宿主正在停止对应子 Agent 请求。" if cancelled else "没有可取消的委派任务。",
    }


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
