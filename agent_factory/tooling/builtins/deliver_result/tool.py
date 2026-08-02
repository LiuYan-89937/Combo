from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_factory.collaboration_system.result_delivery import DELIVERY_PROTOCOL, commit_agent_result
from agent_factory.collaboration_system.store import CollaborationStore, resolve_collaboration_store_path
from agent_factory.tooling.envelope import tool_envelope
from agent_factory.tooling.spec import ToolRiskResult


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    context, identity = _delegation_identity(resources)
    collaboration_id = _required_text(context, "collaboration_id")
    task_id = _required_text(context, "task_id")
    store = CollaborationStore(_store_path(resources))
    session = store.get_session(collaboration_id)
    task = _task_by_id(session, task_id)
    _validate_child_identity(task, identity, context)
    existing_payload = task.get("result_payload") if isinstance(task.get("result_payload"), dict) else {}
    existing_delivery = existing_payload.get("delivery_protocol")
    if isinstance(existing_delivery, dict) and existing_delivery.get("protocol") == DELIVERY_PROTOCOL:
        output = {
            "status": "already_delivered",
            "delegation_id": collaboration_id,
            "task_id": task_id,
            "delivery": existing_delivery,
            "artifacts": task.get("artifact_refs") or [],
            "message": "当前任务已经完成正式交付，本次调用按幂等结果返回。",
        }
        return tool_envelope(output, summary=output["message"])
    execution_config = session.get("execution_config") if isinstance(session.get("execution_config"), dict) else {}
    if execution_config.get("delivery_protocol") != DELIVERY_PROTOCOL:
        raise ValueError("current collaboration task does not use the Agent delivery protocol")
    parent_workspace = Path(_required_text(execution_config, "parent_workspace_root"))
    child_workspace = Path(_required_text(resources, "workdir_root"))
    status = _required_text(arguments, "status")
    summary = _required_text(arguments, "summary")
    commit = commit_agent_result(
        parent_workspace=parent_workspace,
        child_workspace=child_workspace,
        task_id=task_id,
        package_id=str(task.get("assignee_package_id") or ""),
        child_session_id=str(identity.get("session_id") or ""),
        status=status,
        summary=summary,
        artifacts=_artifact_list(arguments.get("artifacts")),
        key_findings=_string_list(arguments.get("key_findings")),
        remaining_issues=_string_list(arguments.get("remaining_issues")),
        recommended_next_actions=_string_list(arguments.get("recommended_next_actions")),
    )
    task_status = {
        "completed": "submitted",
        "partial": "submitted",
        "blocked": "blocked",
        "failed": "failed",
    }[status]
    protocol_payload = {
        "protocol": DELIVERY_PROTOCOL,
        "delivery_id": commit.delivery_id,
        "bundle_path": commit.bundle_path,
        "reported_status": status,
        "summary": summary,
        "key_findings": _string_list(arguments.get("key_findings")),
        "remaining_issues": _string_list(arguments.get("remaining_issues")),
        "recommended_next_actions": _string_list(arguments.get("recommended_next_actions")),
    }
    delivery_validation = {
        "passed": True,
        "protocol": DELIVERY_PROTOCOL,
        "expected_output_paths": [str(item.get("path") or "") for item in commit.artifact_refs],
        "delivered_output_paths": [str(item.get("path") or "") for item in commit.artifact_refs],
        "missing_output_paths": [],
        "unchanged_output_paths": [],
        "empty_output_paths": [],
        "errors": [],
    }
    store.update_task(
        collaboration_id,
        task_id,
        {
            "status": task_status,
            "result_summary": summary,
            "result_payload": {
                **existing_payload,
                "delivery_protocol": protocol_payload,
                "delivery_validation": delivery_validation,
            },
            "artifact_refs": commit.artifact_refs,
        },
    )
    store.record_message(
        collaboration_id,
        speaker_type="worker_agent",
        speaker_package_id=str(task.get("assignee_package_id") or "") or None,
        message_kind="delivery",
        content=f"子 Agent 已通过 {DELIVERY_PROTOCOL} 正式交付：{summary}",
        task_id=task_id,
        event_ref=f"agent-delivery:{commit.delivery_id}",
    )
    output = {
        "status": "delivered",
        "delegation_id": collaboration_id,
        "task_id": task_id,
        "task_status": task_status,
        "delivery": protocol_payload,
        "artifacts": commit.artifact_refs,
        "message": "交付已事务式写入父 Agent 工作区，结构化报告将在本轮结束后发送给父 Agent。",
    }
    return tool_envelope(output, summary=output["message"])


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    del context
    if not str(arguments.get("summary") or "").strip():
        return ToolRiskResult(
            action="deny", risk_level="low", reasons=["deliver_result requires summary"]
        ).model_dump(mode="json")
    return ToolRiskResult(
        action="allow",
        risk_level="low",
        reasons=["delivery is scoped to the authenticated parent-child run relationship"],
    ).model_dump(mode="json")


def _delegation_identity(resources: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    execution = resources.get("runtime_execution_config")
    if not isinstance(execution, dict):
        raise ValueError("deliver_result requires runtime execution context")
    user_config = execution.get("user_config")
    identity = execution.get("identity")
    context = user_config.get("delegation_context") if isinstance(user_config, dict) else None
    if not isinstance(context, dict) or not isinstance(identity, dict):
        raise ValueError("deliver_result is only available in a delegated child run")
    return context, identity


def _validate_child_identity(
    task: dict[str, Any],
    identity: dict[str, Any],
    context: dict[str, Any],
) -> None:
    expected_session = str(task.get("assignee_session_id") or "").strip()
    actual_session = str(identity.get("session_id") or "").strip()
    expected_package = str(task.get("assignee_package_id") or "").strip()
    actual_package = str(context.get("child_package_id") or "").strip()
    if not expected_session or expected_session != actual_session:
        raise PermissionError("delegated child session does not match the assigned task")
    if expected_package and expected_package != actual_package:
        raise PermissionError("delegated child package does not match the assigned task")


def _task_by_id(session: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in session.get("tasks") or []:
        if str(task.get("task_id") or "") == task_id:
            return task
    raise LookupError(f"delegated task not found: {task_id}")


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


def _artifact_list(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    return [
        {
            "path": str(item.get("path") or "").strip(),
            "description": str(item.get("description") or "").strip(),
        }
        for item in value
        if isinstance(item, dict)
    ]
