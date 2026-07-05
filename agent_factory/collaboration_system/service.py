from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from typing import Any

from agent_factory.create_agent.publish_tool import confirm_and_publish
from agent_factory.create_agent.runtime import CreateAgentRuntime
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.collaboration_system.orchestrator import CollaborationOrchestrator
from agent_factory.collaboration_system.store import CollaborationStore
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent
from agent_factory.factory_graph.frontend_bridge.runtime_events import RUN_TERMINAL_EVENT_TYPES, runtime_stream_status
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
        self._manufacturing_requests: set[str] = set()
        self._last_monitor_at: dict[str, float] = {}

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
    ) -> str:
        from agent_factory.collaboration_system.prompting import build_main_agent_collaboration_prompt

        return build_main_agent_collaboration_prompt(
            user_message=user_message,
            session=self.store.get_session(collaboration_id),
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
                self.process_manufacturing_requests(collaboration_id)
                self.dispatch_ready(collaboration_id)
                self.monitor_session(collaboration_id)
            except Exception as exc:
                self.logger.warning(
                    "Collaboration dispatch failed for %s: %s: %s",
                    collaboration_id,
                    type(exc).__name__,
                    exc,
                )

    def process_manufacturing_requests(self, collaboration_id: str) -> None:
        for request in self.store.list_active_manufacturing_requests(collaboration_id):
            request_id = str(request.get("request_id") or "").strip()
            if not request_id or not self._claim_manufacturing_request(request_id):
                continue
            threading.Thread(
                target=self._manufacturing_worker,
                args=(collaboration_id, request_id),
                name=f"collaboration-manufacture-{request_id[:8]}",
                daemon=True,
            ).start()

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

    def monitor_session(self, collaboration_id: str) -> None:
        session = self.store.get_session(collaboration_id)
        if str(session.get("approval_mode") or "") != "main_agent_delegated":
            return
        if str(session.get("status") or "") in {"completed", "failed", "cancelled"}:
            return
        active_tasks = [
            task for task in session.get("tasks") or []
            if str(task.get("status") or "") in {"accepted", "planning", "working", "blocked", "submitted"}
        ]
        if not active_tasks:
            return
        now = time.monotonic()
        interval = _monitor_interval_seconds()
        last = self._last_monitor_at.get(collaboration_id, 0.0)
        if now - last < interval:
            return
        if not self._claim_session(collaboration_id):
            return
        self._last_monitor_at[collaboration_id] = now
        try:
            fresh = self.store.get_session(collaboration_id)
            message = _monitor_message(fresh)
            if not message:
                return
            orchestrator = CollaborationOrchestrator(
                store=self.store,
                runtime=self.runtime_factory(),
            )
            orchestrator.continue_main_agent(collaboration_id, user_message=message)
        finally:
            self._release_session(collaboration_id)

    def _claim_session(self, collaboration_id: str) -> bool:
        with self._lock:
            if collaboration_id in self._dispatching_sessions:
                return False
            self._dispatching_sessions.add(collaboration_id)
            return True

    def _release_session(self, collaboration_id: str) -> None:
        with self._lock:
            self._dispatching_sessions.discard(collaboration_id)

    def _claim_manufacturing_request(self, request_id: str) -> bool:
        with self._lock:
            if request_id in self._manufacturing_requests:
                return False
            self._manufacturing_requests.add(request_id)
            return True

    def _release_manufacturing_request(self, request_id: str) -> None:
        with self._lock:
            self._manufacturing_requests.discard(request_id)

    def _manufacturing_worker(self, collaboration_id: str, request_id: str) -> None:
        try:
            self._run_manufacturing_request(collaboration_id, request_id)
        except Exception as exc:
            self.logger.warning(
                "Collaboration manufacturing failed for %s/%s: %s: %s",
                collaboration_id,
                request_id,
                type(exc).__name__,
                exc,
            )
            try:
                self.store.update_manufacturing_request(
                    collaboration_id,
                    request_id,
                    {
                        "status": "failed",
                        "message": f"Agent 制造失败：{type(exc).__name__}: {exc}",
                        "result_payload": {"error": f"{type(exc).__name__}: {exc}"},
                    },
                )
                self._continue_after_manufacturing(
                    collaboration_id,
                    user_message=f"制造请求 {request_id} 失败，请重新评估是否调整需求或继续使用现有 Agent。",
                )
            except Exception:
                self.logger.exception("Failed to record manufacturing failure for %s", request_id)
        finally:
            self._release_manufacturing_request(request_id)

    def _run_manufacturing_request(self, collaboration_id: str, request_id: str) -> None:
        request = self.store.get_manufacturing_request(collaboration_id, request_id)
        create_agent_session_id = str(request.get("create_agent_session_id") or "").strip() or f"collab_make_{request_id}"
        self.store.update_manufacturing_request(
            collaboration_id,
            request_id,
            {
                "status": "running",
                "create_agent_session_id": create_agent_session_id,
                "message": f"开始制造 Agent：{request.get('agent_name')}",
                "result_payload": {"create_agent_session_id": create_agent_session_id},
            },
        )
        runtime = CreateAgentRuntime()
        run = runtime.stream(
            user_input=_manufacturing_prompt(request),
            session_id=create_agent_session_id,
            request_id=f"collab-manufacture-{request_id}",
            user_config=None,
        )
        status, message, publish_ready = _consume_create_agent_run(run)
        if status != "completed":
            self.store.update_manufacturing_request(
                collaboration_id,
                request_id,
                {
                    "status": "failed",
                    "message": f"制造 Agent 未完成：{message or status}",
                    "result_payload": {
                        "create_agent_session_id": create_agent_session_id,
                        "runtime_status": status,
                        "message": message,
                    },
                },
            )
            self._continue_after_manufacturing(
                collaboration_id,
                user_message=f"制造请求 {request_id} 未完成：{message or status}。请决定是否调整需求或重新制造。",
            )
            return
        workspace = CreateAgentWorkspace.for_session(create_agent_session_id)
        publish_result = confirm_and_publish(
            workspace=workspace,
            confirmation=f"协作主 Agent 代理制造自动发布：{request.get('agent_name')}",
        )
        package_id = str(publish_result.get("package_id") or "").strip()
        self.store.update_manufacturing_request(
            collaboration_id,
            request_id,
            {
                "status": "completed",
                "message": f"Agent 已制造并自动发布：{package_id or request.get('agent_name')}",
                "result_payload": {
                    "create_agent_session_id": create_agent_session_id,
                    "package_id": package_id,
                    "publish": publish_result,
                    **({"publish_ready": publish_ready} if publish_ready else {}),
                },
            },
        )
        self._continue_after_manufacturing(
            collaboration_id,
            user_message=(
                f"制造请求 {request_id} 已自动发布。package_id={package_id}。"
                "请再次调用 agent_search 确认新 Agent 可用，再创建协作任务；不要直接使用未检索确认的 package_id。"
            ),
        )

    def _continue_after_manufacturing(self, collaboration_id: str, *, user_message: str) -> None:
        if not self._claim_session(collaboration_id):
            return
        try:
            orchestrator = CollaborationOrchestrator(
                store=self.store,
                runtime=self.runtime_factory(),
            )
            orchestrator.continue_main_agent(collaboration_id, user_message=user_message)
        finally:
            self._release_session(collaboration_id)

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


def _monitor_interval_seconds() -> float:
    raw = str(os.getenv("AGENTFACTORY_COLLABORATION_MONITOR_INTERVAL_SECONDS") or "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            value = 0.0
        if value >= 15:
            return value
    return 90.0


def _monitor_message(session: dict[str, Any]) -> str:
    active_tasks = [
        task for task in session.get("tasks") or []
        if str(task.get("status") or "") in {"accepted", "planning", "working", "blocked", "submitted"}
    ]
    if not active_tasks:
        return ""
    messages = session.get("messages") if isinstance(session.get("messages"), list) else []
    lines = [
        "协作进展定时快照：请检查子任务是否仍在朝交付标准推进；如出现长时间调研、重复工具调用、阻塞或已提交结果，请主动校正、验收或调整后续任务。",
    ]
    for task in active_tasks:
        task_id = str(task.get("task_id") or "").strip()
        related = [
            message for message in messages
            if isinstance(message, dict) and str(message.get("task_id") or "") == task_id
        ][-6:]
        lines.append(
            f"- task_id={task_id}; agent={task.get('assignee_package_id')}; "
            f"status={task.get('status')}; summary={_compact_text(task.get('result_summary'), 160)}"
        )
        for message in related:
            lines.append(
                f"  - {message.get('speaker_type')}/{message.get('message_kind')}: "
                f"{_compact_text(message.get('content'), 180)}"
            )
    return "\n".join(lines)


def _compact_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


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


def _manufacturing_prompt(request: dict[str, Any]) -> str:
    payload = request.get("request_payload") if isinstance(request.get("request_payload"), dict) else {}
    lines = [
        "请制造并验证一个新的 AgentPackage。该请求来自多 Agent 协作主 Agent，制造通过 full_static 后会由宿主自动发布。",
        "",
        f"Agent 名称：{request.get('agent_name') or payload.get('agent_name')}",
        f"用途：{request.get('purpose') or payload.get('purpose')}",
        f"现有 Agent 不足原因：{payload.get('reason_existing_agents_insufficient') or ''}",
        f"偏好运行模式：{payload.get('preferred_pattern') or '由制造 Agent 根据任务复杂度决定'}",
        "",
        "目标任务：",
        *_list_lines(payload.get("target_tasks")),
        "",
        "交付标准：",
        *_list_lines(payload.get("delivery_standards")),
        "",
        "限制条件：",
        *_list_lines(payload.get("constraints")),
        "",
        "制造要求：",
        "- 使用现有制造流程完成 package 设计、工具/skill/MCP/模型能力配置与 full_static validation。",
        "- 如果需要外部能力，优先复用已有系统工具、SkillHub skill、MCP 继承和模型池能力，不重复造轮子。",
        "- 不要在最终阶段要求用户回复确认发布；通过 full_static 后进入待发布状态即可。",
    ]
    return "\n".join(lines)


def _list_lines(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["- 无"]
    lines = [f"- {str(item).strip()}" for item in value if str(item or "").strip()]
    return lines or ["- 无"]


def _consume_create_agent_run(run: Any) -> tuple[str, str, dict[str, Any] | None]:
    status = "failed"
    message = "create-agent stream ended without terminal status"
    publish_ready: dict[str, Any] | None = None
    for stream_mode, chunk in run.events:
        if stream_mode != "frontend_event":
            continue
        item = chunk if isinstance(chunk, FactoryFrontendEvent) else FactoryFrontendEvent.model_validate(chunk)
        if item.event_type in RUN_TERMINAL_EVENT_TYPES:
            status = runtime_stream_status(item)
            message = str(item.message or item.payload.get("message") or "").strip()
            if isinstance(item.payload.get("publish_ready"), dict):
                publish_ready = item.payload["publish_ready"]
            break
    return status, message, publish_ready
