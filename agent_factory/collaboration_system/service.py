from __future__ import annotations

import logging
import math
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

from agent_factory.create_agent.publish_tool import confirm_and_publish
from agent_factory.create_agent.runtime import CreateAgentRuntime
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.evolution.runtime import AgentEvolutionRuntime
from agent_factory.collaboration_system.orchestrator import CollaborationOrchestrator
from agent_factory.collaboration_runtime_policy import collaboration_runtime_tool_access
from agent_factory.collaboration_system.store import (
    CollaborationStore,
    SUB_AGENT_TASK_TYPE_AGENT,
    SUB_AGENT_TASK_TYPE_EVOLVE,
    SUB_AGENT_TASK_TYPE_MANUFACTURE,
    TASK_STATUSES,
    TERMINAL_TASK_STATUSES,
)
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent
from agent_factory.factory_graph.frontend_bridge.protocol import event
from agent_factory.factory_graph.frontend_bridge.runtime_events import (
    INTERRUPT_TERMINAL_EVENT_TYPES,
    RUN_TERMINAL_EVENT_TYPES,
    runtime_stream_status,
)
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import VisibleAssistantOutputAccumulator
from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentPackageRuntimeManager
from agent_factory.collaboration_system.capacity import (
    ChatInferenceCapacity,
    inspect_configured_inference_capacity,
    normalize_max_parallel_sub_agents,
)
from agent_factory.model_pool.usage import ModelUsageStore


RuntimeFactory = Callable[[], AgentPackageRuntimeManager]
InferenceCapacityProbe = Callable[[], ChatInferenceCapacity]
MAIN_AGENT_EVENT_COALESCE_WINDOW_ENV = "AGENTFACTORY_COLLABORATION_EVENT_COALESCE_WINDOW_SECONDS"
MAIN_AGENT_EVENT_BATCH_LIMIT_ENV = "AGENTFACTORY_COLLABORATION_EVENT_BATCH_LIMIT"
DEFAULT_MAIN_AGENT_EVENT_COALESCE_WINDOW_SECONDS = 0.75
DEFAULT_MAIN_AGENT_EVENT_BATCH_LIMIT = 64


@dataclass(frozen=True, slots=True)
class CollaborationDispatchCapacity:
    capacity: int
    max_parallel_sub_agents: int
    active_sub_agents: int
    inference: ChatInferenceCapacity
    reason: str

    def payload(self) -> dict[str, Any]:
        return {
            "capacity": self.capacity,
            "max_parallel_sub_agents": self.max_parallel_sub_agents,
            "active_sub_agents": self.active_sub_agents,
            "reason": self.reason,
            "inference": self.inference.payload(),
        }


@dataclass(frozen=True, slots=True)
class MainAgentEventBatch:
    event_ids: tuple[str, ...]
    task_ids: tuple[str, ...]
    event_ref: str
    user_message: str
    message_metadata: dict[str, Any]

    @property
    def message_task_id(self) -> str | None:
        return self.task_ids[0] if len(self.task_ids) == 1 else None


class CollaborationService:
    def __init__(
        self,
        *,
        runtime_factory: RuntimeFactory,
        store: CollaborationStore | None = None,
        inference_capacity_probe: InferenceCapacityProbe = inspect_configured_inference_capacity,
        poll_interval_seconds: float = 2.0,
        main_agent_event_coalesce_window_seconds: float | None = None,
        main_agent_event_batch_limit: int | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.store = store or CollaborationStore()
        self.runtime_factory = runtime_factory
        self.inference_capacity_probe = inference_capacity_probe
        self.poll_interval_seconds = _positive_float(
            poll_interval_seconds,
            name="poll_interval_seconds",
        )
        self.main_agent_event_coalesce_window_seconds = (
            _main_agent_event_coalesce_window_seconds()
            if main_agent_event_coalesce_window_seconds is None
            else _positive_float(
                main_agent_event_coalesce_window_seconds,
                name="main_agent_event_coalesce_window_seconds",
            )
        )
        self.main_agent_event_batch_limit = (
            _main_agent_event_batch_limit()
            if main_agent_event_batch_limit is None
            else _positive_int(
                main_agent_event_batch_limit,
                name="main_agent_event_batch_limit",
            )
        )
        self.logger = logger or logging.getLogger(__name__)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._dispatch_lock = threading.Lock()
        self._dispatching_sessions: set[str] = set()
        self._reserved_worker_tasks: set[tuple[str, str]] = set()
        self._active_sub_agent_requests: set[tuple[str, str]] = set()
        self._evolution_runtimes: dict[str, AgentEvolutionRuntime] = {}
        self._evolution_collaboration_ids: dict[str, str] = {}
        self._evolution_threads: dict[str, threading.Thread] = {}
        self._main_agent_event_timers: dict[str, threading.Timer] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        repaired_sessions = self.store.repair_terminal_sessions_with_open_work()
        if repaired_sessions:
            self.logger.info(
                "Repaired %s terminal collaboration session(s) with open work",
                len(repaired_sessions),
            )
        recovery = self.store.recover_interrupted_tasks()
        recovered_count = int(recovery.get("recovered_count") or 0)
        if recovered_count:
            self.logger.info("Recovered %s interrupted collaboration task(s)", recovered_count)
        event_recovery = self.store.recover_interrupted_main_agent_events()
        recovered_event_count = int(event_recovery.get("recovered_count") or 0)
        if recovered_event_count:
            self.logger.info("Recovered %s interrupted collaboration main agent event(s)", recovered_event_count)
        recovered_cleanup_count = self.store.recover_task_retry_cleanups()
        if recovered_cleanup_count:
            self.logger.info("Recovered %s collaboration task retry cleanup(s)", recovered_cleanup_count)
        recovered_approval_count = self.store.recover_processing_task_approval_decisions()
        if recovered_approval_count:
            self.logger.info("Recovered %s collaboration task approval decision(s)", recovered_approval_count)
        recovered_evolution_count = self.store.recover_interrupted_evolution_requests()
        if recovered_evolution_count:
            self.logger.info("Marked %s interrupted evolution request(s) as failed", recovered_evolution_count)
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="collaboration-service",
            daemon=True,
        )
        self._thread.start()
        threading.Thread(
            target=self.dispatch_delegated_sessions,
            name="collaboration-initial-dispatch",
            daemon=True,
        ).start()
        for collaboration_id in self.store.list_pending_main_agent_event_collaboration_ids():
            self._schedule_main_agent_event_drain(collaboration_id)

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            timers = list(self._main_agent_event_timers.values())
            self._main_agent_event_timers.clear()
            evolution_items = list(self._evolution_runtimes.items())
            evolution_threads = dict(self._evolution_threads)
        for timer in timers:
            timer.cancel()
        for request_id, runtime in evolution_items:
            requested = runtime.cancel_active_requests(reason="collaboration_service_stopped")
            thread = evolution_threads.get(request_id)
            if requested == 0 and (thread is None or not thread.is_alive()):
                collaboration_id = self._evolution_collaboration_ids.get(request_id)
                if collaboration_id:
                    request = self.store.get_evolution_request(collaboration_id, request_id)
                    runtime.abort_session(
                        package_id=str(request.get("package_id") or ""),
                        session_id=str(request.get("evolution_session_id") or ""),
                        reason="collaboration_service_stopped",
                    )
        for thread in evolution_threads.values():
            if thread.is_alive():
                thread.join(timeout=5)
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

        session = self.store.get_session(collaboration_id)
        if str(session.get("status") or "") in {"completed", "failed", "cancelled"}:
            session = self.store.reopen_session(collaboration_id)
        return build_main_agent_collaboration_prompt(
            user_message=user_message,
            session=session,
        )

    def main_agent_runtime_tool_access(self) -> dict[str, list[str]]:
        return collaboration_runtime_tool_access()

    def session_view(self, collaboration_id: str) -> dict[str, Any]:
        session = self.store.get_session(collaboration_id)
        task_by_session_id = {
            str(task.get("assignee_session_id") or "").strip(): str(task.get("task_id") or "").strip()
            for task in session.get("tasks") or []
            if isinstance(task, dict) and str(task.get("assignee_session_id") or "").strip()
        }
        main_session_id = str(session.get("main_agent_package_session_id") or "").strip()
        if main_session_id:
            task_by_session_id.setdefault(main_session_id, "")
        session["statistics"] = _collaboration_statistics(
            session,
            ModelUsageStore().collaboration_summary(
                collaboration_id,
                task_by_session_id=task_by_session_id,
            ),
        )
        return session

    def create_task(self, collaboration_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        session = self.store.create_task(collaboration_id, payload)
        self.runtime_factory().emit_collaboration_session_updated(
            collaboration_id=collaboration_id,
            session=session,
        )
        if session.get("approval_mode") == "main_agent_delegated":
            self.dispatch_soon(collaboration_id)
        return session

    def update_task(self, collaboration_id: str, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("status") in (TASK_STATUSES - TERMINAL_TASK_STATUSES):
            self._reopen_terminal_session(collaboration_id)
        session = self._update_task(collaboration_id, task_id, payload)
        self._cancel_cancelled_task_requests(session)
        if session.get("approval_mode") == "main_agent_delegated":
            self.dispatch_soon(collaboration_id)
        return session

    def retry_task(
        self,
        collaboration_id: str,
        task_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._reopen_terminal_session(collaboration_id)
        replacement = self.store.retry_task(collaboration_id, task_id, payload)
        self.cleanup_retried_task_sessions()
        session = replacement["session"]
        self.runtime_factory().emit_collaboration_session_updated(
            collaboration_id=collaboration_id,
            session=session,
        )
        if session.get("approval_mode") == "main_agent_delegated":
            self.dispatch_soon(collaboration_id)
        return replacement

    def _reopen_terminal_session(self, collaboration_id: str) -> None:
        session = self.store.get_session(collaboration_id)
        if str(session.get("status") or "") in {"completed", "failed", "cancelled"}:
            self.store.reopen_session(collaboration_id)

    def cleanup_retried_task_sessions(self) -> int:
        cleaned = 0
        for cleanup in self.store.claim_task_retry_cleanups():
            retry_id = str(cleanup.get("retry_id") or "")
            package_id = str(cleanup.get("assignee_package_id") or "").strip()
            session_id = str(cleanup.get("assignee_session_id") or "").strip()
            try:
                self.runtime_factory().delete_session(
                    package_id,
                    session_id,
                    delete_workdir=True,
                    unlink_collaboration=False,
                )
            except Exception as exc:
                self.store.resolve_task_retry_cleanup(
                    retry_id,
                    succeeded=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
                self.logger.warning(
                    "Failed to clean replaced collaboration worker session %s/%s: %s: %s",
                    package_id,
                    session_id,
                    type(exc).__name__,
                    exc,
                )
                continue
            self.store.resolve_task_retry_cleanup(retry_id, succeeded=True)
            cleaned += 1
        return cleaned

    def cancel_task(self, collaboration_id: str, task_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        session = self.store.get_session(collaboration_id)
        task = _task_by_id(session, task_id)
        notes = str((payload or {}).get("review_notes") or "用户停止了该子任务。").strip()
        result_payload = task.get("result_payload") if isinstance(task.get("result_payload"), dict) else {}
        session = self._update_task(
            collaboration_id,
            task_id,
            {
                "status": "cancelled",
                "review_notes": notes,
                "result_summary": notes,
                "result_payload": {
                    **result_payload,
                    "runtime_status": "cancelled",
                },
            },
        )
        cancelled = self._cancel_task_active_request(task, reason="collaboration_task_cancelled")
        session["cancelled_active_request_count"] = cancelled
        self.store.record_message(
            collaboration_id,
            speaker_type="system",
            speaker_package_id=task.get("assignee_package_id"),
            message_kind="progress",
            content=notes,
            task_id=task_id,
        )
        if cancelled == 0:
            self.store.release_worker_lease_unless_blocked(collaboration_id, task_id)
        return session

    def complete_session(self, collaboration_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.store.complete_session(collaboration_id, payload)
        return self.session_view(collaboration_id)

    def delete_session(self, collaboration_id: str) -> dict[str, Any]:
        session = self.store.get_session(collaboration_id)
        cancelled = self._cancel_session_active_requests(session)
        cancelled += self._cancel_session_evolutions(session)
        session_targets = _collaboration_runtime_session_targets(session)
        runtime_cleanup = self.runtime_factory().delete_collaboration_sessions(
            collaboration_id,
            session_targets=session_targets,
        )
        cleanup_errors = runtime_cleanup.get("errors") if isinstance(runtime_cleanup.get("errors"), list) else []
        if cleanup_errors:
            raise RuntimeError(
                "collaboration runtime cleanup failed: "
                + "; ".join(
                    str(item.get("error") or item)
                    for item in cleanup_errors
                    if isinstance(item, dict)
                )
            )
        result = self.store.delete_session(collaboration_id)
        result["cancelled_active_request_count"] = cancelled
        result["runtime_cleanup"] = runtime_cleanup
        return result

    def dispatch_soon(self, collaboration_id: str) -> None:
        threading.Thread(
            target=self._dispatch_soon_worker,
            args=(collaboration_id,),
            name=f"collaboration-dispatch-{collaboration_id[:8]}",
            daemon=True,
        ).start()

    def _schedule_main_agent_event_drain(
        self,
        collaboration_id: str,
        *,
        minimum_delay_seconds: float = 0.0,
    ) -> None:
        if self._stop_event.is_set():
            return
        oldest_created_at = self.store.oldest_pending_main_agent_event_created_at(collaboration_id)
        if oldest_created_at is None:
            return
        ready_at = _parse_utc_datetime(oldest_created_at) + timedelta(
            seconds=self.main_agent_event_coalesce_window_seconds
        )
        delay_seconds = max(
            minimum_delay_seconds,
            0.0,
            (ready_at - datetime.now(UTC)).total_seconds(),
        )
        with self._lock:
            existing = self._main_agent_event_timers.get(collaboration_id)
            if existing is not None and existing.is_alive():
                return
            timer = threading.Timer(
                delay_seconds,
                self._on_main_agent_event_timer,
                args=(collaboration_id,),
            )
            timer.name = f"collaboration-main-event-{collaboration_id[:8]}"
            timer.daemon = True
            self._main_agent_event_timers[collaboration_id] = timer
            timer.start()

    def _on_main_agent_event_timer(self, collaboration_id: str) -> None:
        current = threading.current_thread()
        with self._lock:
            if self._main_agent_event_timers.get(collaboration_id) is not current:
                return
            self._main_agent_event_timers.pop(collaboration_id, None)
        if self._stop_event.is_set():
            return
        self._dispatch_soon_worker(collaboration_id)
        self._schedule_main_agent_event_drain(
            collaboration_id,
            minimum_delay_seconds=self.poll_interval_seconds,
        )

    def dispatch_ready(self, collaboration_id: str, *, limit: int | None = None) -> dict[str, Any]:
        session = self.store.get_session(collaboration_id)
        if str(session.get("status") or "") in {"completed", "failed", "cancelled"}:
            return {
                "collaboration_id": collaboration_id,
                "started_count": 0,
                "results": [],
                "session": session,
                "message": "协作会话已经结束；重新发送消息后会开启新的执行轮次。",
            }
        if not self._claim_session(collaboration_id):
            return {
                "collaboration_id": collaboration_id,
                "started_count": 0,
                "results": [],
                "session": self.store.get_session(collaboration_id),
                "message": "协作会话正在调度中。",
            }
        claimed_tasks: list[dict[str, Any]] = []
        launches: list[tuple[str, str]] = []
        try:
            with self._dispatch_lock:
                dispatch_capacity = self._dispatch_capacity(collaboration_id, limit=limit)
                queued_tasks = self.store.list_sub_agent_queue(collaboration_id)
                for queued_task in queued_tasks:
                    if len(claimed_tasks) >= dispatch_capacity.capacity:
                        break
                    task_type = str(queued_task.get("type") or "")
                    task_id = str(queued_task.get("task_id") or "").strip()
                    if not task_id:
                        continue
                    if task_type == SUB_AGENT_TASK_TYPE_AGENT:
                        claimed_agent_tasks = self.store.claim_ready_tasks(collaboration_id, limit=1)
                        if not claimed_agent_tasks:
                            continue
                        claimed_task = claimed_agent_tasks[0]
                        claimed_task_id = str(claimed_task.get("task_id") or "").strip()
                        if not claimed_task_id:
                            continue
                        claimed_tasks.append({**claimed_task, "type": SUB_AGENT_TASK_TYPE_AGENT})
                        launches.append((SUB_AGENT_TASK_TYPE_AGENT, claimed_task_id))
                        continue
                    with self._lock:
                        request_key = (task_type, task_id)
                        if request_key in self._active_sub_agent_requests:
                            continue
                        self._active_sub_agent_requests.add(request_key)
                    claimed_tasks.append(dict(queued_task))
                    launches.append((task_type, task_id))
                session = self.store.get_session(collaboration_id)
                if claimed_tasks:
                    self.runtime_factory().emit_collaboration_session_updated(
                        collaboration_id=collaboration_id,
                        session=session,
                    )
                if not claimed_tasks and queued_tasks and dispatch_capacity.capacity == 0:
                    ready_tasks = self.store.ready_tasks(collaboration_id)
                    waiting_tasks = [
                        task
                        for task in ready_tasks
                        if str((task.get("result_payload") or {}).get("runtime_status") or "")
                        != "waiting_for_inference_capacity"
                    ]
                    if waiting_tasks:
                        session = self.store.mark_tasks_waiting_for_inference_capacity(
                            collaboration_id,
                            task_ids=[str(task.get("task_id") or "") for task in waiting_tasks],
                            capacity=dispatch_capacity.payload(),
                            message=dispatch_capacity.reason,
                        )
                        self.runtime_factory().emit_collaboration_session_updated(
                            collaboration_id=collaboration_id,
                            session=session,
                        )
        finally:
            self._release_session(collaboration_id)
        for task_type, task_id in launches:
            if task_type == SUB_AGENT_TASK_TYPE_AGENT:
                target = self._run_worker_task
                name = f"collaboration-agent-{task_id[:8]}"
            elif task_type == SUB_AGENT_TASK_TYPE_MANUFACTURE:
                target = self._manufacturing_worker
                name = f"collaboration-manufacture-{task_id[:8]}"
            else:
                target = self._evolution_worker
                name = f"collaboration-evolve-{task_id[:8]}"
            thread = threading.Thread(
                target=target,
                args=(collaboration_id, task_id),
                name=name,
                daemon=True,
            )
            if task_type == SUB_AGENT_TASK_TYPE_EVOLVE:
                with self._lock:
                    self._evolution_threads[task_id] = thread
            thread.start()
        return {
            "collaboration_id": collaboration_id,
            "started_count": len(claimed_tasks),
            "results": [],
            "claimed_tasks": claimed_tasks,
            "session": self.store.get_session(collaboration_id),
            "dispatch_capacity": dispatch_capacity.payload(),
            "message": dispatch_capacity.reason if not claimed_tasks else "子 Agent 任务已进入统一执行队列。",
        }

    def start_task(self, collaboration_id: str, task_id: str) -> dict[str, Any]:
        if not self._claim_session(collaboration_id):
            return {
                "result": None,
                "session": self.store.get_session(collaboration_id),
                "message": "协作会话正在调度中。",
            }
        reservation = (collaboration_id, task_id)
        reserved = False
        try:
            ready_task_ids = {
                str(task.get("task_id") or "")
                for task in self.store.ready_tasks(collaboration_id)
            }
            if task_id in ready_task_ids:
                with self._dispatch_lock:
                    dispatch_capacity = self._dispatch_capacity(collaboration_id, limit=1)
                    if dispatch_capacity.capacity == 0:
                        session = self.store.mark_tasks_waiting_for_inference_capacity(
                            collaboration_id,
                            task_ids=[task_id],
                            capacity=dispatch_capacity.payload(),
                            message=dispatch_capacity.reason,
                        )
                        self.runtime_factory().emit_collaboration_session_updated(
                            collaboration_id=collaboration_id,
                            session=session,
                        )
                        return {
                            "result": None,
                            "session": session,
                            "message": dispatch_capacity.reason,
                            "dispatch_capacity": dispatch_capacity.payload(),
                        }
                    self._reserved_worker_tasks.add(reservation)
                    reserved = True
            orchestrator = CollaborationOrchestrator(
                store=self.store,
                runtime=self.runtime_factory(),
            )
            result = orchestrator.start_task(collaboration_id, task_id)
        finally:
            if reserved:
                with self._dispatch_lock:
                    self._reserved_worker_tasks.discard(reservation)
            self._release_session(collaboration_id)
            self.store.release_worker_lease_unless_blocked(collaboration_id, task_id)
        self._continue_after_worker_result(collaboration_id, result)
        return {"result": result, "session": self.store.get_session(collaboration_id)}

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
            resume_payload = _approval_resume_payload(task, payload, decided_by="user")
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
        finally:
            self._release_session(collaboration_id)
            self.store.release_worker_lease_unless_blocked(collaboration_id, task_id)
        self._continue_after_worker_result(collaboration_id, result)
        return {"result": result, "session": self.store.get_session(collaboration_id)}

    def dispatch_delegated_sessions(self) -> None:
        self.cleanup_retried_task_sessions()
        self.cancel_requested_tasks()
        self.cancel_requested_evolutions()
        for session in self.store.list_auto_dispatch_sessions():
            collaboration_id = str(session.get("collaboration_id") or "").strip()
            if not collaboration_id:
                continue
            try:
                self.process_task_approval_decisions(collaboration_id)
                self._drain_main_agent_events(collaboration_id)
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

    def cancel_requested_evolutions(self) -> int:
        cancelled = 0
        for request_id, runtime in list(self._evolution_runtimes.items()):
            collaboration_id = self._evolution_collaboration_ids.get(request_id)
            if not collaboration_id:
                continue
            request = self.store.get_evolution_request(collaboration_id, request_id)
            if str(request.get("status") or "") != "cancelled":
                continue
            requested = runtime.cancel_active_requests(reason="parent_agent_cancelled_evolution")
            cancelled += requested
            thread = self._evolution_threads.get(request_id)
            if requested == 0 and (thread is None or not thread.is_alive()):
                runtime.abort_session(
                    package_id=str(request.get("package_id") or ""),
                    session_id=str(request.get("evolution_session_id") or ""),
                    reason="parent_agent_cancelled_evolution",
                )
                self._evolution_runtimes.pop(request_id, None)
                self._evolution_collaboration_ids.pop(request_id, None)
        return cancelled

    def _run_loop(self) -> None:
        while not self._stop_event.wait(self.poll_interval_seconds):
            self.dispatch_delegated_sessions()

    def _dispatch_soon_worker(self, collaboration_id: str) -> None:
        try:
            self.cleanup_retried_task_sessions()
            self.process_task_approval_decisions(collaboration_id)
            self._drain_main_agent_events(collaboration_id)
            self.dispatch_ready(collaboration_id)
        except Exception as exc:
            self.logger.warning(
                "Collaboration dispatch failed for %s: %s: %s",
                collaboration_id,
                type(exc).__name__,
                exc,
            )

    def process_task_approval_decisions(self, collaboration_id: str) -> None:
        claimed_decisions: list[tuple[str, dict[str, Any]]] = []
        with self._dispatch_lock:
            capacity = self._dispatch_capacity(collaboration_id).capacity
            if capacity <= 0:
                return
            pending = self.store.list_pending_task_approval_decisions(collaboration_id)
            for item in pending:
                if len(claimed_decisions) >= capacity:
                    break
                task = item.get("task") if isinstance(item.get("task"), dict) else {}
                task_id = str(task.get("task_id") or "").strip()
                if not task_id:
                    continue
                claimed = self.store.claim_task_approval_decision(collaboration_id, task_id)
                if claimed is None:
                    continue
                self._reserved_worker_tasks.add((collaboration_id, task_id))
                claimed_decisions.append((task_id, claimed))
        for task_id, claimed in claimed_decisions:
            threading.Thread(
                target=self._run_task_approval_decision,
                args=(collaboration_id, task_id, claimed),
                name=f"collaboration-approval-{task_id[:8]}",
                daemon=True,
            ).start()

    def _run_task_approval_decision(
        self,
        collaboration_id: str,
        task_id: str,
        claimed: dict[str, Any],
    ) -> None:
        task = claimed.get("task") if isinstance(claimed.get("task"), dict) else {}
        decision = claimed.get("decision") if isinstance(claimed.get("decision"), dict) else {}
        result = None
        try:
            orchestrator = CollaborationOrchestrator(
                store=self.store,
                runtime=self.runtime_factory(),
            )
            result = orchestrator.resume_task_approval(
                collaboration_id,
                task_id,
                resume_payload=_approval_resume_payload(
                    task,
                    decision,
                    decided_by="main_agent",
                ),
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self.store.fail_task_approval_decision(collaboration_id, task_id, error)
            self.logger.warning(
                "Main Agent approval decision failed for %s/%s: %s",
                collaboration_id,
                task_id,
                error,
            )
        finally:
            with self._dispatch_lock:
                self._reserved_worker_tasks.discard((collaboration_id, task_id))
            self.store.release_worker_lease_unless_blocked(collaboration_id, task_id)
        if result is not None:
            self._continue_after_worker_result(collaboration_id, result)
        else:
            self._continue_after_worker_result(
                collaboration_id,
                None,
                fallback_message=f"子任务 {task_id} 的主 Agent 工具审批决定执行失败，请检查并重新处理。",
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

    def _update_task(
        self,
        collaboration_id: str,
        task_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        session = self.store.update_task(collaboration_id, task_id, payload)
        self.runtime_factory().emit_collaboration_session_updated(
            collaboration_id=collaboration_id,
            session=session,
        )
        return session

    def _dispatch_capacity(
        self,
        collaboration_id: str,
        *,
        limit: int | None = None,
    ) -> CollaborationDispatchCapacity:
        inference = self.inference_capacity_probe()
        session = self.store.get_session(collaboration_id)
        execution_config = session.get("execution_config") if isinstance(session.get("execution_config"), dict) else {}
        max_parallel = normalize_max_parallel_sub_agents(
            execution_config.get("max_parallel_sub_agents"),
            fallback=inference.total_slots,
        )
        active_keys = self.store.active_worker_task_keys() | self._reserved_worker_tasks
        with self._lock:
            active_background_requests = len(self._active_sub_agent_requests)
        active = len(active_keys) + active_background_requests
        sub_agent_capacity = max(0, max_parallel - active)
        capacity = (
            min(sub_agent_capacity, inference.available_slots)
            if inference.live
            else sub_agent_capacity
        )
        if limit is not None:
            capacity = min(capacity, max(0, limit))
        return CollaborationDispatchCapacity(
            capacity=capacity,
            max_parallel_sub_agents=max_parallel,
            active_sub_agents=active,
            inference=inference,
            reason=_dispatch_capacity_reason(
                capacity=capacity,
                max_parallel_sub_agents=max_parallel,
                active_sub_agents=active,
                inference=inference,
            ),
        )

    def _run_worker_task(self, collaboration_id: str, task_id: str) -> None:
        result = None
        try:
            orchestrator = CollaborationOrchestrator(
                store=self.store,
                runtime=self.runtime_factory(),
            )
            result = orchestrator.start_task(collaboration_id, task_id)
        except Exception as exc:
            self.logger.warning(
                "Collaboration worker failed for %s/%s: %s: %s",
                collaboration_id,
                task_id,
                type(exc).__name__,
                exc,
            )
            try:
                self._update_task(
                    collaboration_id,
                    task_id,
                    {
                        "status": "failed",
                        "result_summary": f"worker 调度失败：{type(exc).__name__}: {exc}",
                        "result_payload": {"runtime_status": "failed", "error": f"{type(exc).__name__}: {exc}"},
                    },
                )
            except Exception:
                self.logger.exception("Failed to record collaboration worker failure for %s/%s", collaboration_id, task_id)
        finally:
            self._release_completed_worker_runtime(collaboration_id, task_id)
            self.store.release_worker_lease_unless_blocked(collaboration_id, task_id)
        if result is not None:
            self._continue_after_worker_result(collaboration_id, result)
        else:
            self._continue_after_worker_result(
                collaboration_id,
                None,
                fallback_message=f"子任务 {task_id} 执行失败，请检查失败原因并决定是否重试、改派或取消。",
            )

    def _continue_after_worker_result(
        self,
        collaboration_id: str,
        result: Any | None,
        *,
        fallback_message: str | None = None,
    ) -> None:
        if result is not None:
            self._publish_parent_workspace_delivery(collaboration_id, result)
            user_message = _main_agent_continuation_message_from_result(result)
            task_id = str(getattr(result, "task_id", "") or "").strip()
            message_metadata = _main_agent_continuation_metadata_from_result(
                result,
                assignee_package_id=_assignee_package_id_for_task(self.store.get_session(collaboration_id), task_id),
            )
            status = str(getattr(result, "status", "") or "").strip()
            self._trigger_main_agent_from_event(
                collaboration_id,
                user_message=user_message,
                message_metadata=message_metadata,
                task_id=task_id or None,
                event_ref=f"main-agent-trigger:{task_id}:{status}:{sha256(user_message.encode('utf-8')).hexdigest()[:16]}",
            )
            self.dispatch_soon(collaboration_id)
            return
        user_message = fallback_message or "协作子任务状态已更新，请检查当前任务状态并继续推进。"
        self._trigger_main_agent_from_event(
            collaboration_id,
            user_message=user_message,
            message_metadata=None,
            task_id=None,
            event_ref=None,
        )
        self.dispatch_soon(collaboration_id)

    def _publish_parent_workspace_delivery(self, collaboration_id: str, result: Any) -> None:
        artifact_refs = getattr(result, "artifact_refs", []) or []
        if not any(
            isinstance(item, dict) and item.get("workspace_scope") == "parent"
            for item in artifact_refs
        ):
            return
        session = self.store.get_session(collaboration_id)
        package_id = str(session.get("main_agent_package_id") or SYSTEM_CHAT_PACKAGE_ID).strip()
        package_session_id = str(session.get("main_agent_package_session_id") or "").strip()
        if not package_id or not package_session_id:
            return
        runtime = self.runtime_factory()
        try:
            payload = runtime.list_workspace_entries(
                package_id,
                scope="workdir",
                relative_path="",
                session_id=package_session_id,
            )
        except Exception as exc:
            self.logger.debug(
                "Failed to refresh parent workspace after Agent delivery %s: %s: %s",
                collaboration_id,
                type(exc).__name__,
                exc,
            )
            return
        runtime.emit_frontend_event(
            event(
                "workspace_entries_listed",
                request_id=None,
                session_id=package_session_id,
                mode="agent_package",
                graph_id="agent_delivery",
                producer_type="collaboration_service",
                payload=payload,
            )
        )

    def _release_completed_worker_runtime(self, collaboration_id: str, task_id: str) -> None:
        try:
            session = self.store.get_session(collaboration_id)
            task = _task_by_id(session, task_id)
        except Exception:
            return
        if str(task.get("status") or "") not in {"submitted", "completed", "failed", "cancelled"}:
            return
        package_id = str(task.get("assignee_package_id") or "").strip()
        session_id = str(task.get("assignee_session_id") or "").strip()
        if not package_id or not session_id:
            return
        try:
            closed = self.runtime_factory().shutdown_session_runtime(package_id, session_id=session_id)
        except Exception as exc:
            self.logger.debug(
                "Failed to close collaboration worker runtime for %s/%s: %s: %s",
                package_id,
                session_id,
                type(exc).__name__,
                exc,
            )
            return
        if closed:
            self.store.record_message(
                collaboration_id,
                speaker_type="system",
                speaker_package_id=package_id,
                message_kind="progress",
                content="子 Agent 运行实例已关闭以释放内存。",
                task_id=task_id,
            )

    def _release_sub_agent_request(self, task_type: str, request_id: str) -> None:
        with self._lock:
            self._active_sub_agent_requests.discard((task_type, request_id))

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
            self._release_sub_agent_request(SUB_AGENT_TASK_TYPE_MANUFACTURE, request_id)

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
        self._trigger_main_agent_from_event(
            collaboration_id,
            user_message=user_message,
            message_metadata=None,
            task_id=None,
            event_ref=None,
        )

    def _evolution_worker(self, collaboration_id: str, request_id: str) -> None:
        keep_runtime = False
        request_package_id = ""
        try:
            request = self.store.get_evolution_request(collaboration_id, request_id)
            request_package_id = str(request.get("package_id") or "")
            status = str(request.get("status") or "")
            runtime = self._evolution_runtimes.get(request_id)
            if status == "requested":
                runtime = AgentEvolutionRuntime(
                    package_restart_handler=(
                        lambda package_id, runtime_request_id: self.runtime_factory().restart_package_instance(
                            package_id,
                            request_id=runtime_request_id,
                        )
                    )
                )
                self._evolution_runtimes[request_id] = runtime
                self._evolution_collaboration_ids[request_id] = collaboration_id
                self.store.update_evolution_request(
                    collaboration_id,
                    request_id,
                    {
                        "status": "running",
                        "message": f"开始进化 Agent：{request.get('package_id')}",
                        "result_payload": {"runtime_status": "running"},
                    },
                )
                payload = request.get("request_payload") if isinstance(request.get("request_payload"), dict) else {}
                run = runtime.stream(
                    package_id=str(request.get("package_id") or ""),
                    user_input=str(payload.get("goal") or ""),
                    request_id=f"parent-evolve-{request_id}",
                    session_id=str(request.get("evolution_session_id") or ""),
                    attachments=None,
                    user_config=(
                        payload.get("runtime_user_config")
                        if isinstance(payload.get("runtime_user_config"), dict)
                        else None
                    ),
                )
            elif status == "resume_requested":
                if runtime is None:
                    raise RuntimeError("进化运行上下文已不可用，请重新发起进化")
                result_payload = request.get("result_payload") if isinstance(request.get("result_payload"), dict) else {}
                resume_payload = result_payload.get("resume_payload")
                if not isinstance(resume_payload, dict) or not resume_payload:
                    raise ValueError("resume_requested evolution is missing resume_payload")
                self.store.update_evolution_request(
                    collaboration_id,
                    request_id,
                    {
                        "status": "running",
                        "message": f"继续进化 Agent：{request.get('package_id')}",
                        "result_payload": {**result_payload, "runtime_status": "running"},
                    },
                )
                run = runtime.resume_stream(
                    package_id=str(request.get("package_id") or ""),
                    session_id=str(request.get("evolution_session_id") or ""),
                    resume_payload=resume_payload,
                    request_id=f"parent-evolve-resume-{request_id}",
                )
            else:
                return
            outcome = _consume_evolution_run(run)
            current = self.store.get_evolution_request(collaboration_id, request_id)
            if str(current.get("status") or "") == "cancelled":
                self._continue_after_evolution(
                    collaboration_id,
                    request_id=request_id,
                    package_id=str(request.get("package_id") or ""),
                    status="cancelled",
                    summary="进化请求已取消。",
                )
                return
            if outcome["status"] == "blocked":
                keep_runtime = True
                result_payload = {
                    "runtime_status": "blocked",
                    "pending_interrupt": outcome["interrupt"],
                    "summary": outcome["summary"],
                }
                self.store.update_evolution_request(
                    collaboration_id,
                    request_id,
                    {
                        "status": "blocked",
                        "message": outcome["message"],
                        "result_payload": result_payload,
                    },
                )
                self._continue_after_evolution(
                    collaboration_id,
                    request_id=request_id,
                    package_id=str(request.get("package_id") or ""),
                    status="blocked",
                    summary=outcome["message"],
                )
                return
            terminal_status = "completed" if outcome["status"] == "completed" else "failed"
            self.store.update_evolution_request(
                collaboration_id,
                request_id,
                {
                    "status": terminal_status,
                    "message": outcome["message"],
                    "result_payload": {
                        "runtime_status": outcome["status"],
                        "summary": outcome["summary"],
                        "terminal_payload": outcome["terminal_payload"],
                    },
                },
            )
            self._continue_after_evolution(
                collaboration_id,
                request_id=request_id,
                package_id=str(request.get("package_id") or ""),
                status=terminal_status,
                summary=outcome["message"],
            )
        except Exception as exc:
            self.logger.warning(
                "Collaboration evolution failed for %s/%s: %s: %s",
                collaboration_id,
                request_id,
                type(exc).__name__,
                exc,
            )
            try:
                self.store.update_evolution_request(
                    collaboration_id,
                    request_id,
                    {
                        "status": "failed",
                        "message": f"Agent 进化失败：{type(exc).__name__}: {exc}",
                        "result_payload": {"error": f"{type(exc).__name__}: {exc}"},
                    },
                )
                self._continue_after_evolution(
                    collaboration_id,
                    request_id=request_id,
                    package_id=request_package_id,
                    status="failed",
                    summary=f"Agent 进化失败：{type(exc).__name__}: {exc}",
                )
            except Exception:
                self.logger.exception("Failed to record evolution failure for %s", request_id)
        finally:
            if not keep_runtime:
                self._evolution_runtimes.pop(request_id, None)
                self._evolution_collaboration_ids.pop(request_id, None)
            with self._lock:
                self._evolution_threads.pop(request_id, None)
            self._release_sub_agent_request(SUB_AGENT_TASK_TYPE_EVOLVE, request_id)

    def _continue_after_evolution(
        self,
        collaboration_id: str,
        *,
        request_id: str,
        package_id: str,
        status: str,
        summary: str,
    ) -> None:
        self._trigger_main_agent_from_event(
            collaboration_id,
            user_message=(
                f"Agent 进化状态更新：request_id={request_id}, package_id={package_id or 'unknown'}, "
                f"status={status}。\n{summary}\n"
                "请根据当前状态继续：需要用户补充时明确提问；完成后向用户说明进化结果。"
            ),
            message_metadata={
                "collaboration_report": {
                    "kind": "evolution_report",
                    "status": status,
                    "assignee_package_id": package_id,
                    "summary": summary,
                    "evolution_request_id": request_id,
                    "artifact_count": 0,
                }
            },
            task_id=None,
            event_ref=None,
        )

    def _trigger_main_agent_from_event(
        self,
        collaboration_id: str,
        *,
        user_message: str,
        message_metadata: dict[str, Any] | None = None,
        task_id: str | None,
        event_ref: str | None,
    ) -> None:
        self.store.enqueue_main_agent_event(
            collaboration_id,
            user_message=user_message,
            message_metadata=message_metadata,
            task_id=task_id,
            event_ref=event_ref,
        )
        runtime = self.runtime_factory()
        runtime.emit_collaboration_session_updated(
            collaboration_id=collaboration_id,
            session=self.store.get_session(collaboration_id),
        )
        self._schedule_main_agent_event_drain(collaboration_id)

    def _drain_main_agent_events(self, collaboration_id: str) -> None:
        if not self._claim_session(collaboration_id):
            return
        active_batch: MainAgentEventBatch | None = None
        try:
            runtime = self.runtime_factory()
            orchestrator = CollaborationOrchestrator(
                store=self.store,
                runtime=runtime,
            )
            busy_reason = orchestrator.main_agent_busy_reason(collaboration_id)
            if busy_reason:
                self.logger.debug(
                    "Collaboration main agent is busy for %s: %s",
                    collaboration_id,
                    busy_reason,
                )
                return
            while True:
                ready_before = (
                    datetime.now(UTC)
                    - timedelta(seconds=self.main_agent_event_coalesce_window_seconds)
                ).isoformat()
                events = self.store.claim_main_agent_event_batch(
                    collaboration_id,
                    ready_before=ready_before,
                    limit=self.main_agent_event_batch_limit,
                )
                if not events:
                    break
                active_batch = _main_agent_event_batch(events)
                runtime.emit_collaboration_session_updated(
                    collaboration_id=collaboration_id,
                    session=self.store.get_session(collaboration_id),
                )
                continuation = orchestrator.continue_main_agent(
                    collaboration_id,
                    user_message=active_batch.user_message,
                    message_metadata=active_batch.message_metadata,
                    event_ref=f"{active_batch.event_ref}:main-agent",
                )
                if not continuation.succeeded:
                    error = f"main agent continuation {continuation.status}: {continuation.message}"
                    self.store.fail_main_agent_event_batch(list(active_batch.event_ids), error)
                    failed_batch = active_batch
                    active_batch = None
                    self.store.record_message(
                        collaboration_id,
                        speaker_type="system",
                        speaker_package_id=None,
                        message_kind="progress",
                        content=f"主 Agent 批量处理 {len(failed_batch.event_ids)} 个协作事件失败：{error}",
                        task_id=failed_batch.message_task_id,
                        event_ref=failed_batch.event_ref,
                    )
                    runtime.emit_collaboration_session_updated(
                        collaboration_id=collaboration_id,
                        session=self.store.get_session(collaboration_id),
                    )
                    break
                self.store.complete_main_agent_event_batch(list(active_batch.event_ids))
                active_batch = None
                runtime.emit_collaboration_session_updated(
                    collaboration_id=collaboration_id,
                    session=self.store.get_session(collaboration_id),
                )
        except Exception as exc:
            if active_batch is not None:
                self.store.fail_main_agent_event_batch(
                    list(active_batch.event_ids),
                    f"{type(exc).__name__}: {exc}",
                )
            self.logger.warning(
                "Collaboration main agent trigger failed for %s: %s: %s",
                collaboration_id,
                type(exc).__name__,
                exc,
            )
            self.store.record_message(
                collaboration_id,
                speaker_type="system",
                speaker_package_id=None,
                message_kind="progress",
                content=f"主 Agent 触发失败：{type(exc).__name__}: {exc}",
                task_id=active_batch.message_task_id if active_batch is not None else None,
                event_ref=active_batch.event_ref if active_batch is not None else None,
            )
            self.runtime_factory().emit_collaboration_session_updated(
                collaboration_id=collaboration_id,
                session=self.store.get_session(collaboration_id),
            )
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

    def _cancel_session_evolutions(self, session: dict[str, Any]) -> int:
        cancelled = 0
        threads: list[threading.Thread] = []
        for request in session.get("evolution_requests") or []:
            request_id = str(request.get("request_id") or "").strip()
            runtime = self._evolution_runtimes.get(request_id)
            if not request_id or runtime is None:
                continue
            requested = runtime.cancel_active_requests(reason="collaboration_session_deleted")
            cancelled += requested
            thread = self._evolution_threads.get(request_id)
            if requested == 0 and (thread is None or not thread.is_alive()):
                runtime.abort_session(
                    package_id=str(request.get("package_id") or ""),
                    session_id=str(request.get("evolution_session_id") or ""),
                    reason="collaboration_session_deleted",
                )
                self._evolution_runtimes.pop(request_id, None)
                self._evolution_collaboration_ids.pop(request_id, None)
            elif thread is not None:
                threads.append(thread)
        for thread in threads:
            if thread.is_alive():
                thread.join(timeout=5)
        still_running = [thread.name for thread in threads if thread.is_alive()]
        if still_running:
            raise RuntimeError(
                "evolution runtime did not stop before collaboration deletion: "
                + ", ".join(still_running)
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


def _collaboration_runtime_session_targets(session: dict[str, Any]) -> list[dict[str, str]]:
    targets: dict[tuple[str, str], dict[str, str]] = {}
    main_package_id = str(session.get("main_agent_package_id") or "").strip()
    main_session_id = str(session.get("main_agent_package_session_id") or "").strip()
    if main_package_id and main_session_id:
        targets[(main_package_id, main_session_id)] = {
            "package_id": main_package_id,
            "session_id": main_session_id,
            "source": "main_agent",
        }
    for task in session.get("tasks") or []:
        package_id = str(task.get("assignee_package_id") or "").strip()
        session_id = str(task.get("assignee_session_id") or "").strip()
        if not package_id or not session_id:
            continue
        targets[(package_id, session_id)] = {
            "package_id": package_id,
            "session_id": session_id,
            "source": "worker_task",
        }
    return [targets[key] for key in sorted(targets)]


def _main_agent_event_coalesce_window_seconds() -> float:
    raw = str(os.getenv(MAIN_AGENT_EVENT_COALESCE_WINDOW_ENV) or "").strip()
    if not raw:
        return DEFAULT_MAIN_AGENT_EVENT_COALESCE_WINDOW_SECONDS
    return _positive_float(raw, name=MAIN_AGENT_EVENT_COALESCE_WINDOW_ENV)


def _main_agent_event_batch_limit() -> int:
    raw = str(os.getenv(MAIN_AGENT_EVENT_BATCH_LIMIT_ENV) or "").strip()
    if not raw:
        return DEFAULT_MAIN_AGENT_EVENT_BATCH_LIMIT
    return _positive_int(raw, name=MAIN_AGENT_EVENT_BATCH_LIMIT_ENV)


def _positive_float(value: Any, *, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive number")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be a positive number")
    return parsed


def _positive_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if str(parsed) != str(value).strip() or parsed <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _collaboration_statistics(session: dict[str, Any], usage: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(UTC)
    started_at = _optional_utc_datetime(
        str(session.get("started_at") or session.get("created_at") or "")
    )
    completed_at = _optional_utc_datetime(
        str(
            session.get("completed_at")
            or (session.get("updated_at") if session.get("status") in {"completed", "failed", "cancelled"} else "")
            or ""
        )
    )
    wall_end = completed_at or now
    wall_duration_ms = (
        max(0, int((wall_end - started_at).total_seconds() * 1000))
        if started_at is not None
        else None
    )
    task_duration_ms = 0
    status_counts: dict[str, int] = {}
    retry_count = 0
    for task in session.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        status = str(task.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        visible_context = task.get("visible_context") if isinstance(task.get("visible_context"), dict) else {}
        if isinstance(visible_context.get("retry"), dict):
            retry_count += 1
        task_started = _optional_utc_datetime(str(task.get("started_at") or task.get("created_at") or ""))
        task_completed = _optional_utc_datetime(
            str(
                task.get("completed_at")
                or (task.get("updated_at") if status in TERMINAL_TASK_STATUSES else "")
                or ""
            )
        )
        if task_started is not None:
            task_duration_ms += max(0, int(((task_completed or now) - task_started).total_seconds() * 1000))
    return {
        "round_index": int(session.get("round_index") or 1),
        "wall_duration_ms": wall_duration_ms,
        "cumulative_task_duration_ms": task_duration_ms,
        "task_count": sum(status_counts.values()),
        "task_status_counts": status_counts,
        "retry_count": retry_count,
        "model_usage": usage,
    }


def _optional_utc_datetime(value: str) -> datetime | None:
    if not str(value or "").strip():
        return None
    return _parse_utc_datetime(value)


def _parse_utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value or "").strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("collaboration event timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _dispatch_capacity_reason(
    *,
    capacity: int,
    max_parallel_sub_agents: int,
    active_sub_agents: int,
    inference: ChatInferenceCapacity,
) -> str:
    if capacity > 0:
        source = "推理服务实时容量" if inference.live else "可并行子 Agent 数量设置"
        return f"还可启动 {capacity} 个子 Agent，容量来源：{source}。"
    if max_parallel_sub_agents <= 0:
        detail = f"（{inference.detail}）" if inference.detail else ""
        return f"未找到可用的子 Agent 并发配置，任务正在等待{detail}。"
    if active_sub_agents >= max_parallel_sub_agents:
        return (
            f"任务正在等待可并行子 Agent 名额：{active_sub_agents}/{max_parallel_sub_agents} "
            "个名额已占用。"
        )
    if inference.deferred_requests > 0:
        return (
            f"协作任务正在等待推理容量：llama-server 已有 "
            f"{inference.deferred_requests} 个排队请求。"
        )
    if inference.busy_slots >= inference.total_slots:
        return (
            f"协作任务正在等待推理容量：llama-server 的 "
            f"{inference.busy_slots}/{inference.total_slots} 个槽位正在处理请求。"
        )
    return "协作任务正在等待推理容量。"


def _main_agent_continuation_message_from_result(result: Any) -> str:
    task_id = str(getattr(result, "task_id", "") or "")
    status = str(getattr(result, "status", "") or "")
    summary = str(getattr(result, "result_summary", "") or "")
    assignee_session_id = str(getattr(result, "assignee_session_id", "") or "")
    artifact_refs = getattr(result, "artifact_refs", []) or []
    submit_label = "已提交" if status == "submitted" else status or "已更新"
    return (
        f"子 Agent 汇报：任务 {task_id} {submit_label}。\n"
        f"- task_id={task_id}\n"
        f"- status={status}\n"
        f"- assignee_session_id={assignee_session_id}\n"
        f"- summary={summary}\n"
        f"- artifact_refs={len(artifact_refs)}\n"
        "请像处理用户补充消息一样继续：先验收该交付；如果验收通过，按你此前在本会话中声明的协作计划继续创建或推进后续任务。"
    )


def _main_agent_continuation_metadata_from_result(result: Any, *, assignee_package_id: str | None = None) -> dict[str, Any]:
    task_id = str(getattr(result, "task_id", "") or "")
    status = str(getattr(result, "status", "") or "")
    summary = str(getattr(result, "result_summary", "") or "")
    assignee_session_id = str(getattr(result, "assignee_session_id", "") or "")
    artifact_refs = getattr(result, "artifact_refs", []) or []
    return {
        "collaboration_report": {
            "kind": "worker_report",
            "task_id": task_id,
            "status": status,
            "assignee_package_id": assignee_package_id or "",
            "assignee_session_id": assignee_session_id,
            "summary": summary,
            "artifact_count": len(artifact_refs),
        }
    }


def _main_agent_event_batch(events: list[dict[str, Any]]) -> MainAgentEventBatch:
    if not events:
        raise ValueError("main agent event batch must not be empty")
    event_ids: list[str] = []
    task_ids: list[str] = []
    source_events: list[dict[str, Any]] = []
    worker_reports: list[dict[str, Any]] = []
    artifact_count = 0
    lines = [
        f"系统在短时间窗口内汇总了 {len(events)} 个协作事件。",
        "请一次性检查全部事件和当前协作状态，统一验收并继续推进，避免为同一批状态变化重复规划。",
    ]
    for index, event in enumerate(events, start=1):
        event_id = str(event.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("main agent event is missing event_id")
        task_id = str(event.get("task_id") or "").strip()
        event_ref = str(event.get("event_ref") or "").strip()
        user_message = str(event.get("user_message") or "").strip()
        message_metadata = (
            event.get("message_metadata")
            if isinstance(event.get("message_metadata"), dict)
            else {}
        )
        report = message_metadata.get("collaboration_report")
        if isinstance(report, dict):
            worker_reports.append(dict(report))
            report_artifact_count = report.get("artifact_count")
            if isinstance(report_artifact_count, int) and not isinstance(report_artifact_count, bool):
                artifact_count += max(0, report_artifact_count)
        event_ids.append(event_id)
        if task_id and task_id not in task_ids:
            task_ids.append(task_id)
        source_events.append(
            {
                "event_id": event_id,
                "task_id": task_id or None,
                "event_ref": event_ref or None,
                "user_message": user_message,
                "message_metadata": message_metadata,
            }
        )
        lines.extend(
            [
                "",
                f"事件 {index}：",
                f"- event_id={event_id}",
                f"- task_id={task_id or '无'}",
                f"- event_ref={event_ref or '无'}",
                "- 原始消息：",
                user_message,
            ]
        )
    digest = sha256("\n".join(event_ids).encode("utf-8")).hexdigest()[:20]
    batch_ref = f"main-agent-event-batch:{digest}"
    metadata = {
        "collaboration_report": {
            "kind": "worker_report_batch",
            "status": "updated",
            "summary": f"已汇总 {len(events)} 个协作事件，由主 Agent 统一处理。",
            "artifact_count": artifact_count,
            "worker_reports": worker_reports,
        },
        "collaboration_event_batch": {
            "event_ref": batch_ref,
            "event_count": len(events),
            "events": source_events,
            "worker_reports": worker_reports,
        },
    }
    return MainAgentEventBatch(
        event_ids=tuple(event_ids),
        task_ids=tuple(task_ids),
        event_ref=batch_ref,
        user_message="\n".join(lines),
        message_metadata=metadata,
    )


def _assignee_package_id_for_task(session: dict[str, Any], task_id: str) -> str | None:
    for task in session.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        if str(task.get("task_id") or "") == task_id:
            return str(task.get("assignee_package_id") or "").strip() or None
    return None


def _approval_resume_payload(
    task: dict[str, Any],
    payload: dict[str, Any],
    *,
    decided_by: str,
) -> dict[str, Any]:
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
        "approval": {
            "decision": action,
            "approved_by": decided_by,
            "reason": str(payload.get("decision_reason") or payload.get("revision_guidance") or "").strip(),
        },
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


def _consume_evolution_run(run: Any) -> dict[str, Any]:
    visible = VisibleAssistantOutputAccumulator()
    for stream_mode, chunk in run.events:
        if stream_mode != "frontend_event":
            continue
        item = chunk if isinstance(chunk, FactoryFrontendEvent) else FactoryFrontendEvent.model_validate(chunk)
        visible.accept(item)
        if item.event_type in INTERRUPT_TERMINAL_EVENT_TYPES:
            payload = item.payload if isinstance(item.payload, dict) else {}
            message = _evolution_interrupt_message(payload, fallback=visible.content)
            return {
                "status": "blocked",
                "message": message,
                "summary": visible.content or message,
                "interrupt": {
                    "event_id": item.event_id,
                    "event_type": item.event_type,
                    "request_id": item.request_id,
                    "payload": payload,
                },
                "terminal_payload": {},
            }
        if item.event_type in RUN_TERMINAL_EVENT_TYPES:
            runtime_status = runtime_stream_status(item)
            payload = item.payload if isinstance(item.payload, dict) else {}
            published = runtime_status == "completed" and str(payload.get("status") or "") == "published"
            message = visible.content or str(item.message or payload.get("message") or "").strip()
            if not message:
                message = "Agent 进化已完成并发布。" if published else f"Agent 进化未完成：{runtime_status}"
            if runtime_status == "completed" and not published:
                message = f"{message}\n\n进化运行结束但没有形成已发布变更。"
            return {
                "status": "completed" if published else "failed",
                "message": message,
                "summary": visible.content or message,
                "interrupt": {},
                "terminal_payload": payload,
            }
    return {
        "status": "failed",
        "message": "Agent 进化运行流结束但没有终止事件。",
        "summary": visible.content or "",
        "interrupt": {},
        "terminal_payload": {},
    }


def _evolution_interrupt_message(payload: dict[str, Any], *, fallback: str | None) -> str:
    for key in ("message", "question", "prompt"):
        text = str(payload.get(key) or "").strip()
        if text:
            return text
    requests = payload.get("requests") if isinstance(payload.get("requests"), list) else []
    names = [
        str(item.get("tool_name") or item.get("tool_id") or item.get("name") or "").strip()
        for item in requests
        if isinstance(item, dict)
    ]
    clean_names = [name for name in names if name]
    if clean_names:
        return "进化 Agent 等待工具批准：" + "、".join(clean_names)
    return str(fallback or "进化 Agent 等待用户补充信息。").strip()
