from __future__ import annotations

import os
import mimetypes
from pathlib import Path
from typing import Any

from agent_factory.collaboration_system.store import CollaborationStore, resolve_collaboration_store_path
from agent_factory.document_processing import SUPPORTED_FILE_EXTENSIONS, parse_file
from agent_factory.tooling.envelope import runtime_wait_evidence, tool_envelope
from agent_factory.tooling.spec import ToolRiskResult


COLLABORATION_ROOT_ENV = "AGENTFACTORY_COLLABORATION_ROOT"
ACTIVE_TASK_STATUSES = {"assigned", "queued", "accepted", "planning", "working", "revision_requested"}
IMMEDIATE_ATTENTION_TASK_STATUSES = {"submitted", "blocked", "failed"}


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    output = _run_action(arguments, resources)
    evidence = (
        runtime_wait_evidence(
            status="waiting_for_workers",
            reason="collaboration workers are still running",
        )
        if output.get("status") == "deferred"
        else None
    )
    return tool_envelope(output, evidence=evidence, summary=str(output.get("message") or ""))


def _run_action(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip()
    collaboration_id = _required_text(arguments, "collaboration_id")
    store = CollaborationStore(_store_path(resources))
    if action == "inspect":
        session = store.get_session(collaboration_id)
        gate = _inspect_gate(session)
        if gate is not None:
            return gate
        return {
            "action": action,
            "status": "completed",
            "message": "协作会话状态已读取。",
            "session": _session_state_view(session),
        }
    if action == "create_task":
        session = store.create_task(collaboration_id, _task_payload(arguments))
        task = (session.get("tasks") or [])[-1] if session.get("tasks") else {}
        return {
            "action": action,
            "status": "completed",
            "message": "子任务已创建。宿主协作调度器会启动依赖已满足的任务。",
            "session": _session_state_view(session),
            "task": _task_state_view(task),
            "dispatch_hint": "任务已进入协作队列；依赖满足后可由 dispatch-ready 或右侧任务启动按钮调度 worker。",
        }
    if action == "update_task":
        task_id = _required_text(arguments, "task_id")
        session = store.update_task(collaboration_id, task_id, _task_update_payload(arguments))
        task = next((item for item in session.get("tasks") or [] if item.get("task_id") == task_id), {})
        return {
            "action": action,
            "status": "completed",
            "message": "子任务已更新。",
            "session": _session_state_view(session),
            "task": _task_state_view(task),
        }
    if action == "cancel_task":
        task_id = _required_text(arguments, "task_id")
        session = store.get_session(collaboration_id)
        task = next((item for item in session.get("tasks") or [] if item.get("task_id") == task_id), {})
        result_payload = task.get("result_payload") if isinstance(task.get("result_payload"), dict) else {}
        notes = str(arguments.get("review_notes") or arguments.get("result_summary") or "主 Agent 停止了该子任务。").strip()
        session = store.update_task(
            collaboration_id,
            task_id,
            {
                "status": "cancelled",
                "review_notes": notes,
                "result_summary": notes,
                "result_payload": {
                    **result_payload,
                    "runtime_status": "cancelled",
                    "cancellation_requested": True,
                },
            },
        )
        task = next((item for item in session.get("tasks") or [] if item.get("task_id") == task_id), {})
        return {
            "action": action,
            "status": "completed",
            "message": "子任务已标记停止；宿主协作服务会取消对应 worker 请求。",
            "session": _session_state_view(session),
            "task": _task_state_view(task),
        }
    if action == "read_shared":
        path = _safe_shared_path(store.session_workdir(collaboration_id), _required_text(arguments, "path"))
        if not path.is_file():
            raise FileNotFoundError(f"shared workspace file not found: {arguments.get('path')}")
        max_chars = int(arguments.get("max_chars") or 20000)
        return {
            "action": action,
            "status": "completed",
            "message": "共享工作区文件已读取。",
            "path": str(arguments.get("path") or ""),
            "content": _shared_artifact_text(path, store.session_workdir(collaboration_id), max_chars=max_chars),
        }
    if action == "read_task_artifacts":
        task_id = _required_text(arguments, "task_id")
        session = store.get_session(collaboration_id)
        task = _task_by_id(session, task_id)
        max_chars = int(arguments.get("max_chars") or 20000)
        requested_path = str(arguments.get("path") or "").strip() or None
        artifacts = _read_task_artifacts(
            task=task,
            root=store.session_workdir(collaboration_id),
            requested_path=requested_path,
            max_chars=max_chars,
        )
        return {
            "action": action,
            "status": "completed",
            "message": "子任务交付物已按任务引用读取。",
            "task": {
                "task_id": task.get("task_id"),
                "assignee_package_id": task.get("assignee_package_id"),
                "status": task.get("status"),
                "delivery_standard": task.get("delivery_standard") or {},
            },
            "artifacts": artifacts,
        }
    if action == "write_shared":
        relative = _required_text(arguments, "path")
        path = _safe_shared_path(store.session_workdir(collaboration_id), relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(arguments.get("content") or "") + "\n", encoding="utf-8")
        return {
            "action": action,
            "status": "completed",
            "message": "共享工作区文件已写入。",
            "path": relative,
        }
    if action == "complete_session":
        session = store.complete_session(
            collaboration_id,
            {
                "final_summary": _required_text(arguments, "content"),
                "speaker_type": "main_agent",
            },
        )
        return {
            "action": action,
            "status": "completed",
            "message": "协作会话已完成。",
            "session": _session_state_view(session),
            "path": "final/final-delivery.md",
        }
    raise ValueError(f"unsupported collaboration action: {action}")


def evaluate_risk(arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    action = str(arguments.get("action") or "").strip()
    if action in {"inspect", "read_shared", "read_task_artifacts"}:
        return ToolRiskResult(action="allow", risk_level="low", reasons=["collaboration read action"]).model_dump(mode="json")
    if action in {"create_task", "update_task", "cancel_task", "write_shared", "complete_session"}:
        return ToolRiskResult(
            action="inherit",
            risk_level="medium",
            reasons=["collaboration action mutates task state or shared workspace"],
        ).model_dump(mode="json")
    return ToolRiskResult(action="deny", risk_level="medium", reasons=[f"unsupported action: {action}"]).model_dump(mode="json")


def _inspect_gate(session: dict[str, Any]) -> dict[str, Any] | None:
    tasks = session.get("tasks") if isinstance(session.get("tasks"), list) else []
    if not tasks:
        return None
    statuses = {str(task.get("status") or "").strip() for task in tasks}
    if statuses & IMMEDIATE_ATTENTION_TASK_STATUSES:
        return None
    if statuses & ACTIVE_TASK_STATUSES:
        active = [
            {
                "task_id": task.get("task_id"),
                "assignee_package_id": task.get("assignee_package_id"),
                "status": task.get("status"),
                "updated_at": task.get("updated_at"),
            }
            for task in tasks
            if str(task.get("status") or "").strip() in ACTIVE_TASK_STATUSES
        ]
        return {
            "action": "inspect",
            "status": "deferred",
            "message": "当前只有运行中任务，尚无 submitted/blocked 状态；请等待协作状态变化后再继续验收或调度。",
            "active_tasks": active,
            "updated_at": session.get("updated_at"),
        }
    return None


def _task_payload(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        key: arguments[key]
        for key in (
            "assignee_package_id",
            "task_text",
            "depends_on",
            "delivery_standard",
            "visible_context",
            "input_artifacts",
        )
        if key in arguments
    }


def _task_update_payload(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        key: arguments[key]
        for key in (
            "status",
            "task_text",
            "depends_on",
            "delivery_standard",
            "visible_context",
            "input_artifacts",
            "result_summary",
            "review_notes",
            "artifact_refs",
        )
        if key in arguments
    }


def _store_path(resources: dict[str, Any]) -> Path:
    root = str(resources.get("collaboration_root") or os.getenv(COLLABORATION_ROOT_ENV) or "").strip()
    if root:
        return Path(root).expanduser().resolve() / "factory.sqlite"
    return resolve_collaboration_store_path()


def _required_text(arguments: dict[str, Any], key: str) -> str:
    value = str(arguments.get(key) or "").strip()
    if not value:
        raise ValueError(f"{key} is required")
    return value


def _task_by_id(session: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in session.get("tasks") or []:
        if isinstance(task, dict) and str(task.get("task_id") or "") == task_id:
            return task
    raise ValueError(f"collaboration task not found: {task_id}")


def _session_state_view(session: dict[str, Any]) -> dict[str, Any]:
    tasks = [
        _task_state_view(task)
        for task in session.get("tasks") or []
        if isinstance(task, dict)
    ]
    manufacturing_requests = [
        {
            "request_id": item.get("request_id"),
            "status": item.get("status"),
            "agent_name": item.get("agent_name"),
            "purpose": item.get("purpose"),
            "create_agent_session_id": item.get("create_agent_session_id"),
            "updated_at": item.get("updated_at"),
        }
        for item in session.get("manufacturing_requests") or []
        if isinstance(item, dict)
    ]
    status_counts: dict[str, int] = {}
    for task in tasks:
        status = str(task.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    return {
        "collaboration_id": session.get("collaboration_id"),
        "title": session.get("title"),
        "main_agent_package_id": session.get("main_agent_package_id"),
        "main_agent_package_session_id": session.get("main_agent_package_session_id"),
        "approval_mode": session.get("approval_mode"),
        "status": session.get("status"),
        "task_counts": status_counts,
        "tasks": tasks,
        "manufacturing_requests": manufacturing_requests,
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
    }


def _task_state_view(task: dict[str, Any]) -> dict[str, Any]:
    payload = task.get("result_payload") if isinstance(task.get("result_payload"), dict) else {}
    artifacts = [
        _artifact_state_view(item)
        for item in task.get("artifact_refs") or []
    ]
    result_state = {
        key: payload[key]
        for key in ("runtime_status", "delivery_validation")
        if key in payload
    }
    return {
        "task_id": task.get("task_id"),
        "parent_task_id": task.get("parent_task_id"),
        "assignee_package_id": task.get("assignee_package_id"),
        "assignee_session_id": task.get("assignee_session_id"),
        "task_text": task.get("task_text"),
        "depends_on": task.get("depends_on") or [],
        "delivery_standard": task.get("delivery_standard") or {},
        "status": task.get("status"),
        "result_summary": task.get("result_summary") or "",
        "result_state": result_state,
        "artifact_refs": artifacts,
        "review_notes": task.get("review_notes") or "",
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
    }


def _artifact_state_view(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {"path": str(item or "").strip()}
    return {
        key: item[key]
        for key in ("path", "kind", "mime_type", "size_bytes", "sha256", "created_by", "task_id", "source", "worker_path")
        if key in item
    }


def _read_task_artifacts(
    *,
    task: dict[str, Any],
    root: Path,
    requested_path: str | None,
    max_chars: int,
) -> list[dict[str, Any]]:
    refs = task.get("artifact_refs") if isinstance(task.get("artifact_refs"), list) else []
    indexed: dict[str, dict[str, Any]] = {}
    for item in refs:
        metadata = dict(item) if isinstance(item, dict) else {"path": str(item or "").strip()}
        relative = str(metadata.get("path") or "").strip()
        if relative and relative not in indexed:
            indexed[relative] = metadata
    if requested_path:
        if requested_path not in indexed:
            raise ValueError(f"artifact path is not referenced by task {task.get('task_id')}: {requested_path}")
        selected = [(requested_path, indexed[requested_path])]
    else:
        selected = list(indexed.items())
    if not selected:
        raise ValueError(f"task has no artifact references: {task.get('task_id')}")

    remaining = max_chars
    artifacts: list[dict[str, Any]] = []
    for relative, metadata in selected:
        path = _safe_shared_path(root, relative)
        record = {**metadata, "path": relative, "available": path.is_file()}
        if not path.is_file():
            record["error"] = "referenced artifact file is missing"
            artifacts.append(record)
            continue
        stat = path.stat()
        record.setdefault("size_bytes", stat.st_size)
        if remaining > 0:
            content, truncated = _shared_artifact_content(path, root, max_chars=remaining)
            record["content"] = content
            record["content_truncated"] = truncated
            remaining = max(0, remaining - len(content))
        else:
            record["content"] = ""
            record["content_truncated"] = True
        artifacts.append(record)
    return artifacts


def _safe_shared_path(root: Path, relative: str) -> Path:
    root = root.resolve()
    target = (root / relative).resolve()
    if root != target and root not in target.parents:
        raise ValueError(f"shared workspace path escapes collaboration workdir: {relative}")
    return target


def _shared_artifact_text(path: Path, root: Path, *, max_chars: int) -> str:
    return _shared_artifact_content(path, root, max_chars=max_chars)[0]


def _shared_artifact_content(path: Path, root: Path, *, max_chars: int) -> tuple[str, bool]:
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_FILE_EXTENSIONS:
        try:
            parsed = parse_file(path, root=root)
            text = "\n\n".join(str(document.content or "").strip() for document in parsed.documents).strip()
            if text:
                return text[:max_chars], len(text) > max_chars
        except Exception:
            pass
    data = path.read_bytes()[:8192]
    mime_type, _ = mimetypes.guess_type(path.name)
    if b"\x00" in data or str(mime_type or "").startswith(("image/", "application/")):
        stat = path.stat()
        return f"二进制交付物，mime_type={mime_type or 'application/octet-stream'}, size_bytes={stat.st_size}。", False
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        text = handle.read(max_chars + 1)
    return text[:max_chars], len(text) > max_chars
