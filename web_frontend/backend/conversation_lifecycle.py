from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
from time import monotonic
from typing import Any, Iterable

from agent_factory.dynamic_runtime.database import DynamicRuntimeDatabase
from agent_factory.dynamic_runtime.dispatcher import CommandExecutionRegistry
from agent_factory.dynamic_runtime.run_control import RuntimeRunControlRegistry
from agent_factory.runtime_kernel.persistence import delete_checkpoint_thread
from web_frontend.backend.attachment_upload_store import AttachmentUploadStore


_TERMINAL_RUNTIME_STATUSES = frozenset({"completed", "failed", "cancelled"})
_TERMINAL_COMMAND_STATUSES = frozenset({"completed", "failed", "cancelled", "rejected"})


@dataclass(frozen=True, slots=True)
class ConversationDeletionResult:
    session_ids: tuple[str, ...]
    released_bytes: int
    deleted_file_count: int
    detached_memory_revision_count: int


@dataclass(frozen=True, slots=True)
class _ConversationDeletionPlan:
    principal_id: str
    session_ids: tuple[str, ...]
    workspace_ids: tuple[str, ...]
    managed_workspace_paths: tuple[Path, ...]
    runtime_instance_ids: tuple[str, ...]
    command_ids: tuple[str, ...]
    delegated_task_ids: tuple[str, ...]
    delegation_grant_ids: tuple[str, ...]
    attachment_ids: tuple[str, ...]


class ConversationLifecycleService:
    """Owns cancellation, durable deletion, and filesystem cleanup for conversations."""

    def __init__(
        self,
        *,
        database: DynamicRuntimeDatabase,
        run_controls: RuntimeRunControlRegistry,
        command_executions: CommandExecutionRegistry,
        checkpointer: Any,
        tool_output_root: Path,
        managed_workspace_root: Path,
        attachment_uploads: AttachmentUploadStore,
        quiesce_timeout_seconds: float,
        quiesce_poll_seconds: float,
    ) -> None:
        if quiesce_timeout_seconds <= 0 or quiesce_poll_seconds <= 0:
            raise ValueError("conversation lifecycle quiesce timings must be positive")
        self._database = database
        self._run_controls = run_controls
        self._command_executions = command_executions
        self._checkpointer = checkpointer
        self._tool_output_root = Path(tool_output_root).expanduser().resolve()
        self._managed_workspace_root = Path(managed_workspace_root).expanduser().resolve()
        self._attachment_uploads = attachment_uploads
        self._quiesce_timeout_seconds = float(quiesce_timeout_seconds)
        self._quiesce_poll_seconds = float(quiesce_poll_seconds)

    async def delete_one(self, *, principal_id: str, session_id: str) -> ConversationDeletionResult:
        return await self.delete_many(principal_id=principal_id, session_ids=(session_id,))

    async def delete_all(self, *, principal_id: str) -> ConversationDeletionResult:
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                "select session_id from conversations where principal_id = ? and status != 'deleted'",
                (_required_text(principal_id, "principal_id"),),
            ).fetchall()
        return await self.delete_many(
            principal_id=principal_id,
            session_ids=tuple(str(row["session_id"]) for row in rows),
        )

    async def delete_many(
        self,
        *,
        principal_id: str,
        session_ids: Iterable[str],
    ) -> ConversationDeletionResult:
        owner = _required_text(principal_id, "principal_id")
        normalized_ids = tuple(dict.fromkeys(_required_text(value, "session_id") for value in session_ids))
        if not normalized_ids:
            return ConversationDeletionResult((), 0, 0, 0)
        plan = self._plan(owner=owner, session_ids=normalized_ids)
        self._request_quiescence(plan)
        await self._await_quiescence(plan)
        self._delete_checkpoints(plan)
        detached_memories = self._delete_database_records(plan)
        released_bytes, deleted_files = self._delete_files(plan)
        return ConversationDeletionResult(
            session_ids=plan.session_ids,
            released_bytes=released_bytes,
            deleted_file_count=deleted_files,
            detached_memory_revision_count=detached_memories,
        )

    def _plan(self, *, owner: str, session_ids: tuple[str, ...]) -> _ConversationDeletionPlan:
        placeholders = _placeholders(session_ids)
        with self._database.connection(query_only=True) as conn:
            conversation_rows = conn.execute(
                f"""
                select session_id, workspace_id from conversations
                where session_id in ({placeholders}) and principal_id = ? and status != 'deleted'
                """,
                (*session_ids, owner),
            ).fetchall()
            found = {str(row["session_id"]) for row in conversation_rows}
            missing = tuple(value for value in session_ids if value not in found)
            if missing:
                raise LookupError("conversation not found: " + ", ".join(missing))
            runtime_rows = conn.execute(
                f"select runtime_instance_id from runtime_instances where session_id in ({placeholders})",
                session_ids,
            ).fetchall()
            command_rows = conn.execute(
                f"select command_id from command_inbox where session_id in ({placeholders})",
                session_ids,
            ).fetchall()
            runtime_instance_ids = tuple(str(row["runtime_instance_id"]) for row in runtime_rows)
            delegated_task_rows = conn.execute(
                f"""
                select task_id, delegation_grant_id from delegated_task_revisions
                where parent_runtime_instance_id in ({_placeholders(runtime_instance_ids)})
                   or child_runtime_instance_id in ({_placeholders(runtime_instance_ids)})
                """,
                (*runtime_instance_ids, *runtime_instance_ids),
            ).fetchall() if runtime_instance_ids else []
            message_rows = conn.execute(
                f"select payload_json from conversation_messages where session_id in ({placeholders})",
                session_ids,
            ).fetchall()
            other_message_rows = conn.execute(
                f"select payload_json from conversation_messages where session_id not in ({placeholders})",
                session_ids,
            ).fetchall()
            workspace_ids = tuple(dict.fromkeys(str(row["workspace_id"]) for row in conversation_rows))
            managed_paths = self._deletable_workspace_paths(
                conn,
                workspace_ids=workspace_ids,
                deleting_session_ids=session_ids,
            )
            candidate_attachment_ids = _attachment_ids(
                str(row["payload_json"]) for row in message_rows
            )
            retained_attachment_ids = set(
                _attachment_ids(str(row["payload_json"]) for row in other_message_rows)
            )
        return _ConversationDeletionPlan(
            principal_id=owner,
            session_ids=session_ids,
            workspace_ids=workspace_ids,
            managed_workspace_paths=managed_paths,
            runtime_instance_ids=runtime_instance_ids,
            command_ids=tuple(str(row["command_id"]) for row in command_rows),
            delegated_task_ids=tuple(dict.fromkeys(str(row["task_id"]) for row in delegated_task_rows)),
            delegation_grant_ids=tuple(
                dict.fromkeys(str(row["delegation_grant_id"]) for row in delegated_task_rows)
            ),
            attachment_ids=tuple(
                attachment_id
                for attachment_id in candidate_attachment_ids
                if attachment_id not in retained_attachment_ids
            ),
        )

    def _deletable_workspace_paths(
        self,
        conn: Any,
        *,
        workspace_ids: tuple[str, ...],
        deleting_session_ids: tuple[str, ...],
    ) -> tuple[Path, ...]:
        if not workspace_ids:
            return ()
        workspace_placeholders = _placeholders(workspace_ids)
        session_placeholders = _placeholders(deleting_session_ids)
        rows = conn.execute(
            f"""
            select workspace.workspace_id, workspace.managed_path
            from workspaces as workspace
            where workspace.workspace_id in ({workspace_placeholders})
              and workspace.kind = 'managed'
              and workspace.mode = 'isolated'
              and workspace.managed_path is not null
              and not exists (
                select 1 from conversations as conversation
                where conversation.workspace_id = workspace.workspace_id
                  and conversation.session_id not in ({session_placeholders})
                  and conversation.status != 'deleted'
              )
              and not exists (
                select 1 from scheduler_jobs as job
                where job.workspace_id = workspace.workspace_id and job.status != 'deleted'
              )
              and not exists (
                select 1 from memory_heads as memory
                where memory.workspace_id = workspace.workspace_id
              )
            """,
            (*workspace_ids, *deleting_session_ids),
        ).fetchall()
        return tuple(Path(str(row["managed_path"])).expanduser().resolve() for row in rows)

    def _request_quiescence(self, plan: _ConversationDeletionPlan) -> None:
        for runtime_instance_id in plan.runtime_instance_ids:
            self._run_controls.request_drain(
                runtime_instance_id=runtime_instance_id,
                reason="conversation_deleted",
            )
        for command_id in plan.command_ids:
            self._command_executions.cancel(command_id, reason="conversation_deleted")

    async def _await_quiescence(self, plan: _ConversationDeletionPlan) -> None:
        deadline = monotonic() + self._quiesce_timeout_seconds
        while True:
            if self._is_quiescent(plan):
                return
            if monotonic() >= deadline:
                raise TimeoutError("conversation runtimes did not stop before deletion timeout")
            await asyncio.sleep(self._quiesce_poll_seconds)

    def _is_quiescent(self, plan: _ConversationDeletionPlan) -> bool:
        with self._database.connection(query_only=True) as conn:
            if plan.runtime_instance_ids:
                rows = conn.execute(
                    f"select status from runtime_instances where runtime_instance_id in ({_placeholders(plan.runtime_instance_ids)})",
                    plan.runtime_instance_ids,
                ).fetchall()
                if any(str(row["status"]) not in _TERMINAL_RUNTIME_STATUSES for row in rows):
                    return False
            if plan.command_ids:
                rows = conn.execute(
                    f"select status from command_inbox where command_id in ({_placeholders(plan.command_ids)})",
                    plan.command_ids,
                ).fetchall()
                if any(str(row["status"]) not in _TERMINAL_COMMAND_STATUSES for row in rows):
                    return False
            outbox_conditions = [
                f"(aggregate_kind = 'conversation' and aggregate_id in ({_placeholders(plan.session_ids)}))"
            ]
            outbox_parameters: list[str] = list(plan.session_ids)
            if plan.runtime_instance_ids:
                outbox_conditions.append(
                    f"(aggregate_kind = 'runtime_instance' and aggregate_id in ({_placeholders(plan.runtime_instance_ids)}))"
                )
                outbox_parameters.extend(plan.runtime_instance_ids)
            if plan.command_ids:
                outbox_conditions.append(
                    f"(aggregate_kind = 'command' and aggregate_id in ({_placeholders(plan.command_ids)}))"
                )
                outbox_parameters.extend(plan.command_ids)
            if plan.delegated_task_ids:
                outbox_conditions.append(
                    f"(aggregate_kind = 'delegated_task' and aggregate_id in ({_placeholders(plan.delegated_task_ids)}))"
                )
                outbox_parameters.extend(plan.delegated_task_ids)
            publishing = conn.execute(
                "select 1 from runtime_outbox where status = 'publishing' and ("
                + " or ".join(outbox_conditions)
                + ") limit 1",
                tuple(outbox_parameters),
            ).fetchone()
            if publishing is not None:
                return False
        return True

    def _delete_database_records(self, plan: _ConversationDeletionPlan) -> int:
        session_placeholders = _placeholders(plan.session_ids)
        runtime_placeholders = _placeholders(plan.runtime_instance_ids) if plan.runtime_instance_ids else "null"
        command_placeholders = _placeholders(plan.command_ids) if plan.command_ids else "null"
        with self._database.transaction() as conn:
            detached_memories = conn.execute(
                f"""
                update memory_revisions
                set source_session_id = null, source_turn_id = null, created_by_runtime_instance_id = null
                where source_session_id in ({session_placeholders})
                """,
                plan.session_ids,
            ).rowcount
            conn.execute(
                f"delete from delegated_task_notifications where session_id in ({session_placeholders})",
                plan.session_ids,
            )
            if plan.runtime_instance_ids:
                conn.execute(
                    f"update delegated_task_notifications set delivered_runtime_instance_id = null where delivered_runtime_instance_id in ({runtime_placeholders})",
                    plan.runtime_instance_ids,
                )
            if plan.delegated_task_ids:
                conn.execute(
                    f"delete from delegated_task_events where task_id in ({_placeholders(plan.delegated_task_ids)})",
                    plan.delegated_task_ids,
                )
                conn.execute(
                    f"delete from delegated_task_revisions where task_id in ({_placeholders(plan.delegated_task_ids)})",
                    plan.delegated_task_ids,
                )
            if plan.delegation_grant_ids:
                conn.execute(
                    f"delete from delegation_grants where grant_id in ({_placeholders(plan.delegation_grant_ids)})",
                    plan.delegation_grant_ids,
                )
            if plan.runtime_instance_ids:
                conn.execute(
                    f"update scheduler_runs set runtime_instance_id = null where runtime_instance_id in ({runtime_placeholders})",
                    plan.runtime_instance_ids,
                )
                for table in ("delivery_commits", "runtime_model_usage", "runtime_events", "tool_calls"):
                    conn.execute(
                        f"delete from {table} where runtime_instance_id in ({runtime_placeholders})",
                        plan.runtime_instance_ids,
                    )
            conn.execute(
                f"delete from conversation_messages where session_id in ({session_placeholders})",
                plan.session_ids,
            )
            if plan.runtime_instance_ids:
                conn.execute(
                    f"delete from runtime_instances where runtime_instance_id in ({runtime_placeholders})",
                    plan.runtime_instance_ids,
                )
            conn.execute(
                f"delete from conversation_turns where session_id in ({session_placeholders})",
                plan.session_ids,
            )
            conn.execute(
                f"delete from command_inbox where session_id in ({session_placeholders})",
                plan.session_ids,
            )
            outbox_conditions = [f"(aggregate_kind = 'conversation' and aggregate_id in ({session_placeholders}))"]
            outbox_parameters: list[str] = list(plan.session_ids)
            if plan.runtime_instance_ids:
                outbox_conditions.append(f"(aggregate_kind = 'runtime_instance' and aggregate_id in ({runtime_placeholders}))")
                outbox_parameters.extend(plan.runtime_instance_ids)
            if plan.command_ids:
                outbox_conditions.append(f"(aggregate_kind = 'command' and aggregate_id in ({command_placeholders}))")
                outbox_parameters.extend(plan.command_ids)
            if plan.delegated_task_ids:
                outbox_conditions.append(f"(aggregate_kind = 'delegated_task' and aggregate_id in ({_placeholders(plan.delegated_task_ids)}))")
                outbox_parameters.extend(plan.delegated_task_ids)
            conn.execute(
                "delete from runtime_outbox where " + " or ".join(outbox_conditions),
                tuple(outbox_parameters),
            )
            conn.execute(
                f"delete from conversations where session_id in ({session_placeholders})",
                plan.session_ids,
            )
            self._delete_unused_isolated_workspaces(conn, plan)
        return int(detached_memories)

    def _delete_unused_isolated_workspaces(self, conn: Any, plan: _ConversationDeletionPlan) -> None:
        if not plan.managed_workspace_paths:
            return
        paths = tuple(str(path) for path in plan.managed_workspace_paths)
        conn.execute(
            f"""
            delete from workspaces
            where managed_path in ({_placeholders(paths)})
              and kind = 'managed' and mode = 'isolated'
              and not exists (select 1 from conversations where conversations.workspace_id = workspaces.workspace_id)
              and not exists (select 1 from scheduler_jobs where scheduler_jobs.workspace_id = workspaces.workspace_id)
              and not exists (select 1 from memory_heads where memory_heads.workspace_id = workspaces.workspace_id)
            """,
            paths,
        )

    def _delete_files(self, plan: _ConversationDeletionPlan) -> tuple[int, int]:
        released_bytes = 0
        deleted_files = 0
        for session_id in plan.session_ids:
            released_bytes_delta, deleted_files_delta = _remove_tree(
                self._tool_output_root / "sessions" / session_id,
                allowed_root=self._tool_output_root,
            )
            released_bytes += released_bytes_delta
            deleted_files += deleted_files_delta
        for workspace_path in plan.managed_workspace_paths:
            released_bytes_delta, deleted_files_delta = _remove_tree(
                workspace_path,
                allowed_root=self._managed_workspace_root,
            )
            released_bytes += released_bytes_delta
            deleted_files += deleted_files_delta
        for attachment_id in plan.attachment_ids:
            released_bytes_delta, deleted_files_delta = self._attachment_uploads.delete(attachment_id)
            released_bytes += released_bytes_delta
            deleted_files += deleted_files_delta
        return released_bytes, deleted_files

    def _delete_checkpoints(self, plan: _ConversationDeletionPlan) -> None:
        for runtime_instance_id in plan.runtime_instance_ids:
            delete_checkpoint_thread(self._checkpointer, runtime_instance_id)


def _attachment_ids(payloads: Iterable[str]) -> tuple[str, ...]:
    found: list[str] = []
    for payload in payloads:
        try:
            value = json.loads(payload)
        except json.JSONDecodeError:
            continue
        _collect_attachment_ids(value, found)
    return tuple(dict.fromkeys(found))


def _collect_attachment_ids(value: Any, found: list[str]) -> None:
    if isinstance(value, dict):
        attachment_id = str(value.get("attachment_id") or "").strip()
        if attachment_id:
            found.append(attachment_id)
        for nested in value.values():
            _collect_attachment_ids(nested, found)
    elif isinstance(value, list):
        for nested in value:
            _collect_attachment_ids(nested, found)


def _remove_tree(path: Path, *, allowed_root: Path) -> tuple[int, int]:
    resolved = path.expanduser().resolve()
    root = allowed_root.expanduser().resolve()
    if resolved == root or not resolved.is_relative_to(root) or not resolved.exists():
        return 0, 0
    file_count = sum(1 for item in resolved.rglob("*") if item.is_file())
    byte_count = sum(item.stat().st_size for item in resolved.rglob("*") if item.is_file())
    shutil.rmtree(resolved)
    return byte_count, file_count


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _placeholders(values: Iterable[Any]) -> str:
    materialized = tuple(values)
    if not materialized:
        raise ValueError("SQL placeholder collection must not be empty")
    return ",".join("?" for _ in materialized)
