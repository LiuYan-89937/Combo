from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from hashlib import sha256
import mimetypes
import os
from pathlib import Path, PurePosixPath
import shutil
from typing import Any
from uuid import uuid4

from agent_factory.collaboration_system.event_projection import CollaborationWorkerEventRecorder
from agent_factory.collaboration_system.delivery import WorkerDeliveryValidation, validate_worker_delivery
from agent_factory.collaboration_system.prompting import build_main_agent_collaboration_prompt
from agent_factory.collaboration_runtime_policy import collaboration_runtime_tool_access
from agent_factory.collaboration_system.store import CollaborationStore
from agent_factory.collaboration_system.store import SYSTEM_CHAT_PACKAGE_ID
from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentPackageRuntimeManager
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent
from agent_factory.file_utils import file_sha256
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_support import VisibleAssistantOutputAccumulator
from agent_factory.factory_graph.frontend_bridge.runtime_events import (
    INTERRUPT_TERMINAL_EVENT_TYPES,
    RUN_TERMINAL_EVENT_TYPES,
    runtime_stream_status,
)
from agent_factory.factory_graph.session import FactorySessionManager


SHARE_FILES_DIR = "share_files"
WORKER_ARTIFACT_SKIP_DIRS = {"input_files", SHARE_FILES_DIR, ".cache", "__pycache__"}
DEFAULT_MAX_COLLABORATION_ARTIFACT_BYTES = 200 * 1024 * 1024
MAX_COLLABORATION_ARTIFACT_BYTES_ENV = "AGENTFACTORY_COLLABORATION_MAX_ARTIFACT_BYTES"
MAX_DELEGATED_APPROVALS_PER_TASK = 20
ACTIVE_MAIN_AGENT_TURN_STATUSES = frozenset({"running", "interrupted"})
SUCCESSFUL_MAIN_AGENT_CONTINUATION_STATUSES = frozenset({"completed", "waiting_for_workers"})


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


@dataclass(frozen=True, slots=True)
class MainAgentContinuationResult:
    succeeded: bool
    status: str
    message: str
    session_id: str | None


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
            return [
                self._start_task_and_release_worker_lease(collaboration_id, str(task["task_id"]))
                for task in tasks
            ]
        results: list[CollaborationRunTaskResult] = []
        with ThreadPoolExecutor(max_workers=len(tasks), thread_name_prefix="collab-worker") as executor:
            futures = {
                executor.submit(
                    self._start_task_and_release_worker_lease,
                    collaboration_id,
                    str(task["task_id"]),
                ): task
                for task in tasks
            }
            for future in as_completed(futures):
                results.append(future.result())
        return results

    def _start_task_and_release_worker_lease(
        self,
        collaboration_id: str,
        task_id: str,
    ) -> CollaborationRunTaskResult:
        try:
            return self.start_task(collaboration_id, task_id)
        finally:
            self.store.release_worker_lease_unless_blocked(collaboration_id, task_id)

    def continue_main_agent(
        self,
        collaboration_id: str,
        *,
        user_message: str,
        message_metadata: dict[str, Any] | None = None,
        event_ref: str | None = None,
    ) -> MainAgentContinuationResult:
        session = self.store.get_session(collaboration_id)
        if str(session.get("status") or "") in {"completed", "failed", "cancelled"}:
            return MainAgentContinuationResult(
                succeeded=True,
                status="ignored",
                message="collaboration session is already terminal",
                session_id=str(session.get("main_agent_package_session_id") or "").strip() or None,
            )
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
            message_metadata=message_metadata,
            session_id=package_session_id,
            request_id=request_id,
            user_config={
                "collaboration_id": collaboration_id,
                "runtime_tool_access": collaboration_runtime_tool_access(),
            },
            require_ready=True,
            session_kind="collaboration_main",
            collaboration_id=collaboration_id,
            visible_in_agent_session_list=True,
        )
        main_session_id = str((run.session or {}).get("session_id") or "").strip()
        if main_session_id and main_session_id != str(session.get("main_agent_package_session_id") or ""):
            self.store.update_session(collaboration_id, {"main_agent_package_session_id": main_session_id})
        if main_session_id and package_id == SYSTEM_CHAT_PACKAGE_ID and factory_session_id:
            initial_factory_record = _sync_factory_chat_session_from_agent_session(
                factory_session_id=factory_session_id,
                request_id=request_id,
                user_input=user_message,
                agent_session=run.session or {},
            )
            self.runtime.emit_factory_session_updated(session_record=initial_factory_record, mode="chat")

        output = VisibleAssistantOutputAccumulator()
        tool_activities: list[dict[str, Any]] = []
        status = "failed"
        message = ""
        for stream_mode, chunk in run.events:
            if stream_mode != "frontend_event":
                continue
            item = chunk if isinstance(chunk, FactoryFrontendEvent) else FactoryFrontendEvent.model_validate(chunk)
            self.runtime.emit_frontend_event(
                _main_agent_frontend_event(
                    item,
                    package_id=package_id,
                    factory_session_id=factory_session_id,
                )
            )
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
            )
            if package_id == SYSTEM_CHAT_PACKAGE_ID and factory_session_id:
                factory_record = _sync_factory_chat_session_from_agent_session(
                    factory_session_id=factory_session_id,
                    request_id=request_id,
                    user_input=user_message,
                    agent_session=self.runtime.load_session(package_id, main_session_id),
                )
                self.runtime.emit_factory_session_updated(session_record=factory_record, mode="chat")
        if status in SUCCESSFUL_MAIN_AGENT_CONTINUATION_STATUSES:
            summary = (
                "主 Agent 已进入子任务等待状态。"
                if status == "waiting_for_workers"
                else _short_summary(output.content or "主 Agent 已处理协作事件。")
            )
            self.store.record_message(
                collaboration_id,
                speaker_type="main_agent",
                speaker_package_id=package_id,
                message_kind="progress",
                content=summary,
                task_id=None,
            )
            return MainAgentContinuationResult(
                succeeded=True,
                status=status,
                message=summary,
                session_id=main_session_id or None,
            )
        failure_message = message or status
        self.store.record_message(
            collaboration_id,
            speaker_type="system",
            speaker_package_id=package_id,
            message_kind="progress",
            content=f"主 Agent 处理协作事件失败：{failure_message}",
            task_id=None,
        )
        return MainAgentContinuationResult(
            succeeded=False,
            status=status,
            message=failure_message,
            session_id=main_session_id or None,
        )

    def main_agent_busy_reason(self, collaboration_id: str) -> str | None:
        session = self.store.get_session(collaboration_id)
        package_id = str(session.get("main_agent_package_id") or SYSTEM_CHAT_PACKAGE_ID).strip() or SYSTEM_CHAT_PACKAGE_ID
        factory_session_id = str(session.get("main_factory_session_id") or "").strip()
        if package_id == SYSTEM_CHAT_PACKAGE_ID and factory_session_id:
            try:
                factory_record = FactorySessionManager.from_env().load(factory_session_id)
            except Exception:
                factory_record = None
            if factory_record is not None:
                factory_status = _latest_turn_status(factory_record.chat_turns)
                if factory_status in ACTIVE_MAIN_AGENT_TURN_STATUSES:
                    return f"factory chat turn is {factory_status}"
        package_session_id = self._main_agent_package_session_id(session, package_id=package_id)
        if not package_session_id:
            return None
        try:
            package_session = self.runtime.load_session(package_id, package_session_id)
        except Exception:
            return None
        package_status = _latest_turn_status(package_session.get("turns") or [])
        if package_status in ACTIVE_MAIN_AGENT_TURN_STATUSES:
            return f"agent package turn is {package_status}"
        return None

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
        if not self.store.acquire_worker_lease(collaboration_id, task_id):
            summary = f"子 Agent {package_id} 正在执行其他任务，本任务保持排队。"
            self.store.update_task(
                collaboration_id,
                task_id,
                {
                    "status": "queued",
                    "result_summary": summary,
                    "result_payload": {"runtime_status": "waiting_for_package_worker"},
                },
            )
            return CollaborationRunTaskResult(
                collaboration_id=collaboration_id,
                task_id=task_id,
                status="queued",
                assignee_session_id=task.get("assignee_session_id"),
                result_summary=summary,
                artifact_refs=list(task.get("artifact_refs") or []),
            )
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
        worker_workdir = self.runtime.workdir_for_session(package_id, assignee_session_id)
        shared_materials = _materialize_authorized_artifacts(
            shared_workspace=self.store.session_workdir(collaboration_id),
            worker_workdir=worker_workdir,
            artifacts=task.get("input_artifacts") or [],
        )
        shared_materials_snapshot = _share_files_snapshot(worker_workdir)
        missing_materials = _missing_shared_materials(shared_materials)
        if missing_materials:
            summary = "授权共享材料缺失，任务未启动：" + "、".join(missing_materials)
            self.store.update_task(
                collaboration_id,
                task_id,
                {
                    "status": "failed",
                    "result_summary": summary,
                    "result_payload": {
                        "runtime_status": "missing_input_artifacts",
                        "missing_input_artifacts": missing_materials,
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
            return CollaborationRunTaskResult(
                collaboration_id=collaboration_id,
                task_id=task_id,
                status="failed",
                assignee_session_id=assignee_session_id,
                result_summary=summary,
                artifact_refs=[],
            )
        prompt = _worker_prompt(
            session=session,
            task=task,
            shared_materials=shared_materials,
        )
        before_snapshot = _workspace_snapshot(worker_workdir)
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
            workdir_root=worker_workdir,
        )
        assignee_session_id = str((run.session or {}).get("session_id") or assignee_session_id).strip()
        if not assignee_session_id:
            raise RuntimeError("collaboration worker run did not provide an agent session id")
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
        result = self._finalize_worker_outcome(
            outcome=outcome,
            collaboration_id=collaboration_id,
            task_id=task_id,
            task=task,
            package_id=package_id,
            assignee_session_id=assignee_session_id,
            output=output,
            worker_workdir=worker_workdir,
            before_snapshot=before_snapshot,
            shared_materials_snapshot=shared_materials_snapshot,
        )
        self._finish_worker_session_turn(
            package_id=package_id,
            session_id=outcome.assignee_session_id or assignee_session_id,
            request_id=run_request_id,
            output=output,
            status=_worker_session_status(result.status, outcome.status),
            tool_activities=outcome.tool_activities,
        )
        return result

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
        if not self.store.acquire_worker_lease(collaboration_id, task_id):
            summary = f"子 Agent {package_id} 正在执行其他任务，当前审批恢复需等待该任务结束。"
            return CollaborationRunTaskResult(
                collaboration_id=collaboration_id,
                task_id=task_id,
                status="blocked",
                assignee_session_id=assignee_session_id,
                result_summary=summary,
                artifact_refs=list(task.get("artifact_refs") or []),
            )
        worker_workdir = self.runtime.workdir_for_session(package_id, assignee_session_id)
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
            workdir_root=worker_workdir,
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
        result = self._finalize_worker_outcome(
            outcome=outcome,
            collaboration_id=collaboration_id,
            task_id=task_id,
            task=task,
            package_id=package_id,
            assignee_session_id=assignee_session_id,
            output=output,
            worker_workdir=worker_workdir,
            before_snapshot=before_snapshot,
            shared_materials_snapshot=None,
        )
        self._finish_worker_session_turn(
            package_id=package_id,
            session_id=outcome.assignee_session_id or assignee_session_id,
            request_id=resume_request_id,
            output=output,
            status=_worker_session_status(result.status, outcome.status),
            tool_activities=outcome.tool_activities,
        )
        return result

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
        shared_materials_snapshot: dict[str, tuple[int, int]] | None,
        delivery_validation: WorkerDeliveryValidation,
    ) -> CollaborationRunTaskResult:
        task_id = str(task.get("task_id") or "")
        content = str(output.content or "").strip()
        if not content:
            content = "Worker completed but did not return visible content."
        shared_material_changes = (
            _share_files_changes(worker_workdir, shared_materials_snapshot)
            if shared_materials_snapshot is not None
            else []
        )
        if shared_material_changes:
            summary = "worker 写入或修改了只读共享材料目录 share_files/，交付被拒绝：" + "、".join(shared_material_changes)
            self.store.update_task(
                collaboration_id,
                task_id,
                {
                    "status": "failed",
                    "assignee_session_id": assignee_session_id,
                    "result_summary": summary,
                    "result_payload": {
                        "runtime_status": "share_files_mutated",
                        "content": content,
                        "mutated_paths": shared_material_changes,
                    },
                    "artifact_refs": [],
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
            return CollaborationRunTaskResult(
                collaboration_id=collaboration_id,
                task_id=task_id,
                status="failed",
                assignee_session_id=assignee_session_id,
                result_summary=summary,
                artifact_refs=[],
            )
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
                "result_payload": {
                    "content": content,
                    "reasoning_content": output.reasoning_content or "",
                    "delivery_validation": delivery_validation.model_dump(mode="json"),
                },
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

    def _finalize_worker_outcome(
        self,
        *,
        outcome: WorkerRunOutcome,
        collaboration_id: str,
        task_id: str,
        task: dict[str, Any],
        package_id: str,
        assignee_session_id: str,
        output: VisibleAssistantOutputAccumulator,
        worker_workdir: Path,
        before_snapshot: dict[str, tuple[int, int]],
        shared_materials_snapshot: dict[str, tuple[int, int]] | None = None,
    ) -> CollaborationRunTaskResult:
        """统一处理 worker 运行结果的收尾逻辑：检查取消、处理非完成状态、提交结果"""
        # 检查任务是否已被取消
        cancelled_result = self._cancelled_worker_result(
            collaboration_id=collaboration_id,
            task_id=task_id,
            package_id=package_id,
            assignee_session_id=outcome.assignee_session_id or assignee_session_id,
        )
        if cancelled_result is not None:
            return cancelled_result

        delivery_validation: WorkerDeliveryValidation | None = None
        if outcome.status == "completed":
            delivery_validation = validate_worker_delivery(
                task.get("delivery_standard"),
                visible_result=output.content,
                worker_workdir=worker_workdir,
                before_snapshot=before_snapshot,
            )
            if not delivery_validation.passed:
                summary = "worker runtime completed without satisfying the delivery contract: " + "; ".join(
                    delivery_validation.errors
                )
                self.store.update_task(
                    collaboration_id,
                    task_id,
                    {
                        "status": "failed",
                        "assignee_session_id": outcome.assignee_session_id or assignee_session_id,
                        "result_summary": summary,
                        "result_payload": {
                            "runtime_status": outcome.status,
                            "delivery_validation": delivery_validation.model_dump(mode="json"),
                        },
                        "artifact_refs": [],
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
                return CollaborationRunTaskResult(
                    collaboration_id=collaboration_id,
                    task_id=task_id,
                    status="failed",
                    assignee_session_id=outcome.assignee_session_id or assignee_session_id,
                    result_summary=summary,
                    artifact_refs=[],
                )

        # 处理非完成状态（blocked 或 failed）
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

        # 正常完成，提交结果
        if delivery_validation is None:
            raise RuntimeError("completed worker outcome is missing delivery validation")
        return self._submit_worker_result(
            collaboration_id=collaboration_id,
            task=task,
            package_id=package_id,
            assignee_session_id=outcome.assignee_session_id or assignee_session_id,
            output=output,
            worker_workdir=worker_workdir,
            before_snapshot=before_snapshot,
            shared_materials_snapshot=shared_materials_snapshot,
            delivery_validation=delivery_validation,
        )

    def _cancelled_worker_result(
        self,
        *,
        collaboration_id: str,
        task_id: str,
        package_id: str,
        assignee_session_id: str | None,
    ) -> CollaborationRunTaskResult | None:
        current_task = _task_by_id(self.store.get_session(collaboration_id), task_id)
        if str(current_task.get("status") or "") != "cancelled":
            return None
        summary = "worker 已结束，但任务已被取消；迟到结果已丢弃。"
        self.store.record_message(
            collaboration_id,
            speaker_type="system",
            speaker_package_id=package_id,
            message_kind="progress",
            content=summary,
            task_id=task_id,
        )
        return CollaborationRunTaskResult(
            collaboration_id=collaboration_id,
            task_id=task_id,
            status="cancelled",
            assignee_session_id=assignee_session_id,
            result_summary=summary,
            artifact_refs=list(current_task.get("artifact_refs") or []),
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
                if item.process_event:
                    self.runtime.emit_frontend_event(
                        _worker_agent_frontend_event(item, package_id=package_id, session_id=assignee_session_id)
                    )
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
        )


def _task_by_id(session: dict[str, Any], task_id: str) -> dict[str, Any]:
    for task in session.get("tasks") or []:
        if str(task.get("task_id") or "") == task_id:
            return task
    raise ValueError(f"collaboration task not found: {task_id}")


def _latest_turn_status(turns: Any) -> str:
    if not isinstance(turns, (list, tuple)) or not turns:
        return ""
    latest = turns[-1]
    if isinstance(latest, dict):
        return str(latest.get("status") or "").strip()
    return str(getattr(latest, "status", "") or "").strip()


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


def _worker_session_status(task_status: str, runtime_status: str) -> str:
    return runtime_status if task_status == "submitted" else task_status


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


def _main_agent_frontend_event(
    item: FactoryFrontendEvent,
    *,
    package_id: str,
    factory_session_id: str | None,
) -> FactoryFrontendEvent:
    payload = item.payload if isinstance(item.payload, dict) else {}
    updates: dict[str, Any] = {
        "payload": {
            **payload,
            "package_id": package_id,
        }
    }
    if package_id == SYSTEM_CHAT_PACKAGE_ID:
        updates["mode"] = "chat"
        if factory_session_id:
            updates["session_id"] = factory_session_id
    return item.model_copy(update=updates)


def _worker_agent_frontend_event(
    item: FactoryFrontendEvent,
    *,
    package_id: str,
    session_id: str | None,
) -> FactoryFrontendEvent:
    payload = item.payload if isinstance(item.payload, dict) else {}
    return item.model_copy(
        update={
            "session_id": item.session_id or session_id,
            "payload": {
                **payload,
                "package_id": package_id,
            },
        }
    )


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
    for payload in _tool_activity_payloads(item):
        _upsert_projected_tool_activity(activities, item=item, payload=payload, status=status)


def _tool_activity_payloads(item: FactoryFrontendEvent) -> list[dict[str, Any]]:
    payload = item.payload if isinstance(item.payload, dict) else {}
    if item.event_type == "tool_approval_requested":
        requests = payload.get("requests") if isinstance(payload.get("requests"), list) else []
        common = {key: value for key, value in payload.items() if key != "requests"}
        return [
            {**common, **request}
            for request in requests
            if isinstance(request, dict)
        ]
    if item.event_type == "tool_approval_resolved":
        call_ids = _approval_tool_call_ids(payload)
        return [{**payload, "tool_call_id": call_id} for call_id in call_ids]
    return [payload]


def _approval_tool_call_ids(payload: dict[str, Any]) -> list[str]:
    requests = payload.get("requests") if isinstance(payload.get("requests"), list) else []
    candidates = [
        payload.get("tool_call_id"),
        payload.get("toolCallId"),
        *(payload.get("tool_call_ids") if isinstance(payload.get("tool_call_ids"), list) else []),
        *(payload.get("toolCallIds") if isinstance(payload.get("toolCallIds"), list) else []),
        *(
            request.get("tool_call_id") or request.get("toolCallId")
            for request in requests
            if isinstance(request, dict)
        ),
    ]
    return list(dict.fromkeys(str(value or "").strip() for value in candidates if str(value or "").strip()))


def _upsert_projected_tool_activity(
    activities: list[dict[str, Any]],
    *,
    item: FactoryFrontendEvent,
    payload: dict[str, Any],
    status: str,
) -> None:
    tool_call_id = _first_payload_text(payload, "tool_call_id", "toolCallId")
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
    tool_name = _first_payload_text(payload, "tool_name", "tool_id", "name") or existing.get("toolName") or "tool_call"
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
        "toolName": tool_name,
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
            f"{SHARE_FILES_DIR}/ 是只读上游材料目录，只能读取，不能创建、修改、删除其中的任何文件。",
            "你的交付物必须写入当前工作区的普通路径，例如 result.md、logo.png、reports/summary.md；不要写入 share_files/。宿主会自动收集这些普通工作区文件作为任务交付物。",
            "visible_context 是纯文本提示，不代表文件已存在；只有下面共享材料列表里的路径才是已授权文件。",
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
        return {"items": []}
    materialized_root = worker_workdir / SHARE_FILES_DIR
    if materialized_root.exists():
        shutil.rmtree(materialized_root)
    materialized_root.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for relative in requested_paths:
        source = _safe_shared_path(shared_workspace, relative)
        target_relative = _share_file_runtime_path(relative)
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
    return {"items": items}


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


def _share_file_runtime_path(relative: str) -> Path:
    path = PurePosixPath(str(relative).replace("\\", "/"))
    parts = [part for part in path.parts if part not in {"", "."}]
    if path.is_absolute() or not parts or any(part == ".." for part in parts):
        raise ValueError(f"invalid collaboration shared material path: {relative}")
    return Path(SHARE_FILES_DIR, *parts)


def _shared_materials_prompt(shared_materials: dict[str, Any]) -> str:
    items = shared_materials.get("items") if isinstance(shared_materials, dict) else []
    if not isinstance(items, list) or not items:
        return ""
    lines = [
        f"共享材料已复制到当前工作区的 `{SHARE_FILES_DIR}/` 文件夹。",
        f"`{SHARE_FILES_DIR}/` 是只读上游材料目录；需要前置产物时直接用 read 工具读取下列路径。",
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
        lines.append(f"- path={path}; source={source_path}; role=上游协作材料; status={status}{suffix}")
    return "\n".join(lines)


def _missing_shared_materials(shared_materials: dict[str, Any]) -> list[str]:
    items = shared_materials.get("items") if isinstance(shared_materials, dict) else []
    if not isinstance(items, list):
        return []
    return [
        str(item.get("source_path") or item.get("path") or "").strip()
        for item in items
        if isinstance(item, dict) and str(item.get("status") or "") == "missing"
    ]


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
        target_relative = _next_available_artifact_relative(
            shared_workspace,
            Path("artifacts", assignee, *PurePosixPath(relative).parts).as_posix(),
        )
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


def _next_available_artifact_relative(shared_workspace: Path, relative: str) -> str:
    target = _safe_shared_path(shared_workspace, relative)
    if not target.exists():
        return relative
    path = PurePosixPath(relative)
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 2
    while True:
        candidate = (parent / f"{stem}__{index}{suffix}").as_posix()
        if not _safe_shared_path(shared_workspace, candidate).exists():
            return candidate
        index += 1


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


def _share_files_snapshot(worker_workdir: Path) -> dict[str, tuple[int, int]]:
    root = worker_workdir / SHARE_FILES_DIR
    if not root.exists():
        return {}
    snapshot: dict[str, tuple[int, int]] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        stat = path.stat()
        snapshot[path.relative_to(worker_workdir).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


def _share_files_changes(worker_workdir: Path, before: dict[str, tuple[int, int]]) -> list[str]:
    after = _share_files_snapshot(worker_workdir)
    changed: list[str] = []
    for path, current in sorted(after.items()):
        previous = before.get(path)
        if previous != current:
            changed.append(path)
    for path in sorted(set(before) - set(after)):
        changed.append(path)
    return changed


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


# 为保持向后兼容，保留 _file_sha256 作为别名
_file_sha256 = file_sha256


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
