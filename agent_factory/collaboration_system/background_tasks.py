from __future__ import annotations

from typing import Any

from agent_factory.collaboration_system.background_task_contract import (
    BACKGROUND_TASK_KINDS,
    normalize_background_task_metadata,
)
from agent_factory.collaboration_system.store import CollaborationStore, CollaborationStoreError


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_STATUSES = {"requested", "running", "resume_requested", "assigned", "queued", "accepted", "planning", "working"}


class BackgroundTaskAccessError(PermissionError):
    pass


def list_background_tasks(
    store: CollaborationStore,
    *,
    parent_session_id: str,
) -> list[dict[str, Any]]:
    return [
        background_task_view(store.get_session(str(session["collaboration_id"])))
        for session in store.list_sessions()
        if _belongs_to_parent(session, parent_session_id=parent_session_id)
        and _background_task_metadata(session) is not None
    ]


def get_background_task(
    store: CollaborationStore,
    background_task_id: str,
    *,
    parent_session_id: str,
) -> dict[str, Any]:
    try:
        session = store.get_session(background_task_id)
    except CollaborationStoreError as exc:
        raise LookupError(f"background task not found: {background_task_id}") from exc
    if not _belongs_to_parent(session, parent_session_id=parent_session_id):
        raise BackgroundTaskAccessError("background task does not belong to the current conversation")
    if _background_task_metadata(session) is None:
        raise LookupError(f"background task not found: {background_task_id}")
    return background_task_view(session)


def background_task_view(session: dict[str, Any]) -> dict[str, Any]:
    metadata = _background_task_metadata(session)
    if metadata is None:
        raise ValueError("collaboration session is not a background task")
    tasks = [item for item in session.get("tasks") or [] if isinstance(item, dict)]
    manufacturing = [item for item in session.get("manufacturing_requests") or [] if isinstance(item, dict)]
    evolutions = [item for item in session.get("evolution_requests") or [] if isinstance(item, dict)]
    status = _unified_status(session, tasks=tasks, manufacturing=manufacturing, evolutions=evolutions)
    return {
        "background_task_id": str(session.get("collaboration_id") or ""),
        "kind": metadata["kind"],
        "title": str(session.get("title") or "后台任务"),
        "status": status,
        "current_phase": _current_phase(session, status=status),
        "participants": _participants(tasks, manufacturing=manufacturing, evolutions=evolutions),
        "subtasks": [_subtask_view(task) for task in tasks],
        "recent_activity": _recent_activity(session.get("messages")),
        "artifacts": _artifacts(tasks, manufacturing=manufacturing, evolutions=evolutions),
        "pending_action": _pending_action(session, tasks=tasks, evolutions=evolutions),
        "error": _error(tasks, manufacturing=manufacturing, evolutions=evolutions),
        "started_at": session.get("started_at") or session.get("created_at"),
        "updated_at": session.get("updated_at"),
    }


def maybe_background_task_view(session: dict[str, Any]) -> dict[str, Any] | None:
    return background_task_view(session) if _background_task_metadata(session) is not None else None


def _background_task_metadata(session: dict[str, Any]) -> dict[str, str] | None:
    execution_config = session.get("execution_config")
    background_task = execution_config.get("background_task") if isinstance(execution_config, dict) else None
    if not isinstance(background_task, dict):
        return None
    kind = str(background_task.get("kind") or "").strip()
    if kind not in BACKGROUND_TASK_KINDS:
        return None
    try:
        return normalize_background_task_metadata(background_task)
    except ValueError:
        return None


def _belongs_to_parent(session: dict[str, Any], *, parent_session_id: str) -> bool:
    return str(session.get("main_agent_package_session_id") or "").strip() == parent_session_id


def _unified_status(
    session: dict[str, Any],
    *,
    tasks: list[dict[str, Any]],
    manufacturing: list[dict[str, Any]],
    evolutions: list[dict[str, Any]],
) -> str:
    runtime_status = str(session.get("runtime_status") or "")
    if runtime_status == "waiting_for_approval":
        return "waiting_approval"
    if runtime_status == "waiting_for_input":
        return "waiting_input"
    if runtime_status == "waiting_for_dependency":
        return "waiting_dependency"
    statuses = [str(item.get("status") or "") for item in [*tasks, *manufacturing, *evolutions]]
    if any(status in ACTIVE_STATUSES for status in statuses):
        return "running"
    if any(status == "blocked" for status in statuses):
        return "waiting_input"
    if statuses and all(status == "cancelled" for status in statuses):
        return "cancelled"
    if any(status == "failed" for status in statuses):
        return "failed"
    if statuses and all(status in TERMINAL_STATUSES for status in statuses):
        return "completed"
    session_status = str(session.get("status") or "")
    return session_status if session_status in TERMINAL_STATUSES else "queued"


def _current_phase(session: dict[str, Any], *, status: str) -> str:
    runtime_status = str(session.get("runtime_status") or "").strip()
    if runtime_status:
        return runtime_status
    return status


def _participants(
    tasks: list[dict[str, Any]],
    *,
    manufacturing: list[dict[str, Any]],
    evolutions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    participants: dict[str, dict[str, Any]] = {}
    for task in tasks:
        package_id = str(task.get("assignee_package_id") or "").strip()
        if package_id:
            participants[package_id] = {"package_id": package_id, "status": task.get("status")}
    for request in evolutions:
        package_id = str(request.get("package_id") or "").strip()
        if package_id:
            participants[package_id] = {"package_id": package_id, "status": request.get("status")}
    for request in manufacturing:
        name = str(request.get("agent_name") or "").strip()
        if name:
            participants[f"manufacturing:{request.get('request_id')}"] = {
                "name": name,
                "status": request.get("status"),
            }
    return list(participants.values())


def _subtask_view(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": task.get("task_id"),
        "package_id": task.get("assignee_package_id"),
        "title": task.get("task_text"),
        "status": task.get("status"),
        "summary": task.get("result_summary"),
        "depends_on": task.get("depends_on") or [],
    }


def _recent_activity(value: Any) -> list[dict[str, Any]]:
    messages = [item for item in value or [] if isinstance(item, dict)]
    allowed = {
        "progress", "manufacturing_requested", "manufacturing_running", "manufacturing_blocked",
        "manufacturing_completed", "manufacturing_failed", "evolution_requested", "evolution_running",
        "evolution_blocked", "evolution_completed", "evolution_failed", "delivery", "final_delivery",
    }
    return [
        {
            "id": item.get("message_id"),
            "kind": item.get("message_kind"),
            "content": item.get("content"),
            "created_at": item.get("created_at"),
        }
        for item in messages
        if str(item.get("message_kind") or "") in allowed
    ][-12:]


def _artifacts(
    tasks: list[dict[str, Any]],
    *,
    manufacturing: list[dict[str, Any]],
    evolutions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for task in tasks:
        values.extend(item for item in task.get("artifact_refs") or [] if isinstance(item, dict))
    for request in [*manufacturing, *evolutions]:
        result = request.get("result_payload") if isinstance(request.get("result_payload"), dict) else {}
        values.extend(item for item in result.get("artifacts") or [] if isinstance(item, dict))
    unique: dict[str, dict[str, Any]] = {}
    for item in values:
        key = str(item.get("path") or item.get("id") or item)
        unique[key] = item
    return list(unique.values())


def _pending_action(
    session: dict[str, Any],
    *,
    tasks: list[dict[str, Any]],
    evolutions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for task in tasks:
        payload = task.get("result_payload") if isinstance(task.get("result_payload"), dict) else {}
        pending = payload.get("pending_interrupt")
        if str(task.get("status") or "") == "blocked" and isinstance(pending, dict):
            return {"type": "approval_or_input", "task_id": task.get("task_id"), "payload": pending}
    for request in evolutions:
        payload = request.get("result_payload") if isinstance(request.get("result_payload"), dict) else {}
        pending = payload.get("pending_interrupt")
        if str(request.get("status") or "") == "blocked" and isinstance(pending, dict):
            return {"type": "approval_or_input", "request_id": request.get("request_id"), "payload": pending}
    runtime_payload = session.get("runtime_status_payload")
    return runtime_payload if isinstance(runtime_payload, dict) and runtime_payload else None


def _error(
    tasks: list[dict[str, Any]],
    *,
    manufacturing: list[dict[str, Any]],
    evolutions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for item in [*tasks, *manufacturing, *evolutions]:
        if str(item.get("status") or "") != "failed":
            continue
        payload = item.get("result_payload") if isinstance(item.get("result_payload"), dict) else {}
        message = str(payload.get("error") or item.get("result_summary") or item.get("message") or "任务失败")
        return {"message": message}
    return None
