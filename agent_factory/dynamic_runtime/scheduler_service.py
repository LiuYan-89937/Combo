from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
import os
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from agent_factory.dynamic_runtime.control_plane_store import WorkspaceSchedulerStore
from agent_factory.dynamic_runtime.repositories import CommandInbox, ConversationStore
from agent_factory.runtime_protocol import (
    CancelRuntimeRequestPayload,
    CommandEnvelope,
    CommandReceipt,
    SendMessagePayload,
    TextPart,
)
from agent_factory.runtime_protocol.versioning import RUNTIME_PROTOCOL_VERSION


class SchedulerService:
    """Own durable scheduler triggers and the two SchedulerRun executors."""

    def __init__(
        self,
        *,
        store: WorkspaceSchedulerStore,
        conversations: ConversationStore,
        commands: CommandInbox,
        notify_commands: Callable[[], None],
    ) -> None:
        self._store = store
        self._conversations = conversations
        self._commands = commands
        self._notify_commands = notify_commands
        self._scheduler = AsyncIOScheduler()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._store.bind_change_listener(self._schedule_synchronize)

    def start(self) -> None:
        self._event_loop = asyncio.get_running_loop()
        self._scheduler.start()
        self.synchronize()
        for run in self._store.active_runs():
            self._store.update_run(
                str(run["run_id"]),
                status="failed",
                patch={"error": {"code": "application_restarted", "message": "Task execution was interrupted by an application restart."}},
            )

    async def stop(self) -> None:
        self._store.bind_change_listener(None)
        self._event_loop = None
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def _schedule_synchronize(self) -> None:
        event_loop = self._event_loop
        if event_loop is None or event_loop.is_closed():
            return
        event_loop.call_soon_threadsafe(self.synchronize)

    def synchronize(self) -> None:
        configured_ids: set[str] = set()
        for job in self._store.enabled_jobs():
            job_id = str(job["job_id"])
            try:
                trigger = _trigger(job)
            except (TypeError, ValueError) as exc:
                self._store.set_schedule_error(job_id, str(exc))
                continue
            self._scheduler.add_job(
                self._scheduled_fire,
                trigger=trigger,
                id=job_id,
                args=(job_id,),
                replace_existing=True,
                coalesce=True,
                max_instances=1,
                misfire_grace_time=300,
            )
            configured_ids.add(job_id)
            self._store.set_schedule_error(job_id, None)
            scheduled = self._scheduler.get_job(job_id)
            self._store.set_fire_times(
                job_id,
                next_fire_at=(scheduled.next_run_time.isoformat() if scheduled and scheduled.next_run_time else None),
            )
        for scheduled in self._scheduler.get_jobs():
            if scheduled.id not in configured_ids:
                self._scheduler.remove_job(scheduled.id)

    def launch(self, job_id: str, *, trigger_source: str, scheduled_fire_at: str | None = None) -> dict[str, Any]:
        job = self._store.require_job(job_id)
        if job["status"] != "enabled":
            raise RuntimeError("scheduler job is paused")
        fire_at = scheduled_fire_at or datetime.now().astimezone().isoformat()
        target = _target(job)
        snapshot = {
            "trigger_source": trigger_source,
            "scheduled_fire_at": fire_at,
            "executor_type": "script" if target["target_type"] == "script_run" else "agent",
            "job_snapshot": job,
        }
        run = self._store.create_run(job_id=job_id, payload=snapshot)
        if bool(run.get("deduplicated")):
            return run
        task = asyncio.create_task(self._execute(run, job), name=f"scheduler-run-{run['run_id']}")
        self._tasks[str(run["run_id"])] = task
        task.add_done_callback(lambda _task, run_id=str(run["run_id"]): self._tasks.pop(run_id, None))
        return run

    async def cancel(self, run_id: str) -> dict[str, Any]:
        run = self._store.require_run(run_id)
        runtime_instance_id = str(run.get("runtime_instance_id") or "").strip()
        request_id = str(run.get("request_id") or "").strip()
        session_id = str(run.get("session_id") or "").strip()
        if runtime_instance_id and request_id and session_id:
            command_id = uuid4().hex
            principal_id = _required(self._store.require_job(str(run["job_id"])), "principal_id")
            envelope = CommandEnvelope(
                protocol_version=RUNTIME_PROTOCOL_VERSION,
                command_id=command_id,
                client_instance_id="scheduler-service",
                principal_id=principal_id,
                session_id=session_id,
                payload=CancelRuntimeRequestPayload(
                    runtime_instance_id=runtime_instance_id,
                    request_id=request_id,
                    reason="scheduled task cancelled by user",
                ),
            )
            self._commands.accept(
                envelope,
                CommandReceipt(
                    command_id=command_id,
                    client_instance_id=envelope.client_instance_id,
                    principal_id=principal_id,
                    session_id=session_id,
                    status="received",
                ),
            )
            self._notify_commands()
        task = self._tasks.get(run_id)
        if task is not None:
            task.cancel()
        return self._store.update_run(run_id, status="cancelled")

    async def _scheduled_fire(self, job_id: str) -> None:
        fire_at = datetime.now().astimezone().isoformat()
        self.launch(job_id, trigger_source="scheduled", scheduled_fire_at=fire_at)
        scheduled = self._scheduler.get_job(job_id)
        self._store.set_fire_times(
            job_id,
            next_fire_at=(scheduled.next_run_time.isoformat() if scheduled and scheduled.next_run_time else None),
            last_fire_at=fire_at,
        )

    async def _execute(self, run: dict[str, Any], job: dict[str, Any]) -> None:
        run_id = str(run["run_id"])
        try:
            self._store.update_run(run_id, status="running")
            self._store.append_run_event(run_id, "run_started", {"executor_type": run["executor_type"]})
            if run["executor_type"] == "script":
                result = await self._execute_script(run_id, job)
            else:
                result = await self._execute_agent(run_id, job)
            self._store.append_run_event(run_id, "result", result)
            self._store.update_run(run_id, status="completed", patch={"result": result, "result_summary": _summary(result)})
        except asyncio.CancelledError:
            self._store.append_run_event(run_id, "cancelled", {"reason": "user_cancelled"})
            self._store.update_run(run_id, status="cancelled")
            raise
        except Exception as exc:
            error = {"code": type(exc).__name__, "message": str(exc)}
            self._store.append_run_event(run_id, "failed", error)
            self._store.update_run(run_id, status="failed", patch={"error": error})

    async def _execute_agent(self, run_id: str, job: dict[str, Any]) -> dict[str, Any]:
        principal_id = _required(job, "principal_id")
        workspace_id = _required(job, "workspace_id")
        session_id = uuid5(NAMESPACE_URL, f"combo:scheduler-job:{job['job_id']}").hex
        try:
            conversation = self._conversations.require_identity(session_id)
            if conversation.principal_id != principal_id or conversation.workspace_id != workspace_id:
                raise RuntimeError("scheduler execution session identity does not match its job")
        except LookupError:
            self._conversations.create_conversation(
                session_id=session_id,
                principal_id=principal_id,
                workspace_id=workspace_id,
                title=str(job.get("display_name") or "定时任务"),
                source="scheduler",
            )
        command_id = f"scheduler-{run_id}"
        envelope = CommandEnvelope(
            protocol_version=RUNTIME_PROTOCOL_VERSION,
            command_id=command_id,
            client_instance_id="scheduler-service",
            principal_id=principal_id,
            session_id=session_id,
            payload=SendMessagePayload(
                message_id=uuid4().hex,
                content=_required(job, "task_content"),
                execution_preference=str(job.get("strategy") or "react"),
                approval_mode=str(job.get("approval_policy") or "ask"),
                visibility="internal",
                scheduler_run_id=run_id,
            ),
        )
        receipt = self._commands.accept(
            envelope,
            CommandReceipt(
                command_id=command_id,
                client_instance_id=envelope.client_instance_id,
                principal_id=principal_id,
                session_id=session_id,
                status="received",
            ),
        )
        self._store.update_run(run_id, status="running", patch={"command_id": command_id, "session_id": session_id})
        self._store.append_run_event(run_id, "agent_queued", {"command_id": command_id})
        self._notify_commands()
        while receipt.status not in {"completed", "failed", "cancelled", "rejected"}:
            await asyncio.sleep(0.25)
            receipt = self._commands.get_receipt(command_id)
            if receipt.runtime_instance_id:
                current = self._store.require_run(run_id)
                if (
                    current.get("runtime_instance_id") != receipt.runtime_instance_id
                    or current.get("request_id") != receipt.request_id
                ):
                    current_status = str(current.get("status") or "running")
                    self._store.update_run(
                        run_id,
                        status=current_status if current_status in {"waiting_approval", "waiting_external"} else "running",
                        patch={"request_id": receipt.request_id} if receipt.request_id else None,
                        runtime_instance_id=receipt.runtime_instance_id,
                    )
        if receipt.status != "completed":
            raise RuntimeError(receipt.rejection_code or (receipt.error.user_message_key if receipt.error else receipt.status))
        result_text = _agent_result_text(
            self._conversations.messages(session_id),
            request_id=str(receipt.request_id or ""),
        )
        return {
            "status": "completed",
            "runtime_instance_id": receipt.runtime_instance_id,
            "session_id": session_id,
            "content": result_text,
        }

    async def _execute_script(self, run_id: str, job: dict[str, Any]) -> dict[str, Any]:
        target = _target(job)
        payload = dict(target.get("payload") or {})
        interpreter = str(payload.get("interpreter") or "shell")
        script = str(payload.get("script") or payload.get("command") or "").strip()
        if not script:
            raise ValueError("script task requires script content")
        cwd = self._conversations.require_workspace_root(
            _required(job, "workspace_id"),
            _required(job, "principal_id"),
        )
        command = ["/bin/sh", "-lc", script] if interpreter == "shell" else ["python3", "-c", script]
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(Path(cwd).resolve()),
            env=dict(os.environ),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._store.append_run_event(run_id, "process_started", {"pid": process.pid, "interpreter": interpreter})
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        try:
            await asyncio.gather(
                self._stream_process_output(run_id, "stdout", process.stdout, stdout_chunks),
                self._stream_process_output(run_id, "stderr", process.stderr, stderr_chunks),
            )
            await process.wait()
        except asyncio.CancelledError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
            raise
        output = "".join(stdout_chunks)
        error_output = "".join(stderr_chunks)
        if process.returncode != 0:
            raise RuntimeError(f"script exited with status {process.returncode}: {error_output[-1000:]}")
        return {"status": "completed", "exit_code": process.returncode, "stdout": output, "stderr": error_output}

    async def _stream_process_output(
        self,
        run_id: str,
        stream_name: str,
        stream: asyncio.StreamReader | None,
        collected: list[str],
    ) -> None:
        if stream is None:
            return
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                return
            text = chunk.decode("utf-8", errors="replace")
            collected.append(text)
            self._store.append_run_event(run_id, "process_output", {"stream": stream_name, "text": text})


def _target(job: dict[str, Any]) -> dict[str, Any]:
    value = job.get("target")
    if isinstance(value, dict):
        return value
    return {"target_type": "graph_run", "payload": {"message": job.get("task_content")}}


def _agent_result_text(messages: list[Any], *, request_id: str) -> str:
    for message in reversed(messages):
        if message.role != "assistant" or message.status != "committed":
            continue
        if request_id and message.source_request_id != request_id:
            continue
        text = "\n".join(part.text for part in message.parts if isinstance(part, TextPart)).strip()
        if text:
            return text
    return ""


def _trigger(job: dict[str, Any]):
    schedule_type = str(job.get("schedule_type") or "cron")
    expression = _required(job, "schedule_expr")
    timezone = str(job.get("timezone") or "UTC")
    if schedule_type == "cron":
        return CronTrigger.from_crontab(expression, timezone=timezone)
    if schedule_type == "date":
        return DateTrigger(run_date=datetime.fromisoformat(expression), timezone=timezone)
    if schedule_type == "interval":
        return IntervalTrigger(seconds=float(expression), timezone=timezone)
    raise ValueError(f"unsupported schedule type: {schedule_type}")


def _required(value: dict[str, Any], key: str) -> str:
    text = str(value.get(key) or "").strip()
    if not text:
        raise ValueError(f"{key} must not be empty")
    return text


def _summary(result: dict[str, Any]) -> str:
    value = result.get("content") or result.get("stdout") or result.get("summary") or result.get("status") or "completed"
    return str(value).strip()[:500]
