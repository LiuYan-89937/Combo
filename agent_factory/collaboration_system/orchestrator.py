from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import shutil
from typing import Any
from uuid import uuid4

from agent_factory.collaboration_system.event_projection import CollaborationWorkerEventRecorder
from agent_factory.collaboration_system.prompting import build_main_agent_collaboration_prompt
from agent_factory.collaboration_system.store import CollaborationStore
from agent_factory.collaboration_system.store import SYSTEM_CHAT_PACKAGE_ID
from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentPackageRuntimeManager
from agent_factory.factory_graph.frontend_bridge.agent_package_paths import host_runtime_root
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import VisibleAssistantOutputAccumulator
from agent_factory.factory_graph.frontend_bridge.runtime_events import (
    INTERRUPT_TERMINAL_EVENT_TYPES,
    RUN_TERMINAL_EVENT_TYPES,
    runtime_stream_status,
)
from agent_factory.factory_graph.session import FactorySessionManager


COLLABORATION_SHARED_DIR = "collaboration_shared"
WORKER_ARTIFACT_SKIP_DIRS = {"input_files", COLLABORATION_SHARED_DIR, ".cache", "__pycache__"}
DEFAULT_MAX_COLLABORATION_ARTIFACT_BYTES = 200 * 1024 * 1024
MAX_COLLABORATION_ARTIFACT_BYTES_ENV = "AGENTFACTORY_COLLABORATION_MAX_ARTIFACT_BYTES"
MAX_DELEGATED_APPROVALS_PER_TASK = 20


@dataclass(frozen=True, slots=True)
class CollaborationRunTaskResult:
    collaboration_id: str
    task_id: str
    status: str
    assignee_session_id: str | None
    result_summary: str
    artifact_refs: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class WorkerRunOutcome:
    status: str
    message: str
    assignee_session_id: str | None
    tool_activities: list[dict[str, Any]]
    interrupt_payload: dict[str, Any] | None = None


class CollaborationOrchestrator:
    def __init__(
        self,
        *,
        store: CollaborationStore | None = None,
        runtime: AgentPackageRuntimeManager | None = None,
    ) -> None:
        self.store = store or CollaborationStore()
        self.runtime = runtime or AgentPackageRuntimeManager()

    def start_ready_tasks(self, collaboration_id: str, *, limit: int | None = None) -> dict[str, Any]:
        remaining = limit if limit is None else max(0, limit)
        results: list[CollaborationRunTaskResult] = []
        while remaining is None or remaining > 0:
            tasks = _one_ready_task_per_assignee(self.store.ready_tasks(collaboration_id))
            if remaining is not None:
                tasks = tasks[:remaining]
            if not tasks:
                break
            batch_results = self._start_task_batch(collaboration_id, tasks)
            results.extend(batch_results)
            if remaining is not None:
                remaining -= len(batch_results)
            if not _has_successful_submission(batch_results):
                break
        return {
            "collaboration_id": collaboration_id,
            "started_count": len(results),
            "results": [asdict(result) for result in results],
            "session": self.store.get_session(collaboration_id),
        }

    def _start_task_batch(
        self,
        collaboration_id: str,
        tasks: list[dict[str, Any]],
    ) -> list[CollaborationRunTaskResult]:
        if len(tasks) <= 1:
            return [self.start_task(collaboration_id, str(task["task_id"])) for task in tasks]
        results: list[CollaborationRunTaskResult] = []
        with ThreadPoolExecutor(max_workers=len(tasks), thread_name_prefix="collab-worker") as executor:
            futures = {
                executor.submit(self.start_task, collaboration_id, str(task["task_id"])): task
                for task in tasks
            }
            for future in as_completed(futures):
                results.append(future.result())
        return results

    def continue_main_agent(self, collaboration_id: str, *, user_message: str, event_ref: str | None = None) -> None:
        session = self.store.get_session(collaboration_id)
        if str(session.get("status") or "") in {"completed", "failed", "cancelled"}:
            return
        package_id = str(session.get("main_agent_package_id") or SYSTEM_CHAT_PACKAGE_ID).strip() or SYSTEM_CHAT_PACKAGE_ID
        factory_session_id = str(session.get("main_factory_session_id") or "").strip()
        package_session_id = self._main_agent_package_session_id(session, package_id=package_id)
        request_id = f"collab-main-{collaboration_id[:8]}-{uuid4().hex[:8]}"
        self.store.record_message(
            collaboration_id,
            speaker_type="system",
            speaker_package_id=package_id,
            message_kind="main_agent_triggered",
            content="主 Agent 已被协作事件触发，正在处理子任务提交/阻塞/失败状态。",
            task_id=None,
            event_ref=event_ref,
        )
        prompt = build_main_agent_collaboration_prompt(
            user_message=user_message,
            session=session,
        )
        run = self.runtime.stream(
            package_id,
            user_input=prompt,
            display_user_input=user_message,
            session_id=package_session_id,
            request_id=request_id,
            user_config={
                "collaboration_id": collaboration_id,
                "runtime_tool_access": {
                    "extra_allowed_tool_ids": ["collaboration", "agent_list", "agent_search", "agent_manufacture"],
                },
            },
            require_ready=True,
            session_kind="collaboration_main",
            collaboration_id=collaboration_id,
            visible_in_agent_session_list=True,
        )
        main_session_id = str((run.session or {}).get("session_id") or "").strip()
        if main_session_id and main_session_id != str(session.get("main_agent_package_session_id") or ""):
            self.store.update_session(collaboration_id, {"main_agent_package_session_id": main_session_id})

        output = VisibleAssistantOutputAccumulator()
        tool_activities: list[dict[str, Any]] = []
        status = "failed"
        message = ""
        for stream_mode, chunk in run.events:
            if stream_mode != "frontend_event":
                continue
            item = chunk if isinstance(chunk, FactoryFrontendEvent) else FactoryFrontendEvent.model_validate(chunk)
            output.accept(item)
            _upsert_tool_activity(tool_activities, item)
            if item.event_type in RUN_TERMINAL_EVENT_TYPES:
                status = runtime_stream_status(item)
                message = str(item.message or item.payload.get("message") or "").strip()
                break
            if item.event_type in INTERRUPT_TERMINAL_EVENT_TYPES:
                status = "blocked"
                message = _interrupt_summary(item)
                break

        if main_session_id:
            self.runtime.finish_session_turn(
                package_id,
                session_id=main_session_id,
                request_id=request_id,
                final_answer=output.content,
                reasoning_content=output.reasoning_content,
                status=status,
                tool_activities=tool_activities,
                trace_ref=_latest_trace_ref(package_id),
            )
            if package_id == SYSTEM_CHAT_PACKAGE_ID and factory_session_id:
                factory_record = _sync_factory_chat_session_from_agent_session(
                    factory_session_id=factory_session_id,
                    request_id=request_id,
                    user_input=user_message,
                    agent_session=self.runtime.load_session(package_id, main_session_id),
                )
                self.runtime.emit_factory_session_updated(session_record=factory_record, mode="chat")
        if status == "completed":
            self.store.record_message(
                collaboration_id,
                speaker_type="main_agent",
                speaker_package_id=package_id,
                message_kind="progress",
                content=_short_summary(output.content or "主 Agent 已处理协作事件。"),
                task_id=None,
            )
            return
        self.store.record_message(
            collaboration_id,
            speaker_type="system",
            speaker_package_id=package_id,
            message_kind="progress",
            content=f"主 Agent 处理协作事件失败：{message or status}",
            task_id=None,
        )

    def _main_agent_package_session_id(self, session: dict[str, Any], *, package_id: str) -> str | None:
        if package_id != SYSTEM_CHAT_PACKAGE_ID:
            return str(session.get("main_agent_package_session_id") or "").strip() or None
        factory_session_id = str(session.get("main_factory_session_id") or "").strip()
        if factory_session_id:
            try:
                record = FactorySessionManager.from_env().load(factory_session_id)
                linked_session_id = str(record.chat_agent_package_session_id or "").strip()
                if linked_session_id:
                    stored_session_id = str(session.get("main_agent_package_session_id") or "").strip()
                    if linked_session_id != stored_session_id:
                        self.store.update_session(
                            str(session.get("collaboration_id") or ""),
                            {"main_agent_package_session_id": linked_session_id},
                        )
                    return linked_session_id
            except Exception:
                pass
        return str(session.get("main_agent_package_session_id") or "").strip() or None

    def start_task(self, collaboration_id: str, task_id: str) -> CollaborationRunTaskResult:
        session = self.store.get_session(collaboration_id)
        task = _task_by_id(session, task_id)
        if not _dependencies_satisfied(session, task):
            self.store.update_task(collaboration_id, task_id, {"status": "queued"})
            self.store.record_message(
                collaboration_id,
                speaker_type="system",
                speaker_package_id=task.get("assignee_package_id"),
                message_kind="progress",
                content="任务依赖尚未完成，已进入等待队列。",
                task_id=task_id,
            )
            return CollaborationRunTaskResult(
                collaboration_id=collaboration_id,
                task_id=task_id,
                status="queued",
                assignee_session_id=task.get("assignee_session_id"),
                result_summary="任务依赖尚未完成，已进入等待队列。",
                artifact_refs=list(task.get("artifact_refs") or []),
            )

        package_id = str(task.get("assignee_package_id") or "").strip()
        if not package_id:
            raise ValueError("task assignee_package_id is required")
        init_request_id = f"collab-init-{task_id}"
        self.store.update_task(
            collaboration_id,
            task_id,
            {
                "status": "accepted",
                "result_payload": {
                    "runtime_status": "initializing",
                    "active_request_id": init_request_id,
                    "active_package_id": package_id,
                },
            },
        )
        self.runtime.initialize_package(package_id, request_id=init_request_id)
        run_request_id = f"collab-task-{task_id}-{uuid4().hex[:8]}"
        self.store.update_task(
            collaboration_id,
            task_id,
            {
                "status": "working",
                "result_payload": {
                    "runtime_status": "working",
                    "active_request_id": run_request_id,
                    "active_package_id": package_id,
                },
            },
        )
        self.store.record_message(
            collaboration_id,
            speaker_type="system",
            speaker_package_id=package_id,
            message_kind="progress",
            content=f"子 Agent {package_id} 已开始执行任务。",
            task_id=task_id,
        )

        worker_session = self.runtime.ensure_session(
            package_id,
            session_id=task.get("assignee_session_id") or None,
            first_user_input=str(task.get("task_text") or ""),
            session_kind="collaboration_worker",
            collaboration_id=collaboration_id,
            collaboration_task_id=task_id,
            visible_in_agent_session_list=True,
        )
        assignee_session_id = str(worker_session.get("session_id") or task.get("assignee_session_id") or "").strip()
        if not assignee_session_id:
            raise RuntimeError("collaboration worker session was not created")
        self.store.update_task(
            collaboration_id,
            task_id,
            {"assignee_session_id": assignee_session_id},
        )
        worker_workdir = self.runtime.session_workdir_for_package(package_id, assignee_session_id)
        shared_materials = _materialize_authorized_artifacts(
            shared_workspace=self.store.session_workdir(collaboration_id),
            worker_workdir=worker_workdir,
            artifacts=task.get("input_artifacts") or [],
        )
        prompt = _worker_prompt(
            session=session,
            task=task,
            shared_materials=shared_materials,
        )
        run = self.runtime.stream(
            package_id,
            user_input=prompt,
            session_id=assignee_session_id,
            request_id=run_request_id,
            require_ready=True,
            session_kind="collaboration_worker",
            collaboration_id=collaboration_id,
            collaboration_task_id=task_id,
            visible_in_agent_session_list=True,
        )
        assignee_session_id = str((run.session or {}).get("session_id") or assignee_session_id).strip()
        if not assignee_session_id:
            raise RuntimeError("collaboration worker run did not provide an agent session id")
        before_snapshot = _workspace_snapshot(worker_workdir)
        output = VisibleAssistantOutputAccumulator()
        event_recorder = CollaborationWorkerEventRecorder(
            store=self.store,
            collaboration_id=collaboration_id,
            task_id=task_id,
            package_id=package_id,
        )
        outcome = self._consume_worker_run(
            run=run,
            package_id=package_id,
            collaboration_id=collaboration_id,
            task_id=task_id,
            approval_mode=str(session.get("approval_mode") or ""),
            output=output,
            event_recorder=event_recorder,
        )
        self._finish_worker_session_turn(
            package_id=package_id,
            session_id=outcome.assignee_session_id or assignee_session_id,
            request_id=run_request_id,
            output=output,
            status=outcome.status,
            tool_activities=outcome.tool_activities,
        )
        if outcome.status != "completed":
            summary = outcome.message or f"worker runtime finished with status {outcome.status}"
            task_status = "blocked" if outcome.status == "blocked" else "failed"
            self.store.update_task(
                collaboration_id,
                task_id,
                {
                    "status": task_status,
                    "assignee_session_id": outcome.assignee_session_id or assignee_session_id,
                    "result_summary": summary,
                    "result_payload": {
                        "runtime_status": outcome.status,
                        **({"pending_interrupt": outcome.interrupt_payload} if outcome.interrupt_payload else {}),
                    },
                },
            )
            self.store.record_message(
                collaboration_id,
                speaker_type="system",
                speaker_package_id=package_id,
                message_kind="progress",
                content=summary,
                task_id=task_id,
            )
            self.store.record_message(
                collaboration_id,
                speaker_type="system",
                speaker_package_id=package_id,
                message_kind="progress",
                content=f"任务{task_status}，已通知主 Agent 处理该状态。",
                task_id=task_id,
            )
            return CollaborationRunTaskResult(
                collaboration_id=collaboration_id,
                task_id=task_id,
                status=task_status,
                assignee_session_id=outcome.assignee_session_id or assignee_session_id,
                result_summary=summary,
                artifact_refs=[],
            )

        return self._submit_worker_result(
            collaboration_id=collaboration_id,
            task=task,
            package_id=package_id,
            assignee_session_id=outcome.assignee_session_id or assignee_session_id,
            output=output,
            worker_workdir=worker_workdir,
            before_snapshot=before_snapshot,
        )

    def resume_task_approval(
        self,
        collaboration_id: str,
        task_id: str,
        *,
        resume_payload: dict[str, Any],
    ) -> CollaborationRunTaskResult:
        session = self.store.get_session(collaboration_id)
        task = _task_by_id(session, task_id)
        package_id = str(task.get("assignee_package_id") or "").strip()
        assignee_session_id = str(task.get("assignee_session_id") or "").strip()
        if not package_id:
            raise ValueError("task assignee_package_id is required")
        if not assignee_session_id:
            raise ValueError("blocked task does not have an assignee_session_id")
        worker_workdir = self.runtime.session_workdir_for_package(package_id, assignee_session_id)
        before_snapshot = _workspace_snapshot(worker_workdir)
        output = VisibleAssistantOutputAccumulator()
        event_recorder = CollaborationWorkerEventRecorder(
            store=self.store,
            collaboration_id=collaboration_id,
            task_id=task_id,
            package_id=package_id,
        )
        resume_request_id = f"collab-user-approval-{task_id}-{uuid4().hex[:8]}"
        self.store.update_task(
            collaboration_id,
            task_id,
            {
                "status": "working",
                "result_summary": "用户已处理 worker 审批，任务继续执行。",
                "result_payload": {
                    "runtime_status": "resumed",
                    "active_request_id": resume_request_id,
                    "active_package_id": package_id,
                },
            },
        )
        run = self.runtime.resume_stream(
            package_id,
            session_id=assignee_session_id,
            resume_payload=resume_payload,
            request_id=resume_request_id,
        )
        outcome = self._consume_worker_run(
            run=run,
            package_id=package_id,
            collaboration_id=collaboration_id,
            task_id=task_id,
            approval_mode=str(session.get("approval_mode") or ""),
            output=output,
            event_recorder=event_recorder,
        )
        self._finish_worker_session_turn(
            package_id=package_id,
            session_id=outcome.assignee_session_id or assignee_session_id,
            request_id=resume_request_id,
            output=output,
            status=outcome.status,
            tool_activities=outcome.tool_activities,
        )
        if outcome.status != "completed":
            summary = outcome.message or f"worker runtime finished with status {outcome.status}"
            task_status = "blocked" if outcome.status == "blocked" else "failed"
            self.store.update_task(
                collaboration_id,
                task_id,
                {
                    "status": task_status,
                    "assignee_session_id": outcome.assignee_session_id or assignee_session_id,
                    "result_summary": summary,
                    "result_payload": {
                        "runtime_status": outcome.status,
                        **({"pending_interrupt": outcome.interrupt_payload} if outcome.interrupt_payload else {}),
                    },
                },
            )
            return CollaborationRunTaskResult(
                collaboration_id=collaboration_id,
                task_id=task_id,
                status=task_status,
                assignee_session_id=outcome.assignee_session_id or assignee_session_id,
                result_summary=summary,
                artifact_refs=[],
            )
        return self._submit_worker_result(
            collaboration_id=collaboration_id,
            task=task,
            package_id=package_id,
            assignee_session_id=outcome.assignee_session_id or assignee_session_id,
            output=output,
            worker_workdir=worker_workdir,
            before_snapshot=before_snapshot,
        )

    def _submit_worker_result(
        self,
        *,
        collaboration_id: str,
        task: dict[str, Any],
        package_id: str,
        assignee_session_id: str | None,
        output: VisibleAssistantOutputAccumulator,
        worker_workdir: Path,
        before_snapshot: dict[str, tuple[int, int]],
    ) -> CollaborationRunTaskResult:
        task_id = str(task.get("task_id") or "")
        content = str(output.content or "").strip()
        if not content:
            content = "Worker completed but did not return visible content."
        shared_workspace = self.store.session_workdir(collaboration_id)
        delivery_artifact = _write_worker_delivery(
            shared_workspace,
            task=task,
            content=content,
        )
        worker_artifacts = _copy_worker_artifacts(
            worker_workdir,
            shared_workspace,
            before_snapshot=before_snapshot,
            task=task,
        )
        artifact_refs = [delivery_artifact, *worker_artifacts]
        self.store.update_task(
            collaboration_id,
            task_id,
            {
                "status": "submitted",
                "assignee_session_id": assignee_session_id,
                "result_summary": _short_summary(content),
                "result_payload": {"content": content, "reasoning_content": output.reasoning_content or ""},
                "artifact_refs": artifact_refs,
            },
        )
        self.store.record_message(
            collaboration_id,
            speaker_type="worker_agent",
            speaker_package_id=package_id,
            message_kind="delivery",
            content=_delivery_message(content, artifact_refs),
            task_id=task_id,
        )
        self.store.record_message(
            collaboration_id,
            speaker_type="system",
            speaker_package_id=package_id,
            message_kind="progress",
            content="任务已提交，主 Agent 可验收该交付；依赖该任务的后续任务将被自动调度。",
            task_id=task_id,
        )
        return CollaborationRunTaskResult(
            collaboration_id=collaboration_id,
            task_id=task_id,
            status="submitted",
            assignee_session_id=assignee_session_id,
            result_summary=_short_summary(content),
            artifact_refs=artifact_refs,
        )

    def _consume_worker_run(
        self,
        *,
        run: Any,
        package_id: str,
        collaboration_id: str,
        task_id: str,
        approval_mode: str,
        output: VisibleAssistantOutputAccumulator,
        event_recorder: CollaborationWorkerEventRecorder,
    ) -> WorkerRunOutcome:
        current_run = run
        assignee_session_id = str((current_run.session or {}).get("session_id") or "").strip() or None
        if assignee_session_id:
            self.store.update_task(
                collaboration_id,
                task_id,
                {"assignee_session_id": assignee_session_id},
            )
        delegated_approval_count = 0
        tool_activities: list[dict[str, Any]] = []
        while True:
            interrupted: FactoryFrontendEvent | None = None
            for stream_mode, chunk in current_run.events:
                if stream_mode != "frontend_event":
                    continue
                item = chunk if isinstance(chunk, FactoryFrontendEvent) else FactoryFrontendEvent.model_validate(chunk)
                output.accept(item)
                event_recorder.accept(item)
                _upsert_tool_activity(tool_activities, item)
                if item.event_type in RUN_TERMINAL_EVENT_TYPES:
                    return WorkerRunOutcome(
                        status=runtime_stream_status(item),
                        message=str(item.message or item.payload.get("message") or "").strip(),
                        assignee_session_id=assignee_session_id,
                        tool_activities=tool_activities,
                    )
                if item.event_type in INTERRUPT_TERMINAL_EVENT_TYPES:
                    interrupted = item
                    break
            if interrupted is None:
                return WorkerRunOutcome(
                    status="failed",
                    message="worker runtime stream ended without terminal status",
                    assignee_session_id=assignee_session_id,
                    tool_activities=tool_activities,
                )
            if not _is_tool_approval_interrupt(interrupted):
                return WorkerRunOutcome(
                    status="blocked",
                    message=_interrupt_summary(interrupted),
                    assignee_session_id=assignee_session_id,
                    tool_activities=tool_activities,
                    interrupt_payload=_pending_interrupt_payload(interrupted),
                )
            if approval_mode != "main_agent_delegated":
                return WorkerRunOutcome(
                    status="blocked",
                    message=_interrupt_summary(interrupted),
                    assignee_session_id=assignee_session_id,
                    tool_activities=tool_activities,
                    interrupt_payload=_pending_interrupt_payload(interrupted),
                )
            delegated_approval_count += 1
            if delegated_approval_count > MAX_DELEGATED_APPROVALS_PER_TASK:
                return WorkerRunOutcome(
                    status="blocked",
                    message="主 Agent 代理审批次数超过上限，任务已暂停。",
                    assignee_session_id=assignee_session_id,
                    tool_activities=tool_activities,
                )
            if not assignee_session_id:
                return WorkerRunOutcome(
                    status="blocked",
                    message="worker runtime interrupted before a session id was available.",
                    assignee_session_id=assignee_session_id,
                    tool_activities=tool_activities,
                    interrupt_payload=_pending_interrupt_payload(interrupted),
                )
            self.store.record_message(
                collaboration_id,
                speaker_type="main_agent",
                speaker_package_id=None,
                message_kind="approval",
                content="主 Agent 代理批准 worker 工具调用。",
                task_id=task_id,
                event_ref=f"{interrupted.event_id}:delegated-approval",
            )
            current_run = self.runtime.resume_stream(
                package_id,
                session_id=assignee_session_id,
                resume_payload=_approval_resume_payload(interrupted),
                request_id=f"collab-approve-{task_id}-{delegated_approval_count}-{uuid4().hex[:8]}",
            )

    def _finish_worker_session_turn(
        self,
        *,
        package_id: str,
        session_id: str | None,
        request_id: str,
        output: VisibleAssistantOutputAccumulator,
        status: str,
        tool_activities: list[dict[str, Any]],
    ) -> None:
        if not session_id:
            return
        self.runtime.finish_session_turn(
            package_id,
            session_id=session_id,
            request_id=request_id,
            final_answer=output.content,
            reasoning_content=output.reasoning_content,
            status=status,
            tool_activities=tool_activities,
            trace_ref=_latest_trace_ref(package_id),
        )


def _task_by_id(session: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in session.get("tasks") or []:
        if str(task.get("task_id") or "") == task_id:
            return task
    raise ValueError(f"collaboration task not found: {task_id}")


def _one_ready_task_per_assignee(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for task in tasks:
        assignee = str(task.get("assignee_package_id") or "").strip()
        if not assignee or assignee in seen:
            continue
        selected.append(task)
        seen.add(assignee)
    return selected


def _has_successful_submission(results: list[CollaborationRunTaskResult]) -> bool:
    return any(result.status in {"submitted", "completed"} for result in results)


def _main_agent_continuation_message(results: list[CollaborationRunTaskResult]) -> str:
    lines = ["子 Agent 汇报：协作子任务状态已更新。"]
    for result in results:
        lines.append(
            f"- task_id={result.task_id}; status={result.status}; summary={result.result_summary}; "
            f"artifact_refs={len(result.artifact_refs)}"
        )
    lines.append("请先验收提交结果；验收通过后，按你此前在本会话中声明的协作计划继续创建或推进后续任务。")
    return "\n".join(lines)


def _sync_factory_chat_session_from_agent_session(
    *,
    factory_session_id: str,
    request_id: str,
    user_input: str,
    agent_session: dict[str, Any],
) -> Any:
    manager = FactorySessionManager.from_env()
    record = manager.remember_first_user_input(factory_session_id, user_input)
    agent_session_id = str(agent_session.get("session_id") or "").strip()
    if agent_session_id and record.chat_agent_package_session_id != agent_session_id:
        record.chat_agent_package_session_id = agent_session_id
        manager.save(record)
    turns = agent_session.get("turns")
    if isinstance(turns, list):
        return manager.replace_turns_from_agent_session(
            factory_session_id,
            "chat",
            [turn for turn in turns if isinstance(turn, dict)],
        )
    return manager.start_turn(factory_session_id, "chat", request_id=request_id, user_input=user_input)


def _latest_trace_ref(package_id: str) -> dict[str, str] | None:
    trace_root = host_runtime_root(package_id) / "trace"
    runs_root = trace_root / "runs"
    if not runs_root.is_dir():
        return None
    trace_dirs = [path for path in runs_root.iterdir() if path.is_dir() and _is_safe_path_id(path.name)]
    if not trace_dirs:
        return None
    latest = max(trace_dirs, key=lambda path: path.stat().st_mtime)
    manifest_path = latest / "manifest.json"
    run_id = ""
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
        if isinstance(manifest, dict):
            run_id = str(manifest.get("run_id") or "").strip()
    if not run_id:
        run_id = _latest_trace_run_id(latest / "trace.jsonl")
    return {
        "trace_id": latest.name,
        "trace_root": str(trace_root),
        **({"run_id": run_id} if run_id else {}),
    }


def _latest_trace_run_id(trace_path: Path) -> str:
    try:
        lines = trace_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            run_id = str(item.get("run_id") or "").strip()
            if run_id:
                return run_id
    return ""


def _is_safe_path_id(value: str) -> bool:
    return bool(value) and all(char.isalnum() or char in {"-", "_"} for char in value)


def _dependencies_satisfied(session: dict[str, Any], task: dict[str, Any]) -> bool:
    tasks = {str(item.get("task_id") or ""): item for item in session.get("tasks") or []}
    for dependency_id in task.get("depends_on") or []:
        dependency = tasks.get(str(dependency_id))
        if str(dependency.get("status") if dependency else "") != "completed":
            return False
    return True


def _is_tool_approval_interrupt(item: FactoryFrontendEvent) -> bool:
    payload = item.payload if isinstance(item.payload, dict) else {}
    if item.event_type == "tool_approval_requested":
        return True
    return str(payload.get("type") or "").strip() == "tool_approval"


def _approval_resume_payload(item: FactoryFrontendEvent) -> dict[str, Any]:
    payload = item.payload if isinstance(item.payload, dict) else {}
    requests = payload.get("requests") if isinstance(payload.get("requests"), list) else []
    tool_call_ids = [
        str(request.get("tool_call_id") or "").strip()
        for request in requests
        if isinstance(request, dict) and str(request.get("tool_call_id") or "").strip()
    ]
    first = next((request for request in requests if isinstance(request, dict)), {})
    return {
        "action": "approve",
        "approved": True,
        "type": "tool_approval",
        "interrupt_event_id": item.event_id,
        "pending_request_id": item.request_id,
        "original_request_id": item.request_id,
        "tool_call_id": first.get("tool_call_id"),
        "tool_name": first.get("tool_name") or first.get("tool_id") or first.get("name"),
        "tool_call_ids": tool_call_ids or None,
        "requests": requests,
        "approval": {
            "decision": "approve",
            "approved_by": "collaboration_main_agent",
            "reason": "collaboration session approval_mode=main_agent_delegated",
        },
    }


def _pending_interrupt_payload(item: FactoryFrontendEvent) -> dict[str, Any]:
    payload = item.payload if isinstance(item.payload, dict) else {}
    return {
        "event_id": item.event_id,
        "event_type": item.event_type,
        "request_id": item.request_id,
        "session_id": item.session_id,
        "payload": payload,
        "resume_payload": _approval_resume_payload(item) if _is_tool_approval_interrupt(item) else {},
    }


TOOL_ACTIVITY_EVENT_STATUS = {
    "tool_call_proposed": "proposed",
    "tool_approval_requested": "approval",
    "tool_approval_resolved": "approval",
    "tool_call_started": "started",
    "tool_call_completed": "completed",
    "tool_call_failed": "failed",
    "tool_contract_invalid": "failed",
    "tool_observation_available": "observed",
}


def _upsert_tool_activity(activities: list[dict[str, Any]], item: FactoryFrontendEvent) -> None:
    status = TOOL_ACTIVITY_EVENT_STATUS.get(item.event_type)
    if status is None:
        return
    payload = item.payload if isinstance(item.payload, dict) else {}
    tool_call_id = _first_payload_text(payload, "tool_call_id", "toolCallId")
    tool_name = _first_payload_text(payload, "tool_name", "tool_id", "name") or "tool_call"
    activity_key = tool_call_id or str(item.span_id or item.event_id)
    existing_index = next(
        (
            index
            for index, activity in enumerate(activities)
            if activity.get("activityKey") == activity_key
            or (tool_call_id and activity.get("toolCallId") == tool_call_id)
        ),
        -1,
    )
    existing = activities[existing_index] if existing_index >= 0 else {}
    merged_payload = {
        **(existing.get("payload") if isinstance(existing.get("payload"), dict) else {}),
        **payload,
    }
    merged_payload["arguments"] = {
        **_payload_arguments(existing.get("payload") if isinstance(existing.get("payload"), dict) else {}),
        **_payload_arguments(payload),
    }
    activity = {
        "activityKey": str(existing.get("activityKey") or activity_key),
        "requestId": item.request_id or existing.get("requestId"),
        "eventType": item.event_type,
        "timestamp": item.timestamp,
        "createdAt": existing.get("createdAt") or item.timestamp,
        "stageId": item.stage_id or existing.get("stageId"),
        "nodeId": item.node_id or existing.get("nodeId"),
        "toolCallId": tool_call_id or existing.get("toolCallId"),
        "toolName": tool_name or existing.get("toolName") or "tool_call",
        "status": status,
        "approvalState": _approval_state(item, existing.get("approvalState")),
        "payload": merged_payload,
    }
    if existing_index >= 0:
        activities[existing_index] = activity
    else:
        activities.append(activity)


def _first_payload_text(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return None


def _payload_arguments(payload: dict[str, Any]) -> dict[str, Any]:
    arguments = payload.get("arguments")
    if isinstance(arguments, dict):
        return dict(arguments)
    args = payload.get("args")
    if isinstance(args, dict):
        return dict(args)
    return {}


def _approval_state(item: FactoryFrontendEvent, existing: Any) -> str | None:
    if item.event_type == "tool_approval_requested":
        return "pending"
    if item.event_type != "tool_approval_resolved":
        return str(existing) if existing else None
    payload = item.payload if isinstance(item.payload, dict) else {}
    approved = payload.get("approved")
    action = str(payload.get("action") or payload.get("decision") or "").strip().lower()
    if approved is True or action == "approve":
        return "approved"
    if approved is False or action in {"deny", "reject", "rejected"}:
        return "denied"
    return str(existing) if existing else None


def _interrupt_summary(item: FactoryFrontendEvent) -> str:
    payload = item.payload if isinstance(item.payload, dict) else {}
    requests = payload.get("requests") if isinstance(payload.get("requests"), list) else []
    names = [
        str(request.get("tool_name") or request.get("tool_id") or request.get("name") or "").strip()
        for request in requests
        if isinstance(request, dict)
    ]
    clean_names = [name for name in names if name]
    if clean_names:
        return "任务等待工具审批：" + "、".join(clean_names)
    return str(item.message or payload.get("message") or "任务等待人工输入或审批。").strip()


def _worker_prompt(*, session: dict[str, Any], task: dict[str, Any], shared_materials: dict[str, Any]) -> str:
    materials = _shared_materials_prompt(shared_materials)
    return "\n\n".join(
        item
        for item in [
            "你正在一个多 Agent 协作会话中作为被分配任务的子 Agent 工作。",
            "只完成当前任务，不要假设自己能看到其他子 Agent 的完整对话。需要使用共享材料时，只读取下面列出的授权文件。",
            f"协作会话：{session.get('title') or session.get('collaboration_id')}",
            f"任务 ID：{task.get('task_id')}",
            f"任务要求：{task.get('task_text')}",
            f"验收标准：{task.get('delivery_standard')}",
            f"可见上下文：{task.get('visible_context')}",
            materials,
            "交付要求：给出可由主 Agent 验收的完整结果。你在工作区中新建或修改的普通文件会被系统收集到协作共享工作区作为任务交付物。",
        ]
        if item
    )


def _materialize_authorized_artifacts(
    *,
    shared_workspace: Path,
    worker_workdir: Path,
    artifacts: list[Any],
) -> dict[str, Any]:
    requested_paths = _authorized_artifact_paths(artifacts)
    if not requested_paths:
        return {"items": [], "manifest_path": ""}
    materialized_root = worker_workdir / COLLABORATION_SHARED_DIR
    if materialized_root.exists():
        shutil.rmtree(materialized_root)
    materialized_root.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for relative in requested_paths:
        source = _safe_shared_path(shared_workspace, relative)
        target_relative = _shared_material_runtime_path(relative)
        target = worker_workdir / target_relative
        item = {
            "source_path": relative,
            "path": target_relative.as_posix(),
            "status": "missing",
        }
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            stat = target.stat()
            mime_type, _ = mimetypes.guess_type(target.name)
            item.update(
                {
                    "status": "available",
                    "kind": _artifact_kind(target),
                    "mime_type": mime_type or "application/octet-stream",
                    "size_bytes": stat.st_size,
                    "sha256": _file_sha256(target),
                }
            )
        items.append(item)
    manifest = {
        "type": "collaboration_shared_materials",
        "access": "read_only",
        "root": COLLABORATION_SHARED_DIR,
        "items": items,
    }
    manifest_path = materialized_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "items": items,
        "manifest_path": f"{COLLABORATION_SHARED_DIR}/manifest.json",
    }


def _authorized_artifact_paths(artifacts: list[Any]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for raw in artifacts:
        relative = str(raw.get("path") if isinstance(raw, dict) else raw or "").strip()
        if not relative or relative in seen:
            continue
        seen.add(relative)
        paths.append(relative)
    return paths


def _shared_material_runtime_path(relative: str) -> Path:
    path = PurePosixPath(str(relative).replace("\\", "/"))
    parts = [part for part in path.parts if part not in {"", "."}]
    if path.is_absolute() or not parts or any(part == ".." for part in parts):
        raise ValueError(f"invalid collaboration shared material path: {relative}")
    return Path(COLLABORATION_SHARED_DIR, "materials", *parts)


def _shared_materials_prompt(shared_materials: dict[str, Any]) -> str:
    items = shared_materials.get("items") if isinstance(shared_materials, dict) else []
    if not isinstance(items, list) or not items:
        return ""
    lines = [
        "授权共享材料已物化到当前工作区。",
        f"清单文件：{shared_materials.get('manifest_path') or COLLABORATION_SHARED_DIR + '/manifest.json'}",
        "使用规则：需要材料内容时，用 read 工具读取下列 path；不要假设未列出的共享材料可见。",
    ]
    for item in items:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        source_path = str(item.get("source_path") or "").strip()
        status = str(item.get("status") or "").strip() or "unknown"
        if not path:
            continue
        suffix = "（文件不存在）" if status != "available" else ""
        lines.append(f"- path={path}; source={source_path}; status={status}{suffix}")
    return "\n".join(lines)


def _write_worker_delivery(shared_workspace: Path, *, task: dict[str, Any], content: str) -> dict[str, Any]:
    task_id = str(task.get("task_id") or uuid4().hex)
    assignee = str(task.get("assignee_package_id") or "worker")
    relative = f"deliveries/{task_id}-{assignee}.md"
    path = _safe_shared_path(shared_workspace, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content + "\n", encoding="utf-8")
    return {
        "path": relative,
        "kind": "markdown",
        "created_by": assignee,
        "task_id": task_id,
        "source": "worker_final_answer",
    }


def _copy_worker_artifacts(
    worker_workdir: Path,
    shared_workspace: Path,
    *,
    before_snapshot: dict[str, tuple[int, int]],
    task: dict[str, Any],
) -> list[dict[str, Any]]:
    if not worker_workdir.exists():
        return []
    task_id = str(task.get("task_id") or uuid4().hex)
    assignee = str(task.get("assignee_package_id") or "worker")
    result: list[dict[str, Any]] = []
    for source in sorted(worker_workdir.rglob("*")):
        if not source.is_file() or _is_skipped_worker_artifact(worker_workdir, source):
            continue
        stat = source.stat()
        relative = source.relative_to(worker_workdir).as_posix()
        previous = before_snapshot.get(relative)
        current = (stat.st_size, stat.st_mtime_ns)
        if previous == current:
            continue
        if stat.st_size > _max_collaboration_artifact_bytes():
            continue
        target_relative = f"artifacts/{task_id}-{assignee}/{relative}"
        target = _safe_shared_path(shared_workspace, target_relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        mime_type, _ = mimetypes.guess_type(target.name)
        result.append(
            {
                "path": target_relative,
                "kind": _artifact_kind(target),
                "mime_type": mime_type or "application/octet-stream",
                "size_bytes": stat.st_size,
                "sha256": _file_sha256(target),
                "created_by": assignee,
                "task_id": task_id,
                "source": "worker_workdir",
                "worker_path": relative,
            }
        )
    return result


def _workspace_snapshot(root: Path) -> dict[str, tuple[int, int]]:
    if not root.exists():
        return {}
    snapshot: dict[str, tuple[int, int]] = {}
    for path in root.rglob("*"):
        if not path.is_file() or _is_skipped_worker_artifact(root, path):
            continue
        stat = path.stat()
        snapshot[path.relative_to(root).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def _is_skipped_worker_artifact(root: Path, path: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return True
    return any(part in WORKER_ARTIFACT_SKIP_DIRS or part.startswith(".") for part in parts)


def _artifact_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt", ".json", ".csv", ".py", ".ts", ".tsx", ".js", ".vue", ".html", ".css"}:
        return "text"
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}:
        return "image"
    if suffix in {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx"}:
        return "document"
    return "binary"


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _max_collaboration_artifact_bytes() -> int:
    value = str(os.getenv(MAX_COLLABORATION_ARTIFACT_BYTES_ENV) or "").strip()
    if not value:
        return DEFAULT_MAX_COLLABORATION_ARTIFACT_BYTES
    try:
        return max(1, int(value))
    except ValueError:
        return DEFAULT_MAX_COLLABORATION_ARTIFACT_BYTES


def _delivery_message(content: str, artifact_refs: list[dict[str, Any]]) -> str:
    artifact_lines = [str(item.get("path") or "").strip() for item in artifact_refs if item.get("path")]
    artifacts = "\n".join(f"- {line}" for line in artifact_lines)
    return f"任务已提交：{_short_summary(content)}\n\n交付物：\n{artifacts}"


def _safe_shared_path(root: Path, relative: str) -> Path:
    root = root.resolve()
    target = (root / relative).resolve()
    if root != target and root not in target.parents:
        raise ValueError(f"shared workspace path escapes collaboration workdir: {relative}")
    return target


def _short_summary(content: str) -> str:
    text = " ".join(str(content or "").split())
    return text[:500] if len(text) > 500 else text
