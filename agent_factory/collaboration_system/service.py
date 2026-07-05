from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from agent_factory.collaboration_system.orchestrator import CollaborationOrchestrator
from agent_factory.collaboration_system.store import CollaborationStore
from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentPackageRuntimeManager


RuntimeFactory = Callable[[], AgentPackageRuntimeManager]


class CollaborationService:
    def __init__(
        self,
        *,
        runtime_factory: RuntimeFactory,
        store: CollaborationStore | None = None,
        poll_interval_seconds: float = 2.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self.store = store or CollaborationStore()
        self.runtime_factory = runtime_factory
        self.poll_interval_seconds = poll_interval_seconds
        self.logger = logger or logging.getLogger(__name__)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._dispatching_sessions: set[str] = set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        recovery = self.store.recover_interrupted_tasks()
        recovered_count = int(recovery.get("recovered_count") or 0)
        if recovered_count:
            self.logger.info("Recovered %s interrupted collaboration task(s)", recovered_count)
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="collaboration-service",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None

    def build_main_agent_prompt(
        self,
        *,
        collaboration_id: str,
        user_message: str,
        worker_agents: list[dict[str, Any]],
    ) -> str:
        from agent_factory.collaboration_system.prompting import build_main_agent_collaboration_prompt

        return build_main_agent_collaboration_prompt(
            user_message=user_message,
            session=self.store.get_session(collaboration_id),
            worker_agents=worker_agents,
        )

    def create_task(self, collaboration_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        session = self.store.create_task(collaboration_id, payload)
        if session.get("approval_mode") == "main_agent_delegated":
            self.dispatch_soon(collaboration_id)
        return session

    def update_task(self, collaboration_id: str, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        session = self.store.update_task(collaboration_id, task_id, payload)
        self._cancel_cancelled_task_requests(session)
        if session.get("approval_mode") == "main_agent_delegated":
            self.dispatch_soon(collaboration_id)
        return session

    def cancel_task(self, collaboration_id: str, task_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        session = self.store.get_session(collaboration_id)
        task = _task_by_id(session, task_id)
        cancelled = self._cancel_task_active_request(task, reason="collaboration_task_cancelled")
        notes = str((payload or {}).get("review_notes") or "用户停止了该子任务。").strip()
        result_payload = task.get("result_payload") if isinstance(task.get("result_payload"), dict) else {}
        session = self.store.update_task(
            collaboration_id,
            task_id,
            {
                "status": "cancelled",
                "review_notes": notes,
                "result_summary": notes,
                "result_payload": {
                    **result_payload,
                    "runtime_status": "cancelled",
                    "cancelled_active_request_count": cancelled,
                },
            },
        )
        self.store.record_message(
            collaboration_id,
            speaker_type="system",
            speaker_package_id=task.get("assignee_package_id"),
            message_kind="progress",
            content=notes,
            task_id=task_id,
        )
        return session

    def complete_session(self, collaboration_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.store.complete_session(collaboration_id, payload)

    def delete_session(self, collaboration_id: str) -> dict[str, Any]:
        session = self.store.get_session(collaboration_id)
        cancelled = self._cancel_session_active_requests(session)
        result = self.store.delete_session(collaboration_id)
        result["cancelled_active_request_count"] = cancelled
        return result

    def dispatch_soon(self, collaboration_id: str) -> None:
        threading.Thread(
            target=self._dispatch_soon_worker,
            args=(collaboration_id,),
            name=f"collaboration-dispatch-{collaboration_id[:8]}",
            daemon=True,
        ).start()

    def dispatch_ready(self, collaboration_id: str, *, limit: int | None = None) -> dict[str, Any]:
        if not self._claim_session(collaboration_id):
            return {
                "collaboration_id": collaboration_id,
                "started_count": 0,
                "results": [],
                "session": self.store.get_session(collaboration_id),
                "message": "协作会话正在调度中。",
            }
        try:
            orchestrator = CollaborationOrchestrator(
                store=self.store,
                runtime=self.runtime_factory(),
            )
            return orchestrator.start_ready_tasks(collaboration_id, limit=limit)
        finally:
            self._release_session(collaboration_id)

    def start_task(self, collaboration_id: str, task_id: str) -> dict[str, Any]:
        if not self._claim_session(collaboration_id):
            return {
                "result": None,
                "session": self.store.get_session(collaboration_id),
                "message": "协作会话正在调度中。",
            }
        try:
            orchestrator = CollaborationOrchestrator(
                store=self.store,
                runtime=self.runtime_factory(),
            )
            result = orchestrator.start_task(collaboration_id, task_id)
            return {"result": result, "session": self.store.get_session(collaboration_id)}
        finally:
            self._release_session(collaboration_id)

    def resolve_task_approval(self, collaboration_id: str, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._claim_session(collaboration_id):
            return {
                "result": None,
                "session": self.store.get_session(collaboration_id),
                "message": "协作会话正在调度中。",
            }
        try:
            session = self.store.get_session(collaboration_id)
            task = _task_by_id(session, task_id)
            resume_payload = _approval_resume_payload(task, payload)
            self.store.record_message(
                collaboration_id,
                speaker_type="user",
                speaker_package_id=None,
                message_kind="approval",
                content=_approval_resolution_message(payload),
                task_id=task_id,
            )
            orchestrator = CollaborationOrchestrator(
                store=self.store,
                runtime=self.runtime_factory(),
            )
            result = orchestrator.resume_task_approval(
                collaboration_id,
                task_id,
                resume_payload=resume_payload,
            )
            return {"result": result, "session": self.store.get_session(collaboration_id)}
        finally:
            self._release_session(collaboration_id)

    def dispatch_delegated_sessions(self) -> None:
        self.cancel_requested_tasks()
        for session in self.store.list_auto_dispatch_sessions():
            collaboration_id = str(session.get("collaboration_id") or "").strip()
            if not collaboration_id:
                continue
            try:
                self.dispatch_ready(collaboration_id)
            except Exception as exc:
                self.logger.warning(
                    "Collaboration dispatch failed for %s: %s: %s",
                    collaboration_id,
                    type(exc).__name__,
                    exc,
                )

    def cancel_requested_tasks(self) -> int:
        cancelled = 0
        for session in self.store.list_sessions():
            collaboration_id = str(session.get("collaboration_id") or "").strip()
            if not collaboration_id:
                continue
            cancelled += self._cancel_cancelled_task_requests(self.store.get_session(collaboration_id))
        return cancelled

    def _run_loop(self) -> None:
        while not self._stop_event.wait(self.poll_interval_seconds):
            self.dispatch_delegated_sessions()

    def _dispatch_soon_worker(self, collaboration_id: str) -> None:
        try:
            self.dispatch_ready(collaboration_id)
        except Exception as exc:
            self.logger.warning(
                "Collaboration dispatch failed for %s: %s: %s",
                collaboration_id,
                type(exc).__name__,
                exc,
            )

    def _claim_session(self, collaboration_id: str) -> bool:
        with self._lock:
            if collaboration_id in self._dispatching_sessions:
                return False
            self._dispatching_sessions.add(collaboration_id)
            return True

    def _release_session(self, collaboration_id: str) -> None:
        with self._lock:
            self._dispatching_sessions.discard(collaboration_id)

    def _cancel_session_active_requests(self, session: dict[str, Any]) -> int:
        targets = _active_runtime_request_targets(session)
        if not targets:
            return 0
        runtime = self.runtime_factory()
        cancelled = 0
        for request_id in targets:
            cancelled += runtime.cancel_active_requests(
                reason="collaboration_session_deleted",
                request_id=request_id,
            )
        return cancelled

    def _cancel_cancelled_task_requests(self, session: dict[str, Any]) -> int:
        cancelled = 0
        for task in session.get("tasks") or []:
            if str(task.get("status") or "") != "cancelled":
                continue
            cancelled += self._cancel_task_active_request(task, reason="collaboration_task_cancelled")
        return cancelled

    def _cancel_task_active_request(self, task: dict[str, Any], *, reason: str) -> int:
        payload = task.get("result_payload") if isinstance(task.get("result_payload"), dict) else {}
        request_id = str(payload.get("active_request_id") or "").strip()
        if not request_id:
            return 0
        package_id = str(payload.get("active_package_id") or task.get("assignee_package_id") or "").strip()
        return self.runtime_factory().cancel_active_requests(
            reason=reason,
            request_id=request_id,
            package_id=package_id or None,
        )


def _task_by_id(session: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in session.get("tasks") or []:
        if str(task.get("task_id") or "") == task_id:
            return task
    raise ValueError(f"collaboration task not found: {task_id}")


def _active_runtime_request_targets(session: dict[str, Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    tasks = session.get("tasks") if isinstance(session.get("tasks"), list) else []
    for task in tasks:
        payload = task.get("result_payload") if isinstance(task.get("result_payload"), dict) else {}
        request_id = str(payload.get("active_request_id") or "").strip()
        if not request_id or request_id in seen:
            continue
        seen.add(request_id)
        result.append(request_id)
    return result


def _approval_resume_payload(task: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    result_payload = task.get("result_payload") if isinstance(task.get("result_payload"), dict) else {}
    pending = result_payload.get("pending_interrupt") if isinstance(result_payload.get("pending_interrupt"), dict) else {}
    base = pending.get("resume_payload") if isinstance(pending.get("resume_payload"), dict) else {}
    action = str(payload.get("action") or "approve").strip()
    if action not in {"approve", "deny", "revise"}:
        raise ValueError(f"unsupported collaboration approval action: {action}")
    approved = action == "approve"
    merged = {
        **base,
        "action": action,
        "approved": approved,
    }
    guidance = str(payload.get("revision_guidance") or "").strip()
    if action == "revise" and guidance:
        merged["revision_guidance"] = guidance
    return merged


def _approval_resolution_message(payload: dict[str, Any]) -> str:
    action = str(payload.get("action") or "approve").strip()
    if action == "approve":
        return "用户批准 worker 工具调用。"
    if action == "deny":
        return "用户拒绝 worker 工具调用。"
    guidance = str(payload.get("revision_guidance") or "").strip()
    return "用户要求 worker 修改工具调用。" + (f" 修改意见：{guidance}" if guidance else "")
