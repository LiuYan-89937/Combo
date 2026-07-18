from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from agent_factory.collaboration_system.delivery import normalize_delivery_standard
from agent_factory.paths import factory_artifact_path, resolve_project_path
from agent_factory.sqlite_runtime import connect_sqlite, initialize_sqlite_store


SYSTEM_CHAT_PACKAGE_ID = "factory_chat"
DEFAULT_APPROVAL_MODE = "main_agent_delegated"
APPROVAL_MODES = {"user_controlled", "main_agent_delegated"}
SESSION_STATUSES = {"draft", "running", "completed", "failed", "cancelled"}
TERMINAL_SESSION_STATUSES = {"completed", "failed", "cancelled"}
MANUFACTURING_REQUEST_STATUSES = {"requested", "running", "ready_for_publish", "completed", "failed", "blocked"}
MANUFACTURING_REQUEST_ACTIVE_STATUSES = {"requested", "running"}
MAIN_AGENT_EVENT_STATUSES = {"pending", "processing", "completed", "failed"}
TASK_STATUSES = {
    "assigned",
    "queued",
    "accepted",
    "planning",
    "working",
    "blocked",
    "submitted",
    "revision_requested",
    "completed",
    "failed",
    "cancelled",
}
TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled"}
TASK_EXECUTION_STARTED_STATUSES = {"accepted", "planning", "working", "blocked", "submitted", "completed"}
TASK_EXECUTION_FINISHED_STATUSES = {"submitted", "completed", "failed", "cancelled"}
READY_TO_START_STATUSES = {"assigned", "queued"}
READY_TO_START_STATUS_PLACEHOLDERS = ", ".join("?" for _ in READY_TO_START_STATUSES)
RETRYABLE_TASK_STATUSES = {"failed", "revision_requested", "cancelled"}
DEPENDENCY_SATISFIED_TASK_STATUSES = {"completed"}
RECOVERABLE_RUNNING_TASK_STATUSES = {"accepted", "planning", "working"}
ACTIVE_WORKER_TASK_STATUSES = {"accepted", "planning", "working"}
WORKER_LEASE_HOLDING_TASK_STATUSES = {*ACTIVE_WORKER_TASK_STATUSES, "blocked"}
SQLITE_BUSY_TIMEOUT_MS = 10000
TASK_RETRY_CLEANUP_BASE_DELAY_SECONDS = 5
TASK_RETRY_CLEANUP_MAX_DELAY_SECONDS = 300


class CollaborationStoreError(RuntimeError):
    pass


class CollaborationStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = resolve_collaboration_store_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        initialize_sqlite_store(
            self.path,
            self._ensure_schema,
            timeout_ms=SQLITE_BUSY_TIMEOUT_MS,
            wal=True,
        )

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from collaboration_sessions
                order by updated_at desc, created_at desc
                """
            ).fetchall()
            sessions = [self._session_view(row) for row in rows]
            for session in sessions:
                self._attach_runtime_status(conn, session)
        return sessions

    def list_auto_dispatch_sessions(self) -> list[dict[str, Any]]:
        sessions = [
            session
            for session in self.list_sessions()
            if session.get("approval_mode") == "main_agent_delegated"
            and session.get("status") not in {"completed", "failed", "cancelled"}
        ]
        return [
            session for session in sessions
            if self.ready_tasks(str(session.get("collaboration_id") or ""))
            or self.list_active_manufacturing_requests(str(session.get("collaboration_id") or ""))
            or self.pending_main_agent_event_count(str(session.get("collaboration_id") or "")) > 0
            or self.list_pending_task_approval_decisions(str(session.get("collaboration_id") or ""))
        ]

    def reopen_session(self, collaboration_id: str) -> dict[str, Any]:
        now = utc_now_text()
        with self._connect() as conn:
            row = conn.execute(
                "select status from collaboration_sessions where collaboration_id = ?",
                (collaboration_id,),
            ).fetchone()
            if row is None:
                raise CollaborationStoreError(f"collaboration session not found: {collaboration_id}")
            previous_status = str(row["status"] or "")
            if previous_status not in {"completed", "failed", "cancelled"}:
                return self.get_session(collaboration_id)
            conn.execute(
                """
                update collaboration_sessions
                set status = ?, round_index = round_index + 1,
                    started_at = coalesce(started_at, ?), completed_at = null, updated_at = ?
                where collaboration_id = ?
                """,
                ("running", now, now, collaboration_id),
            )
            self._insert_message_conn(
                conn,
                collaboration_id=collaboration_id,
                speaker_type="system",
                speaker_package_id=None,
                message_kind="session_reopened",
                content=f"协作会话已从 {previous_status} 重新打开，开始新的执行轮次。",
                task_id=None,
                event_ref=f"session-reopened:{collaboration_id}:{now}",
                created_at=now,
            )
        return self.get_session(collaboration_id)

    def repair_terminal_sessions_with_open_work(self) -> list[str]:
        now = utc_now_text()
        repaired: list[str] = []
        with self._connect() as conn:
            rows = conn.execute(
                """
                select distinct session.collaboration_id, session.status
                from collaboration_sessions as session
                join collaboration_tasks as task
                  on task.collaboration_id = session.collaboration_id
                where session.status in ('completed', 'failed', 'cancelled')
                  and task.status not in ('completed', 'failed', 'cancelled')
                """
            ).fetchall()
            for row in rows:
                collaboration_id = str(row["collaboration_id"])
                previous_status = str(row["status"])
                conn.execute(
                    """
                    update collaboration_sessions
                    set status = 'running', round_index = round_index + 1,
                        started_at = coalesce(started_at, ?), completed_at = null, updated_at = ?
                    where collaboration_id = ?
                    """,
                    (now, now, collaboration_id),
                )
                self._insert_message_conn(
                    conn,
                    collaboration_id=collaboration_id,
                    speaker_type="system",
                    speaker_package_id=None,
                    message_kind="session_recovered",
                    content=f"检测到 {previous_status} 会话仍有未完成任务，已恢复为 running。",
                    task_id=None,
                    event_ref=f"repair-terminal-session:{collaboration_id}:{now}",
                    created_at=now,
                )
                repaired.append(collaboration_id)
        return repaired

    def recover_interrupted_tasks(self) -> dict[str, Any]:
        now = utc_now_text()
        recovered: list[dict[str, str]] = []
        with self._connect() as conn:
            conn.execute("delete from collaboration_worker_leases")
            statuses = sorted(RECOVERABLE_RUNNING_TASK_STATUSES)
            placeholders = ", ".join("?" for _ in statuses)
            rows = conn.execute(
                f"""
                select task_id, collaboration_id, assignee_package_id, status, visible_context_json
                from collaboration_tasks
                where status in ({placeholders})
                """,
                tuple(statuses),
            ).fetchall()
            for row in rows:
                collaboration_id = str(row["collaboration_id"])
                task_id = str(row["task_id"])
                previous_status = str(row["status"])
                visible_context = json_loads(row["visible_context_json"], {})
                visible_context["recovery"] = {
                    "reason": "backend_restart",
                    "previous_status": previous_status,
                    "recovered_at": now,
                }
                conn.execute(
                    """
                    update collaboration_tasks
                    set status = ?, visible_context_json = ?, result_summary = ?,
                        result_payload_json = ?, updated_at = ?
                    where collaboration_id = ? and task_id = ?
                    """,
                    (
                        "queued",
                        json_dumps(visible_context),
                        "后端服务重启后恢复为待调度。",
                        json_dumps({"runtime_status": "recovered_after_backend_restart", "previous_status": previous_status}),
                        now,
                        collaboration_id,
                        task_id,
                    ),
                )
                self._insert_message_conn(
                    conn,
                    collaboration_id=collaboration_id,
                    speaker_type="system",
                    speaker_package_id=normalize_optional_text(row["assignee_package_id"]),
                    message_kind="progress",
                    content=f"检测到任务处于 {previous_status}，已恢复为 queued 等待重新调度。",
                    task_id=task_id,
                    event_ref=f"recover:{task_id}:{now}",
                    created_at=now,
                )
                self._mark_session_running_conn(conn, collaboration_id, now)
                conn.execute(
                    "update collaboration_sessions set status = ?, updated_at = ? where collaboration_id = ?",
                    ("running", now, collaboration_id),
                )
                recovered.append(
                    {
                        "collaboration_id": collaboration_id,
                        "task_id": task_id,
                        "previous_status": previous_status,
                    }
                )
            blocked_rows = conn.execute(
                """
                select collaboration_id, task_id, assignee_package_id
                from collaboration_tasks
                where status = ?
                order by created_at asc, task_id asc
                """,
                ("blocked",),
            ).fetchall()
            for row in blocked_rows:
                self._acquire_worker_lease_conn(
                    conn,
                    package_id=str(row["assignee_package_id"]),
                    collaboration_id=str(row["collaboration_id"]),
                    task_id=str(row["task_id"]),
                    acquired_at=now,
                )
        return {"recovered_count": len(recovered), "tasks": recovered}

    def recover_interrupted_main_agent_events(self) -> dict[str, Any]:
        now = utc_now_text()
        with self._connect() as conn:
            rows = conn.execute(
                """
                select event_id, collaboration_id
                from collaboration_main_agent_events
                where status = ?
                """,
                ("processing",),
            ).fetchall()
            conn.execute(
                """
                update collaboration_main_agent_events
                set status = ?, updated_at = ?
                where status = ?
                """,
                ("pending", now, "processing"),
            )
        return {
            "recovered_count": len(rows),
            "events": [dict(row) for row in rows],
        }

    def create_session(
        self,
        *,
        title: str,
        main_agent_package_id: str | None = None,
        approval_mode: str = DEFAULT_APPROVAL_MODE,
    ) -> dict[str, Any]:
        clean_title = title.strip() or "多 Agent 协作"
        clean_main = normalize_package_id(main_agent_package_id)
        clean_mode = validate_approval_mode(approval_mode)
        now = utc_now_text()
        collaboration_id = uuid4().hex
        self._session_workdir(collaboration_id).mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                insert into collaboration_sessions (
                  collaboration_id, title, main_agent_package_id, approval_mode,
                  status, execution_config_json, round_index, started_at,
                  completed_at, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (collaboration_id, clean_title, clean_main, clean_mode, "draft", "{}", 1, None, None, now, now),
            )
            conn.execute(
                """
                insert into collaboration_messages (
                  message_id, collaboration_id, speaker_type, speaker_package_id,
                  message_kind, content, task_id, event_ref, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    collaboration_id,
                    "system",
                    None,
                    "chat",
                    f"协作已创建，主 Agent 为 {clean_main}，审批模式为 {clean_mode}。",
                    None,
                    None,
                    now,
                ),
            )
        return self.get_session(collaboration_id)

    def get_session(self, collaboration_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "select * from collaboration_sessions where collaboration_id = ?",
                (collaboration_id,),
            ).fetchone()
            if row is None:
                raise CollaborationStoreError(f"collaboration session not found: {collaboration_id}")
            session = self._session_view(row)
            session["messages"] = [
                self._message_view(item)
                for item in conn.execute(
                    """
                    select * from collaboration_messages
                    where collaboration_id = ?
                    order by created_at asc, message_id asc
                    """,
                    (collaboration_id,),
                ).fetchall()
            ]
            session["tasks"] = [
                self._task_view(item)
                for item in conn.execute(
                    """
                    select * from collaboration_tasks
                    where collaboration_id = ?
                    order by created_at asc, task_id asc
                    """,
                    (collaboration_id,),
                ).fetchall()
            ]
            session["manufacturing_requests"] = [
                self._manufacturing_request_view(item)
                for item in conn.execute(
                    """
                    select * from collaboration_manufacturing_requests
                    where collaboration_id = ?
                    order by created_at asc, request_id asc
                    """,
                    (collaboration_id,),
                ).fetchall()
            ]
            self._attach_runtime_status(conn, session)
        return session

    def update_session(self, collaboration_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        existing = self.get_session(collaboration_id)
        title = str(payload.get("title") if "title" in payload else existing["title"]).strip() or existing["title"]
        main_agent_package_id = (
            normalize_package_id(payload.get("main_agent_package_id"))
            if "main_agent_package_id" in payload
            else existing["main_agent_package_id"]
        )
        main_agent_package_session_id = (
            normalize_optional_text(payload.get("main_agent_package_session_id"))
            if "main_agent_package_session_id" in payload
            else existing["main_agent_package_session_id"]
        )
        main_factory_session_id = (
            normalize_optional_text(payload.get("main_factory_session_id"))
            if "main_factory_session_id" in payload
            else existing["main_factory_session_id"]
        )
        approval_mode = (
            validate_approval_mode(str(payload.get("approval_mode")))
            if "approval_mode" in payload
            else existing["approval_mode"]
        )
        execution_config = (
            validate_execution_config(payload.get("execution_config"))
            if "execution_config" in payload
            else dict(existing.get("execution_config") or {})
        )
        status = str(payload.get("status") if "status" in payload else existing["status"]).strip()
        if status not in SESSION_STATUSES:
            raise CollaborationStoreError(f"unsupported collaboration session status: {status}")
        now = utc_now_text()
        started_at = existing.get("started_at")
        if status == "running" and not started_at:
            started_at = now
        completed_at = existing.get("completed_at")
        if status in TERMINAL_SESSION_STATUSES and not completed_at:
            completed_at = now
        elif status == "running":
            completed_at = None
        with self._connect() as conn:
            conn.execute(
                """
                update collaboration_sessions
                set title = ?, main_agent_package_id = ?, main_agent_package_session_id = ?,
                    main_factory_session_id = ?, approval_mode = ?, execution_config_json = ?,
                    status = ?, started_at = ?, completed_at = ?, updated_at = ?
                where collaboration_id = ?
                """,
                (
                    title,
                    main_agent_package_id,
                    main_agent_package_session_id,
                    main_factory_session_id,
                    approval_mode,
                    json_dumps(execution_config),
                    status,
                    started_at,
                    completed_at,
                    now,
                    collaboration_id,
                ),
            )
            if approval_mode != existing["approval_mode"]:
                self._insert_message_conn(
                    conn,
                    collaboration_id=collaboration_id,
                    speaker_type="system",
                    speaker_package_id=None,
                    message_kind="chat",
                    content=f"审批模式已切换为 {approval_mode}。",
                    task_id=None,
                    event_ref=None,
                    created_at=now,
                )
        return self.get_session(collaboration_id)

    def complete_session(self, collaboration_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        session = self.get_session(collaboration_id)
        final_summary = str(payload.get("final_summary") or payload.get("content") or "").strip()
        if not final_summary:
            final_summary = "协作已完成。"
        final_path = self._write_final_delivery(collaboration_id, final_summary)
        now = utc_now_text()
        with self._connect() as conn:
            conn.execute(
                """
                update collaboration_sessions
                set status = ?, completed_at = ?, updated_at = ?
                where collaboration_id = ?
                """,
                ("completed", now, now, collaboration_id),
            )
            self._insert_message_conn(
                conn,
                collaboration_id=collaboration_id,
                speaker_type=str(payload.get("speaker_type") or "main_agent").strip() or "main_agent",
                speaker_package_id=normalize_optional_text(payload.get("speaker_package_id")),
                message_kind="final_delivery",
                content=f"协作已完成。最终交付：{final_path}",
                task_id=None,
                event_ref=None,
                created_at=now,
            )
            self._touch_session_conn(conn, collaboration_id, now)
        result = self.get_session(collaboration_id)
        result["final_delivery"] = {
            "path": final_path,
            "kind": "markdown",
            "source": "collaboration_final",
            "created_by": payload.get("speaker_type") or "main_agent",
        }
        return result

    def add_message(self, collaboration_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.get_session(collaboration_id)
        now = utc_now_text()
        with self._connect() as conn:
            self._insert_message_conn(
                conn,
                collaboration_id=collaboration_id,
                speaker_type=str(payload.get("speaker_type") or "user").strip(),
                speaker_package_id=normalize_optional_text(payload.get("speaker_package_id")),
                message_kind=str(payload.get("message_kind") or "chat").strip(),
                content=str(payload.get("content") or "").strip(),
                task_id=normalize_optional_text(payload.get("task_id")),
                event_ref=normalize_optional_text(payload.get("event_ref")),
                created_at=now,
            )
            self._touch_session_conn(conn, collaboration_id, now)
        return self.get_session(collaboration_id)

    def record_message(
        self,
        collaboration_id: str,
        *,
        speaker_type: str,
        content: str,
        speaker_package_id: str | None = None,
        message_kind: str = "progress",
        task_id: str | None = None,
        event_ref: str | None = None,
    ) -> None:
        self.get_session(collaboration_id)
        now = utc_now_text()
        with self._connect() as conn:
            if event_ref:
                existing = conn.execute(
                    """
                    select message_id from collaboration_messages
                    where collaboration_id = ? and event_ref = ?
                    limit 1
                    """,
                    (collaboration_id, event_ref),
                ).fetchone()
                if existing is not None:
                    return
            self._insert_message_conn(
                conn,
                collaboration_id=collaboration_id,
                speaker_type=speaker_type,
                speaker_package_id=speaker_package_id,
                message_kind=message_kind,
                content=content,
                task_id=task_id,
                event_ref=event_ref,
                created_at=now,
            )
            self._touch_session_conn(conn, collaboration_id, now)

    def enqueue_main_agent_event(
        self,
        collaboration_id: str,
        *,
        user_message: str,
        message_metadata: dict[str, Any] | None = None,
        task_id: str | None = None,
        event_ref: str | None = None,
    ) -> dict[str, Any]:
        self.get_session(collaboration_id)
        clean_message = str(user_message or "").strip()
        if not clean_message:
            raise CollaborationStoreError("main agent event user_message must not be empty")
        clean_ref = normalize_optional_text(event_ref)
        now = utc_now_text()
        with self._connect() as conn:
            if clean_ref:
                existing = conn.execute(
                    """
                    select * from collaboration_main_agent_events
                    where collaboration_id = ? and event_ref = ?
                    limit 1
                    """,
                    (collaboration_id, clean_ref),
                ).fetchone()
                if existing is not None:
                    return self._main_agent_event_view(existing)
            event_id = uuid4().hex
            try:
                conn.execute(
                    """
                    insert into collaboration_main_agent_events (
                      event_id, collaboration_id, user_message, message_metadata_json,
                      task_id, event_ref, status, attempts, last_error, created_at, updated_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        collaboration_id,
                        clean_message,
                        json_dumps(message_metadata or {}),
                        normalize_optional_text(task_id),
                        clean_ref,
                        "pending",
                        0,
                        "",
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                if not clean_ref:
                    raise
                existing = conn.execute(
                    """
                    select * from collaboration_main_agent_events
                    where collaboration_id = ? and event_ref = ?
                    limit 1
                    """,
                    (collaboration_id, clean_ref),
                ).fetchone()
                if existing is not None:
                    return self._main_agent_event_view(existing)
                raise
            self._insert_message_conn(
                conn,
                collaboration_id=collaboration_id,
                speaker_type="system",
                speaker_package_id=None,
                message_kind="collaboration_event",
                content="协作事件已产生：子 Agent 已提交/阻塞/失败，系统将触发主 Agent 继续处理。",
                task_id=normalize_optional_text(task_id),
                event_ref=clean_ref,
                created_at=now,
            )
            self._mark_session_running_conn(conn, collaboration_id, now)
            row = conn.execute(
                "select * from collaboration_main_agent_events where event_id = ?",
                (event_id,),
            ).fetchone()
        if row is None:
            raise CollaborationStoreError("failed to enqueue main agent event")
        return self._main_agent_event_view(row)

    def pending_main_agent_event_count(self, collaboration_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                select count(*) as count
                from collaboration_main_agent_events
                where collaboration_id = ? and status = ?
                """,
                (collaboration_id, "pending"),
            ).fetchone()
        return int(row["count"] if row is not None else 0)

    def list_pending_main_agent_event_collaboration_ids(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select distinct collaboration_id
                from collaboration_main_agent_events
                where status = ?
                order by collaboration_id asc
                """,
                ("pending",),
            ).fetchall()
        return [str(row["collaboration_id"]) for row in rows]

    def oldest_pending_main_agent_event_created_at(self, collaboration_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select created_at
                from collaboration_main_agent_events
                where collaboration_id = ? and status = ?
                order by created_at asc, event_id asc
                limit 1
                """,
                (collaboration_id, "pending"),
            ).fetchone()
        return str(row["created_at"]) if row is not None else None

    def claim_main_agent_event_batch(
        self,
        collaboration_id: str,
        *,
        ready_before: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        clean_ready_before = str(ready_before or "").strip()
        if not clean_ready_before:
            raise CollaborationStoreError("main agent event ready_before must not be empty")
        if limit <= 0:
            raise CollaborationStoreError("main agent event batch limit must be positive")
        now = utc_now_text()
        with self._connect() as conn:
            conn.execute("begin immediate")
            ready = conn.execute(
                """
                select event_id from collaboration_main_agent_events
                where collaboration_id = ? and status = ? and created_at <= ?
                order by created_at asc, event_id asc
                limit 1
                """,
                (collaboration_id, "pending", clean_ready_before),
            ).fetchone()
            if ready is None:
                return []
            rows = conn.execute(
                """
                select * from collaboration_main_agent_events
                where collaboration_id = ? and status = ?
                order by created_at asc, event_id asc
                limit ?
                """,
                (collaboration_id, "pending", limit),
            ).fetchall()
            event_ids = [str(row["event_id"]) for row in rows]
            if not event_ids:
                return []
            placeholders = ", ".join("?" for _ in event_ids)
            conn.execute(
                f"""
                update collaboration_main_agent_events
                set status = ?, attempts = attempts + 1, updated_at = ?
                where event_id in ({placeholders}) and status = ?
                """,
                ("processing", now, *event_ids, "pending"),
            )
            claimed = conn.execute(
                f"""
                select * from collaboration_main_agent_events
                where event_id in ({placeholders})
                order by created_at asc, event_id asc
                """,
                tuple(event_ids),
            ).fetchall()
        return [self._main_agent_event_view(row) for row in claimed]

    def complete_main_agent_event_batch(self, event_ids: list[str]) -> None:
        self._resolve_main_agent_event_batch(event_ids, status="completed", error="")

    def fail_main_agent_event_batch(self, event_ids: list[str], error: str) -> None:
        self._resolve_main_agent_event_batch(event_ids, status="failed", error=error)

    def _resolve_main_agent_event_batch(
        self,
        event_ids: list[str],
        *,
        status: str,
        error: str,
    ) -> None:
        clean_ids = list(dict.fromkeys(str(event_id or "").strip() for event_id in event_ids))
        if not clean_ids or any(not event_id for event_id in clean_ids):
            raise CollaborationStoreError("main agent event batch must contain non-empty event ids")
        if status not in {"completed", "failed"}:
            raise CollaborationStoreError(f"unsupported main agent event terminal status: {status}")
        now = utc_now_text()
        placeholders = ", ".join("?" for _ in clean_ids)
        with self._connect() as conn:
            conn.execute("begin immediate")
            cursor = conn.execute(
                f"""
                update collaboration_main_agent_events
                set status = ?, last_error = ?, updated_at = ?
                where event_id in ({placeholders}) and status = ?
                """,
                (status, str(error or "").strip(), now, *clean_ids, "processing"),
            )
            if cursor.rowcount != len(clean_ids):
                raise CollaborationStoreError(
                    "main agent event batch state changed before terminal resolution"
                )

    def list_archived_main_agent_events(
        self,
        collaboration_id: str,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clean_collaboration_id = str(collaboration_id or "").strip()
        if not clean_collaboration_id:
            raise CollaborationStoreError("collaboration_id must not be empty")
        if limit < 1 or limit > 1000:
            raise CollaborationStoreError("archive event limit must be between 1 and 1000")
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from collaboration_main_agent_event_archive
                where collaboration_id = ?
                order by archived_at desc, created_at asc, event_id asc
                limit ?
                """,
                (clean_collaboration_id, limit),
            ).fetchall()
        return [self._archived_main_agent_event_view(row) for row in rows]

    def create_task(self, collaboration_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        session = self.get_session(collaboration_id)
        if str(session.get("status") or "") in {"completed", "failed", "cancelled"}:
            raise CollaborationStoreError(
                "cannot create a task in a terminal collaboration session; reopen the session first"
            )
        task_text = str(payload.get("task_text") or "").strip()
        if not task_text:
            raise CollaborationStoreError("task_text must not be empty")
        assignee = normalize_package_id(payload.get("assignee_package_id"))
        depends_on = normalize_dependency_ids(payload.get("depends_on"))
        delivery_standard = validate_delivery_standard(payload.get("delivery_standard"))
        _reject_duplicate_retry_task(
            session.get("tasks") or [],
            assignee_package_id=assignee,
            task_text=task_text,
            depends_on=depends_on,
            delivery_standard=delivery_standard,
        )
        self._validate_task_dependencies(collaboration_id, task_id=None, depends_on=depends_on)
        input_artifacts = merge_artifact_refs(
            dependency_artifact_refs(session, depends_on),
            normalize_artifact_refs(payload.get("input_artifacts")),
        )
        now = utc_now_text()
        task_id = uuid4().hex
        with self._connect() as conn:
            conn.execute(
                """
                insert into collaboration_tasks (
                  task_id, collaboration_id, parent_task_id, assignee_package_id,
                  assignee_session_id, task_text, depends_on_json, delivery_standard_json,
                  visible_context_json, input_artifacts_json, status, result_summary,
                  result_payload_json, artifact_refs_json, review_notes, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    collaboration_id,
                    normalize_optional_text(payload.get("parent_task_id")),
                    assignee,
                    normalize_optional_text(payload.get("assignee_session_id")),
                    task_text,
                    json_dumps(depends_on),
                    json_dumps(delivery_standard),
                    json_dumps(payload.get("visible_context") or {}),
                    json_dumps(input_artifacts),
                    "assigned",
                    "",
                    json_dumps({}),
                    json_dumps([]),
                    "",
                    now,
                    now,
                ),
            )
            self._insert_message_conn(
                conn,
                collaboration_id=collaboration_id,
                speaker_type="main_agent",
                speaker_package_id=None,
                message_kind="task_assigned",
                content=f"已将任务分配给 {assignee}：{task_text}",
                task_id=task_id,
                event_ref=None,
                created_at=now,
            )
            self._mark_session_running_conn(conn, collaboration_id, now)
        return self.get_session(collaboration_id)

    def retry_task(
        self,
        collaboration_id: str,
        task_id: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        retry_payload = dict(payload or {})
        replacement_task_id = uuid4().hex
        retry_cleanup_id: str | None = None
        current: dict[str, Any]
        current_status: str
        retry_context: dict[str, Any]
        now = utc_now_text()
        with self._connect() as conn:
            conn.execute("begin immediate")
            session_row = conn.execute(
                "select * from collaboration_sessions where collaboration_id = ?",
                (collaboration_id,),
            ).fetchone()
            if session_row is None:
                raise CollaborationStoreError(f"collaboration session not found: {collaboration_id}")
            task_rows = conn.execute(
                "select * from collaboration_tasks where collaboration_id = ? order by created_at, task_id",
                (collaboration_id,),
            ).fetchall()
            current_row = next((row for row in task_rows if str(row["task_id"]) == task_id), None)
            if current_row is None:
                raise CollaborationStoreError(f"collaboration task not found: {task_id}")
            current = self._task_view(current_row)
            current_status = str(current.get("status") or "")
            if current_status not in RETRYABLE_TASK_STATUSES:
                raise CollaborationStoreError(
                    f"task {task_id} cannot be retried from status {current_status!r}; "
                    f"expected one of {sorted(RETRYABLE_TASK_STATUSES)}"
                )

            assignee = normalize_package_id(
                retry_payload.get("assignee_package_id")
                if "assignee_package_id" in retry_payload
                else current.get("assignee_package_id")
            )
            task_text = str(
                retry_payload.get("task_text")
                if "task_text" in retry_payload
                else current.get("task_text")
                or ""
            ).strip()
            if not task_text:
                raise CollaborationStoreError("task_text must not be empty")
            depends_on = (
                normalize_dependency_ids(retry_payload.get("depends_on"))
                if "depends_on" in retry_payload
                else list(current.get("depends_on") or [])
            )
            task_views = [self._task_view(row) for row in task_rows]
            _validate_replacement_task_dependencies(
                task_views,
                replaced_task_id=task_id,
                replacement_task_id=replacement_task_id,
                depends_on=depends_on,
            )
            delivery_standard = (
                validate_delivery_standard(retry_payload.get("delivery_standard"))
                if "delivery_standard" in retry_payload
                else dict(current.get("delivery_standard") or {})
            )
            input_artifacts = merge_artifact_refs(
                dependency_artifact_refs({"tasks": task_views}, depends_on),
                normalize_artifact_refs(
                    retry_payload.get("input_artifacts")
                    if "input_artifacts" in retry_payload
                    else current.get("input_artifacts")
                ),
            )
            visible_context = dict(current.get("visible_context") or {})
            if "visible_context" in retry_payload:
                replacement_context = retry_payload.get("visible_context")
                if not isinstance(replacement_context, dict):
                    raise CollaborationStoreError("visible_context must be an object")
                visible_context = dict(replacement_context)
            retry_context = _task_retry_context(current, retry_payload)
            visible_context["retry"] = retry_context
            retry_cleanup_id = uuid4().hex if str(current.get("assignee_session_id") or "").strip() else None

            conn.execute(
                """
                insert into collaboration_tasks (
                  task_id, collaboration_id, parent_task_id, assignee_package_id,
                  assignee_session_id, task_text, depends_on_json, delivery_standard_json,
                  visible_context_json, input_artifacts_json, status, result_summary,
                  result_payload_json, artifact_refs_json, review_notes, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    replacement_task_id,
                    collaboration_id,
                    normalize_optional_text(current.get("parent_task_id")),
                    assignee,
                    None,
                    task_text,
                    json_dumps(depends_on),
                    json_dumps(delivery_standard),
                    json_dumps(visible_context),
                    json_dumps(input_artifacts),
                    "assigned",
                    "",
                    json_dumps({}),
                    json_dumps([]),
                    "",
                    now,
                    now,
                ),
            )
            dependent_rows = conn.execute(
                """
                select task_id, depends_on_json from collaboration_tasks
                where collaboration_id = ? and task_id not in (?, ?)
                """,
                (collaboration_id, task_id, replacement_task_id),
            ).fetchall()
            for dependent in dependent_rows:
                dependency_ids = json_loads(dependent["depends_on_json"], [])
                if task_id not in dependency_ids:
                    continue
                migrated = [replacement_task_id if item == task_id else item for item in dependency_ids]
                conn.execute(
                    """
                    update collaboration_tasks set depends_on_json = ?, updated_at = ?
                    where collaboration_id = ? and task_id = ?
                    """,
                    (json_dumps(migrated), now, collaboration_id, dependent["task_id"]),
                )
            conn.execute(
                """
                update collaboration_tasks set parent_task_id = ?, updated_at = ?
                where collaboration_id = ? and parent_task_id = ?
                """,
                (replacement_task_id, now, collaboration_id, task_id),
            )
            conn.execute(
                "delete from collaboration_worker_leases where collaboration_id = ? and task_id = ?",
                (collaboration_id, task_id),
            )
            conn.execute(
                "delete from collaboration_tasks where collaboration_id = ? and task_id = ?",
                (collaboration_id, task_id),
            )
            if retry_cleanup_id is not None:
                conn.execute(
                    """
                    insert into collaboration_task_retry_cleanups (
                      retry_id, collaboration_id, replaced_task_id, replacement_task_id,
                      assignee_package_id, assignee_session_id, status, attempts,
                      last_error, next_attempt_at, created_at, updated_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        retry_cleanup_id,
                        collaboration_id,
                        task_id,
                        replacement_task_id,
                        str(current.get("assignee_package_id") or ""),
                        str(current.get("assignee_session_id") or ""),
                        "pending",
                        0,
                        "",
                        now,
                        now,
                        now,
                    ),
                )
            self._insert_message_conn(
                conn,
                collaboration_id=collaboration_id,
                speaker_type="system",
                speaker_package_id=assignee,
                message_kind="task_retried",
                content=(
                    f"任务 {task_id} 已由新任务 {replacement_task_id} 原子替换。"
                    f" 上次状态：{current_status}。"
                    f" 失败原因：{retry_context['failure_reason']}"
                ),
                task_id=replacement_task_id,
                event_ref=f"task-retry:{task_id}:{replacement_task_id}",
                created_at=now,
            )
            self._mark_session_running_conn(conn, collaboration_id, now)

        replacement_session = self.get_session(collaboration_id)
        replacement_task = next(
            task
            for task in replacement_session.get("tasks") or []
            if str(task.get("task_id") or "") == replacement_task_id
        )
        return {
            "session": replacement_session,
            "task": replacement_task,
            "replaced_task": current,
            "retry_cleanup_id": retry_cleanup_id,
        }

    def recover_task_retry_cleanups(self) -> int:
        now = utc_now_text()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                update collaboration_task_retry_cleanups
                set status = 'pending', next_attempt_at = ?, updated_at = ?
                where status = 'processing'
                """,
                (now, now),
            )
            return int(cursor.rowcount)

    def claim_task_retry_cleanups(self, *, limit: int = 20) -> list[dict[str, Any]]:
        if limit < 1:
            return []
        now = utc_now_text()
        with self._connect() as conn:
            conn.execute("begin immediate")
            rows = conn.execute(
                """
                select * from collaboration_task_retry_cleanups
                where status = 'pending' and (next_attempt_at = '' or next_attempt_at <= ?)
                order by created_at asc, retry_id asc
                limit ?
                """,
                (now, limit),
            ).fetchall()
            retry_ids = [str(row["retry_id"]) for row in rows]
            if not retry_ids:
                return []
            placeholders = ", ".join("?" for _ in retry_ids)
            conn.execute(
                f"""
                update collaboration_task_retry_cleanups
                set status = 'processing', attempts = attempts + 1, updated_at = ?
                where status = 'pending' and retry_id in ({placeholders})
                """,
                (now, *retry_ids),
            )
            claimed = conn.execute(
                f"""
                select * from collaboration_task_retry_cleanups
                where status = 'processing' and retry_id in ({placeholders})
                order by created_at asc, retry_id asc
                """,
                tuple(retry_ids),
            ).fetchall()
        return [dict(row) for row in claimed]

    def resolve_task_retry_cleanup(
        self,
        retry_id: str,
        *,
        succeeded: bool,
        error: str = "",
    ) -> None:
        now = utc_now_text()
        with self._connect() as conn:
            row = conn.execute(
                "select attempts from collaboration_task_retry_cleanups where retry_id = ? and status = 'processing'",
                (retry_id,),
            ).fetchone()
            if row is None:
                raise CollaborationStoreError(f"task retry cleanup is not processing: {retry_id}")
            attempts = max(1, int(row["attempts"] or 1))
            delay_seconds = TASK_RETRY_CLEANUP_BASE_DELAY_SECONDS
            for _ in range(attempts - 1):
                if delay_seconds >= TASK_RETRY_CLEANUP_MAX_DELAY_SECONDS:
                    break
                delay_seconds = min(TASK_RETRY_CLEANUP_MAX_DELAY_SECONDS, delay_seconds * 2)
            next_attempt_at = (
                now
                if succeeded
                else (datetime.now(UTC) + timedelta(seconds=delay_seconds)).isoformat()
            )
            cursor = conn.execute(
                """
                update collaboration_task_retry_cleanups
                set status = ?, last_error = ?, next_attempt_at = ?, updated_at = ?
                where retry_id = ? and status = 'processing'
                """,
                (
                    "completed" if succeeded else "pending",
                    "" if succeeded else str(error),
                    next_attempt_at,
                    now,
                    retry_id,
                ),
            )
            if cursor.rowcount != 1:
                raise CollaborationStoreError(f"task retry cleanup is not processing: {retry_id}")

    def create_manufacturing_request(self, collaboration_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.get_session(collaboration_id)
        agent_name = str(payload.get("agent_name") or "").strip()
        purpose = str(payload.get("purpose") or "").strip()
        if not agent_name:
            raise CollaborationStoreError("agent_name must not be empty")
        if not purpose:
            raise CollaborationStoreError("purpose must not be empty")
        request_id = uuid4().hex
        now = utc_now_text()
        with self._connect() as conn:
            conn.execute(
                """
                insert into collaboration_manufacturing_requests (
                  request_id, collaboration_id, create_agent_session_id, status,
                  agent_name, purpose, request_payload_json, result_payload_json,
                  created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    collaboration_id,
                    None,
                    "requested",
                    agent_name,
                    purpose,
                    json_dumps(payload),
                    json_dumps({}),
                    now,
                    now,
                ),
            )
            self._insert_message_conn(
                conn,
                collaboration_id=collaboration_id,
                speaker_type="main_agent",
                speaker_package_id=None,
                message_kind="manufacturing_requested",
                content=f"已请求制造新 Agent：{agent_name}。用途：{purpose}",
                task_id=None,
                event_ref=f"manufacturing:{request_id}:requested",
                created_at=now,
            )
            self._mark_session_running_conn(conn, collaboration_id, now)
        return self.get_manufacturing_request(collaboration_id, request_id)

    def get_manufacturing_request(self, collaboration_id: str, request_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                select * from collaboration_manufacturing_requests
                where collaboration_id = ? and request_id = ?
                """,
                (collaboration_id, request_id),
            ).fetchone()
            if row is None:
                raise CollaborationStoreError(f"collaboration manufacturing request not found: {request_id}")
            return self._manufacturing_request_view(row)

    def list_active_manufacturing_requests(self, collaboration_id: str | None = None) -> list[dict[str, Any]]:
        statuses = sorted(MANUFACTURING_REQUEST_ACTIVE_STATUSES)
        placeholders = ", ".join("?" for _ in statuses)
        params: list[Any] = [*statuses]
        where = f"status in ({placeholders})"
        if collaboration_id:
            where += " and collaboration_id = ?"
            params.append(collaboration_id)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select * from collaboration_manufacturing_requests
                where {where}
                order by created_at asc, request_id asc
                """,
                tuple(params),
            ).fetchall()
        return [self._manufacturing_request_view(row) for row in rows]

    def update_manufacturing_request(
        self,
        collaboration_id: str,
        request_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        current = self.get_manufacturing_request(collaboration_id, request_id)
        status = str(payload.get("status") if "status" in payload else current["status"]).strip()
        if status not in MANUFACTURING_REQUEST_STATUSES:
            raise CollaborationStoreError(f"unsupported manufacturing request status: {status}")
        result_payload = (
            payload.get("result_payload")
            if "result_payload" in payload
            else current.get("result_payload") or {}
        )
        now = utc_now_text()
        with self._connect() as conn:
            conn.execute(
                """
                update collaboration_manufacturing_requests
                set create_agent_session_id = ?, status = ?, result_payload_json = ?, updated_at = ?
                where collaboration_id = ? and request_id = ?
                """,
                (
                    normalize_optional_text(payload.get("create_agent_session_id"))
                    if "create_agent_session_id" in payload
                    else current.get("create_agent_session_id"),
                    status,
                    json_dumps(result_payload),
                    now,
                    collaboration_id,
                    request_id,
                ),
            )
            message = str(payload.get("message") or "").strip()
            if message:
                self._insert_message_conn(
                    conn,
                    collaboration_id=collaboration_id,
                    speaker_type="system",
                    speaker_package_id=None,
                    message_kind=f"manufacturing_{status}",
                    content=message,
                    task_id=None,
                    event_ref=f"manufacturing:{request_id}:{status}:{now}",
                    created_at=now,
                )
            self._mark_session_running_conn(conn, collaboration_id, now)
        return self.get_manufacturing_request(collaboration_id, request_id)

    def update_task(self, collaboration_id: str, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        session = self.get_session(collaboration_id)
        with self._connect() as conn:
            row = conn.execute(
                """
                select * from collaboration_tasks
                where collaboration_id = ? and task_id = ?
                """,
                (collaboration_id, task_id),
            ).fetchone()
            if row is None:
                raise CollaborationStoreError(f"collaboration task not found: {task_id}")
            current = self._task_view(row)
            status = str(payload.get("status") if "status" in payload else current["status"]).strip()
            if status not in TASK_STATUSES:
                raise CollaborationStoreError(f"unsupported collaboration task status: {status}")
            depends_on = (
                normalize_dependency_ids(payload.get("depends_on"))
                if "depends_on" in payload
                else list(current["depends_on"])
            )
            delivery_standard = (
                validate_delivery_standard(payload.get("delivery_standard"))
                if "delivery_standard" in payload
                else current["delivery_standard"]
            )
            input_artifacts = (
                normalize_artifact_refs(payload.get("input_artifacts"))
                if "input_artifacts" in payload
                else list(current["input_artifacts"])
            )
            self._validate_task_dependencies(collaboration_id, task_id=task_id, depends_on=depends_on)
            dependency_artifacts = dependency_artifact_refs(session, depends_on)
            input_artifacts = merge_artifact_refs(dependency_artifacts, input_artifacts)
            if status in READY_TO_START_STATUSES and not delivery_standard:
                raise CollaborationStoreError("delivery_standard must not be empty for a startable task")
            dependencies_ready = dependencies_satisfied(session, depends_on)
            if status in READY_TO_START_STATUSES and depends_on and dependencies_ready and not input_artifacts:
                raise CollaborationStoreError("dependent tasks require at least one dependency artifact")
            result_payload = payload.get("result_payload") if "result_payload" in payload else current["result_payload"]
            artifact_refs = payload.get("artifact_refs") if "artifact_refs" in payload else current["artifact_refs"]
            _validate_task_completion_transition(
                current_status=str(current["status"]),
                next_status=status,
                current_delivery_standard=current["delivery_standard"],
                next_delivery_standard=delivery_standard,
                result_payload=result_payload,
                artifact_refs=artifact_refs,
            )
            now = utc_now_text()
            started_at = current.get("started_at")
            if not started_at and status in TASK_EXECUTION_STARTED_STATUSES:
                started_at = now
            completed_at = current.get("completed_at")
            if status in TASK_EXECUTION_FINISHED_STATUSES and not completed_at:
                completed_at = now
            elif status in ACTIVE_WORKER_TASK_STATUSES:
                completed_at = None
            if status in WORKER_LEASE_HOLDING_TASK_STATUSES:
                if not self._worker_lease_owned_conn(
                    conn,
                    package_id=str(current["assignee_package_id"]),
                    collaboration_id=collaboration_id,
                    task_id=task_id,
                ):
                    raise CollaborationStoreError(
                        f"worker lease is not owned by task {task_id}: {current['assignee_package_id']}"
                    )
            conn.execute(
                """
                update collaboration_tasks
                set task_text = ?, status = ?, assignee_session_id = ?, depends_on_json = ?,
                    delivery_standard_json = ?, visible_context_json = ?, input_artifacts_json = ?,
                    result_summary = ?, result_payload_json = ?,
                    artifact_refs_json = ?, review_notes = ?, started_at = ?,
                    completed_at = ?, updated_at = ?
                where collaboration_id = ? and task_id = ?
                """,
                (
                    str(payload.get("task_text") if "task_text" in payload else current["task_text"]),
                    status,
                    normalize_optional_text(payload.get("assignee_session_id"))
                    if "assignee_session_id" in payload
                    else current["assignee_session_id"],
                    json_dumps(depends_on),
                    json_dumps(delivery_standard),
                    json_dumps(payload.get("visible_context"))
                    if "visible_context" in payload
                    else json_dumps(current["visible_context"]),
                    json_dumps(input_artifacts),
                    str(payload.get("result_summary") if "result_summary" in payload else current["result_summary"]),
                    json_dumps(result_payload),
                    json_dumps(artifact_refs),
                    str(payload.get("review_notes") if "review_notes" in payload else current["review_notes"]),
                    started_at,
                    completed_at,
                    now,
                    collaboration_id,
                    task_id,
                ),
            )
            if current["status"] == "blocked" and status not in WORKER_LEASE_HOLDING_TASK_STATUSES:
                self._release_worker_lease_conn(
                    conn,
                    package_id=str(current["assignee_package_id"]),
                    collaboration_id=collaboration_id,
                    task_id=task_id,
                )
            self._insert_message_conn(
                conn,
                collaboration_id=collaboration_id,
                speaker_type="system",
                speaker_package_id=current["assignee_package_id"],
                message_kind=_task_message_kind(status),
                content=_task_status_message(status, payload),
                task_id=task_id,
                event_ref=None,
                created_at=now,
            )
            self._mark_session_running_conn(conn, collaboration_id, now)
        return self.get_session(collaboration_id)

    def queue_task_approval_decision(
        self,
        collaboration_id: str,
        task_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        action = str(payload.get("action") or "").strip()
        if action not in {"approve", "deny", "revise"}:
            raise CollaborationStoreError(f"unsupported collaboration approval action: {action}")
        reason = str(payload.get("decision_reason") or "").strip()
        if not reason:
            raise CollaborationStoreError("decision_reason is required for a main Agent approval decision")
        revision_guidance = str(payload.get("revision_guidance") or "").strip()
        if action == "revise" and not revision_guidance:
            raise CollaborationStoreError("revision_guidance is required when revising a worker tool call")
        now = utc_now_text()
        with self._connect() as conn:
            conn.execute("begin immediate")
            session_row = conn.execute(
                "select approval_mode from collaboration_sessions where collaboration_id = ?",
                (collaboration_id,),
            ).fetchone()
            if session_row is None:
                raise CollaborationStoreError(f"collaboration session not found: {collaboration_id}")
            if str(session_row["approval_mode"] or "") != "main_agent_delegated":
                raise CollaborationStoreError("main Agent approval decisions require main_agent_delegated mode")
            row = conn.execute(
                "select * from collaboration_tasks where collaboration_id = ? and task_id = ?",
                (collaboration_id, task_id),
            ).fetchone()
            if row is None:
                raise CollaborationStoreError(f"collaboration task not found: {task_id}")
            task = self._task_view(row)
            if str(task.get("status") or "") != "blocked":
                raise CollaborationStoreError("only a blocked task can receive a tool approval decision")
            result_payload = task.get("result_payload") if isinstance(task.get("result_payload"), dict) else {}
            pending_interrupt = (
                result_payload.get("pending_interrupt")
                if isinstance(result_payload.get("pending_interrupt"), dict)
                else {}
            )
            resume_payload = (
                pending_interrupt.get("resume_payload")
                if isinstance(pending_interrupt.get("resume_payload"), dict)
                else {}
            )
            if str(resume_payload.get("type") or "") != "tool_approval":
                raise CollaborationStoreError("blocked task is not waiting for a tool approval decision")
            existing = result_payload.get("approval_decision")
            if isinstance(existing, dict) and str(existing.get("status") or "") in {"pending", "processing"}:
                raise CollaborationStoreError("a tool approval decision is already pending for this task")
            decision = {
                "action": action,
                "decision_reason": reason,
                "revision_guidance": revision_guidance,
                "decided_by": "main_agent",
                "status": "pending",
                "created_at": now,
                "updated_at": now,
            }
            decision_message = _main_agent_approval_message(action, reason, revision_guidance)
            conn.execute(
                """
                update collaboration_tasks
                set result_summary = ?, result_payload_json = ?, updated_at = ?
                where collaboration_id = ? and task_id = ?
                """,
                (
                    decision_message,
                    json_dumps({**result_payload, "approval_decision": decision}),
                    now,
                    collaboration_id,
                    task_id,
                ),
            )
            self._insert_message_conn(
                conn,
                collaboration_id=collaboration_id,
                speaker_type="main_agent",
                speaker_package_id=None,
                message_kind="approval",
                content=decision_message,
                task_id=task_id,
                event_ref=None,
                created_at=now,
            )
            self._touch_session_conn(conn, collaboration_id, now)
        return self.get_session(collaboration_id)

    def list_pending_task_approval_decisions(self, collaboration_id: str) -> list[dict[str, Any]]:
        session = self.get_session(collaboration_id)
        result: list[dict[str, Any]] = []
        for task in session.get("tasks") or []:
            if str(task.get("status") or "") != "blocked":
                continue
            payload = task.get("result_payload") if isinstance(task.get("result_payload"), dict) else {}
            decision = payload.get("approval_decision") if isinstance(payload.get("approval_decision"), dict) else {}
            if str(decision.get("status") or "") == "pending":
                result.append({"task": task, "decision": decision})
        return result

    def claim_task_approval_decision(self, collaboration_id: str, task_id: str) -> dict[str, Any] | None:
        now = utc_now_text()
        with self._connect() as conn:
            row = conn.execute(
                "select * from collaboration_tasks where collaboration_id = ? and task_id = ?",
                (collaboration_id, task_id),
            ).fetchone()
            if row is None:
                return None
            task = self._task_view(row)
            payload = task.get("result_payload") if isinstance(task.get("result_payload"), dict) else {}
            decision = payload.get("approval_decision") if isinstance(payload.get("approval_decision"), dict) else {}
            if str(task.get("status") or "") != "blocked" or str(decision.get("status") or "") != "pending":
                return None
            claimed = {**decision, "status": "processing", "updated_at": now}
            conn.execute(
                """
                update collaboration_tasks
                set result_payload_json = ?, updated_at = ?
                where collaboration_id = ? and task_id = ?
                """,
                (json_dumps({**payload, "approval_decision": claimed}), now, collaboration_id, task_id),
            )
        return {"task": task, "decision": claimed}

    def fail_task_approval_decision(self, collaboration_id: str, task_id: str, error: str) -> None:
        now = utc_now_text()
        with self._connect() as conn:
            row = conn.execute(
                "select result_payload_json from collaboration_tasks where collaboration_id = ? and task_id = ?",
                (collaboration_id, task_id),
            ).fetchone()
            if row is None:
                return
            payload = json_loads(row["result_payload_json"], {})
            decision = payload.get("approval_decision") if isinstance(payload.get("approval_decision"), dict) else {}
            failed = {**decision, "status": "failed", "error": error, "updated_at": now}
            conn.execute(
                """
                update collaboration_tasks
                set status = ?, result_summary = ?, result_payload_json = ?, updated_at = ?
                where collaboration_id = ? and task_id = ?
                """,
                (
                    "blocked",
                    f"主 Agent 审批决定执行失败：{error}",
                    json_dumps({**payload, "approval_decision": failed}),
                    now,
                    collaboration_id,
                    task_id,
                ),
            )
            self._insert_message_conn(
                conn,
                collaboration_id=collaboration_id,
                speaker_type="system",
                speaker_package_id=None,
                message_kind="approval",
                content=f"主 Agent 审批决定执行失败：{error}",
                task_id=task_id,
                event_ref=None,
                created_at=now,
            )
            self._touch_session_conn(conn, collaboration_id, now)

    def recover_processing_task_approval_decisions(self) -> int:
        recovered = 0
        now = utc_now_text()
        with self._connect() as conn:
            rows = conn.execute(
                "select task_id, result_payload_json from collaboration_tasks where status = ?",
                ("blocked",),
            ).fetchall()
            for row in rows:
                payload = json_loads(row["result_payload_json"], {})
                decision = payload.get("approval_decision") if isinstance(payload.get("approval_decision"), dict) else {}
                if str(decision.get("status") or "") != "processing":
                    continue
                pending = {**decision, "status": "pending", "updated_at": now}
                conn.execute(
                    "update collaboration_tasks set result_payload_json = ?, updated_at = ? where task_id = ?",
                    (json_dumps({**payload, "approval_decision": pending}), now, row["task_id"]),
                )
                recovered += 1
        return recovered

    def delete_session(self, collaboration_id: str) -> dict[str, Any]:
        existing = self.get_session(collaboration_id)
        workdir = self._session_root(collaboration_id)
        if workdir.exists():
            shutil.rmtree(workdir)
        archived_at = utc_now_text()
        session_snapshot = {
            key: existing.get(key)
            for key in (
                "collaboration_id",
                "title",
                "main_agent_package_id",
                "main_agent_package_session_id",
                "main_factory_session_id",
                "approval_mode",
                "status",
                "created_at",
                "updated_at",
            )
        }
        with self._connect() as conn:
            archived_event_count = int(
                conn.execute(
                    """
                    select count(*) as count
                    from collaboration_main_agent_events
                    where collaboration_id = ?
                    """,
                    (collaboration_id,),
                ).fetchone()["count"]
            )
            conn.execute(
                """
                insert into collaboration_main_agent_event_archive (
                  event_id, collaboration_id, user_message, message_metadata_json,
                  task_id, event_ref, status, attempts, last_error, created_at,
                  updated_at, session_snapshot_json, archive_reason, archived_at
                )
                select event_id, collaboration_id, user_message, message_metadata_json,
                       task_id, event_ref, status, attempts, last_error, created_at,
                       updated_at, ?, ?, ?
                from collaboration_main_agent_events
                where collaboration_id = ?
                on conflict(event_id) do update set
                  status=excluded.status,
                  attempts=excluded.attempts,
                  last_error=excluded.last_error,
                  updated_at=excluded.updated_at,
                  session_snapshot_json=excluded.session_snapshot_json,
                  archive_reason=excluded.archive_reason,
                  archived_at=excluded.archived_at
                """,
                (
                    json_dumps(session_snapshot),
                    "collaboration_session_deleted",
                    archived_at,
                    collaboration_id,
                ),
            )
            conn.execute("delete from collaboration_main_agent_events where collaboration_id = ?", (collaboration_id,))
            conn.execute("delete from collaboration_manufacturing_requests where collaboration_id = ?", (collaboration_id,))
            conn.execute("delete from collaboration_task_retry_cleanups where collaboration_id = ?", (collaboration_id,))
            conn.execute("delete from collaboration_worker_leases where collaboration_id = ?", (collaboration_id,))
            conn.execute("delete from collaboration_tasks where collaboration_id = ?", (collaboration_id,))
            conn.execute("delete from collaboration_messages where collaboration_id = ?", (collaboration_id,))
            conn.execute("delete from collaboration_sessions where collaboration_id = ?", (collaboration_id,))
        return {
            "collaboration_id": collaboration_id,
            "deleted": True,
            "main_agent_package_id": existing["main_agent_package_id"],
            "main_agent_package_session_id": existing.get("main_agent_package_session_id"),
            "main_factory_session_id": existing.get("main_factory_session_id"),
            "archived_main_agent_event_count": archived_event_count,
            "sessions": self.list_sessions(),
        }

    def unlink_runtime_session(self, *, package_id: str, session_id: str) -> dict[str, Any]:
        clean_package_id = normalize_package_id(package_id)
        clean_session_id = normalize_optional_text(session_id)
        if not clean_session_id:
            raise CollaborationStoreError("session_id must not be empty")
        now = utc_now_text()
        with self._connect() as conn:
            main_rows = conn.execute(
                """
                select collaboration_id
                from collaboration_sessions
                where main_agent_package_id = ? and main_agent_package_session_id = ?
                """,
                (clean_package_id, clean_session_id),
            ).fetchall()
            task_rows = conn.execute(
                """
                select collaboration_id, task_id
                from collaboration_tasks
                where assignee_package_id = ? and assignee_session_id = ?
                """,
                (clean_package_id, clean_session_id),
            ).fetchall()
            for row in main_rows:
                collaboration_id = str(row["collaboration_id"])
                conn.execute(
                    """
                    update collaboration_sessions
                    set main_agent_package_session_id = null, updated_at = ?
                    where collaboration_id = ?
                    """,
                    (now, collaboration_id),
                )
                self._insert_message_conn(
                    conn,
                    collaboration_id=collaboration_id,
                    speaker_type="system",
                    speaker_package_id=clean_package_id,
                    message_kind="progress",
                    content=f"主 Agent 运行会话已删除，协作会话已解除绑定：{clean_session_id}",
                    task_id=None,
                    event_ref=f"runtime-session-unlinked:main:{clean_package_id}:{clean_session_id}:{now}",
                    created_at=now,
                )
            for row in task_rows:
                collaboration_id = str(row["collaboration_id"])
                task_id = str(row["task_id"])
                conn.execute(
                    """
                    update collaboration_tasks
                    set assignee_session_id = null, updated_at = ?
                    where collaboration_id = ? and task_id = ?
                    """,
                    (now, collaboration_id, task_id),
                )
                self._insert_message_conn(
                    conn,
                    collaboration_id=collaboration_id,
                    speaker_type="system",
                    speaker_package_id=clean_package_id,
                    message_kind="progress",
                    content=f"子 Agent 运行会话已删除，任务已解除会话绑定：{clean_session_id}",
                    task_id=task_id,
                    event_ref=f"runtime-session-unlinked:task:{clean_package_id}:{clean_session_id}:{task_id}:{now}",
                    created_at=now,
                )
        return {
            "package_id": clean_package_id,
            "session_id": clean_session_id,
            "main_agent_reference_count": len(main_rows),
            "worker_task_reference_count": len(task_rows),
            "collaboration_ids": sorted(
                {
                    *[str(row["collaboration_id"]) for row in main_rows],
                    *[str(row["collaboration_id"]) for row in task_rows],
                }
            ),
        }

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            self._ensure_collaboration_sessions_schema(conn)
            conn.execute(
                """
                create table if not exists collaboration_messages (
                  message_id text primary key,
                  collaboration_id text not null,
                  speaker_type text not null,
                  speaker_package_id text,
                  message_kind text not null,
                  content text not null,
                  task_id text,
                  event_ref text,
                  created_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists collaboration_tasks (
                  task_id text primary key,
                  collaboration_id text not null,
                  parent_task_id text,
                  assignee_package_id text not null,
                  assignee_session_id text,
                  task_text text not null,
                  depends_on_json text not null default '[]',
                  delivery_standard_json text not null,
                  visible_context_json text not null,
                  input_artifacts_json text not null,
                  status text not null,
                  result_summary text not null,
                  result_payload_json text not null,
                  artifact_refs_json text not null,
                  review_notes text not null,
                  created_at text not null,
                  updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists collaboration_manufacturing_requests (
                  request_id text primary key,
                  collaboration_id text not null,
                  create_agent_session_id text,
                  status text not null,
                  agent_name text not null,
                  purpose text not null,
                  request_payload_json text not null,
                  result_payload_json text not null,
                  created_at text not null,
                  updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists collaboration_main_agent_events (
                  event_id text primary key,
                  collaboration_id text not null,
                  user_message text not null,
                  message_metadata_json text not null,
                  task_id text,
                  event_ref text,
                  status text not null,
                  attempts integer not null default 0,
                  last_error text not null default '',
                  created_at text not null,
                  updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create unique index if not exists idx_collaboration_main_agent_events_ref
                on collaboration_main_agent_events(collaboration_id, event_ref)
                where event_ref is not null
                """
            )
            conn.execute(
                """
                create index if not exists idx_collaboration_main_agent_events_pending
                on collaboration_main_agent_events(collaboration_id, status, created_at, event_id)
                """
            )
            conn.execute(
                """
                create table if not exists collaboration_main_agent_event_archive (
                  event_id text primary key,
                  collaboration_id text not null,
                  user_message text not null,
                  message_metadata_json text not null,
                  task_id text,
                  event_ref text,
                  status text not null,
                  attempts integer not null,
                  last_error text not null,
                  created_at text not null,
                  updated_at text not null,
                  session_snapshot_json text not null,
                  archive_reason text not null,
                  archived_at text not null
                )
                """
            )
            conn.execute(
                """
                create index if not exists idx_collaboration_main_agent_event_archive_session
                on collaboration_main_agent_event_archive(collaboration_id, archived_at)
                """
            )
            conn.execute(
                """
                create table if not exists collaboration_worker_leases (
                  assignee_package_id text primary key,
                  collaboration_id text not null,
                  task_id text not null unique,
                  acquired_at text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists collaboration_task_retry_cleanups (
                  retry_id text primary key,
                  collaboration_id text not null,
                  replaced_task_id text not null unique,
                  replacement_task_id text not null,
                  assignee_package_id text not null,
                  assignee_session_id text not null,
                  status text not null,
                  attempts integer not null default 0,
                  last_error text not null default '',
                  next_attempt_at text not null default '',
                  created_at text not null,
                  updated_at text not null
                )
                """
            )
            conn.execute(
                """
                create index if not exists idx_collaboration_task_retry_cleanups_pending
                on collaboration_task_retry_cleanups(status, created_at, retry_id)
                """
            )
            self._ensure_column(
                conn,
                "collaboration_task_retry_cleanups",
                "next_attempt_at",
                "text not null default ''",
            )
            self._ensure_column(conn, "collaboration_tasks", "depends_on_json", "text not null default '[]'")
            self._ensure_column(conn, "collaboration_tasks", "started_at", "text")
            self._ensure_column(conn, "collaboration_tasks", "completed_at", "text")

    def _ensure_collaboration_sessions_schema(self, conn: sqlite3.Connection) -> None:
        target_columns = [
            "collaboration_id",
            "title",
            "main_agent_package_id",
            "main_agent_package_session_id",
            "main_factory_session_id",
            "approval_mode",
            "status",
            "execution_config_json",
            "round_index",
            "started_at",
            "completed_at",
            "created_at",
            "updated_at",
        ]
        rows = conn.execute("pragma table_info(collaboration_sessions)").fetchall()
        if not rows:
            conn.execute(
                """
                create table collaboration_sessions (
                  collaboration_id text primary key,
                  title text not null,
                  main_agent_package_id text not null,
                  main_agent_package_session_id text,
                  main_factory_session_id text,
                  approval_mode text not null,
                  status text not null,
                  execution_config_json text not null default '{}',
                  round_index integer not null default 1,
                  started_at text,
                  completed_at text,
                  created_at text not null,
                  updated_at text not null
                )
                """
            )
            return
        existing_columns = [str(row["name"]) for row in rows]
        if existing_columns == target_columns:
            return
        conn.execute("alter table collaboration_sessions rename to collaboration_sessions_legacy")
        conn.execute(
            """
            create table collaboration_sessions (
              collaboration_id text primary key,
              title text not null,
              main_agent_package_id text not null,
              main_agent_package_session_id text,
              main_factory_session_id text,
              approval_mode text not null,
              status text not null,
              execution_config_json text not null default '{}',
              round_index integer not null default 1,
              started_at text,
              completed_at text,
              created_at text not null,
              updated_at text not null
            )
            """
        )
        legacy = set(existing_columns)
        package_session_expr = (
            "main_agent_package_session_id"
            if "main_agent_package_session_id" in legacy
            else "null"
        )
        factory_session_expr = (
            "main_factory_session_id"
            if "main_factory_session_id" in legacy
            else "null"
        )
        execution_config_expr = "execution_config_json" if "execution_config_json" in legacy else "'{}'"
        round_index_expr = "round_index" if "round_index" in legacy else "1"
        started_at_expr = "started_at" if "started_at" in legacy else "null"
        completed_at_expr = "completed_at" if "completed_at" in legacy else "null"
        conn.execute(
            f"""
            insert into collaboration_sessions (
              collaboration_id, title, main_agent_package_id,
              main_agent_package_session_id, main_factory_session_id,
              approval_mode, status, execution_config_json, round_index,
              started_at, completed_at, created_at, updated_at
            )
            select
              collaboration_id, title, main_agent_package_id,
              {package_session_expr}, {factory_session_expr},
              approval_mode, status, {execution_config_expr}, {round_index_expr},
              {started_at_expr}, {completed_at_expr}, created_at, updated_at
            from collaboration_sessions_legacy
            """
        )
        conn.execute("drop table collaboration_sessions_legacy")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = connect_sqlite(
            self.path,
            timeout_ms=SQLITE_BUSY_TIMEOUT_MS,
            foreign_keys=True,
        )
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _session_view(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["execution_config"] = json_loads(data.pop("execution_config_json", "{}"), {})
        data["acceptance_workspace"] = {
            "resource_mode": "collaboration",
            "collaboration_id": data["collaboration_id"],
            "workdir": str(self._session_workdir(data["collaboration_id"])),
        }
        return data

    def _attach_runtime_status(self, conn: sqlite3.Connection, session: dict[str, Any]) -> None:
        collaboration_id = str(session.get("collaboration_id") or "")
        if str(session.get("status") or "") in TERMINAL_SESSION_STATUSES:
            session["runtime_status"] = None
            session["runtime_status_payload"] = {}
            return
        tasks = session.get("tasks")
        if not isinstance(tasks, list):
            tasks = [
                self._task_view(row)
                for row in conn.execute(
                    """
                    select * from collaboration_tasks
                    where collaboration_id = ?
                    order by created_at asc, task_id asc
                    """,
                    (collaboration_id,),
                ).fetchall()
            ]
        manufacturing_requests = session.get("manufacturing_requests")
        if not isinstance(manufacturing_requests, list):
            manufacturing_requests = [
                self._manufacturing_request_view(row)
                for row in conn.execute(
                    """
                    select * from collaboration_manufacturing_requests
                    where collaboration_id = ?
                    order by created_at asc, request_id asc
                    """,
                    (collaboration_id,),
                ).fetchall()
            ]
        event_counts = {
            str(row["status"]): int(row["count"])
            for row in conn.execute(
                """
                select status, count(*) as count
                from collaboration_main_agent_events
                where collaboration_id = ? and status in (?, ?)
                group by status
                """,
                (collaboration_id, "pending", "processing"),
            ).fetchall()
        }
        runtime_status, runtime_payload = collaboration_runtime_status_view(
            tasks=tasks,
            manufacturing_requests=manufacturing_requests,
            pending_event_count=event_counts.get("pending", 0),
            processing_event_count=event_counts.get("processing", 0),
        )
        session["runtime_status"] = runtime_status
        session["runtime_status_payload"] = runtime_payload

    def _task_view(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["depends_on"] = json_loads(data.pop("depends_on_json", "[]"), [])
        data["delivery_standard"] = json_loads(data.pop("delivery_standard_json"), {})
        data["visible_context"] = json_loads(data.pop("visible_context_json"), {})
        data["input_artifacts"] = json_loads(data.pop("input_artifacts_json"), [])
        data["result_payload"] = json_loads(data.pop("result_payload_json"), {})
        data["artifact_refs"] = json_loads(data.pop("artifact_refs_json"), [])
        return data

    def _message_view(self, row: sqlite3.Row) -> dict[str, Any]:
        return dict(row)

    def _manufacturing_request_view(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["request_payload"] = json_loads(data.pop("request_payload_json"), {})
        data["result_payload"] = json_loads(data.pop("result_payload_json"), {})
        return data

    def _main_agent_event_view(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["message_metadata"] = json_loads(data.pop("message_metadata_json", "{}"), {})
        return data

    def _archived_main_agent_event_view(self, row: sqlite3.Row) -> dict[str, Any]:
        data = self._main_agent_event_view(row)
        data["session_snapshot"] = json_loads(data.pop("session_snapshot_json", "{}"), {})
        return data

    def _insert_message_conn(
        self,
        conn: sqlite3.Connection,
        *,
        collaboration_id: str,
        speaker_type: str,
        speaker_package_id: str | None,
        message_kind: str,
        content: str,
        task_id: str | None,
        event_ref: str | None,
        created_at: str,
    ) -> None:
        if not content:
            content = " "
        conn.execute(
            """
            insert into collaboration_messages (
              message_id, collaboration_id, speaker_type, speaker_package_id,
              message_kind, content, task_id, event_ref, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid4().hex,
                collaboration_id,
                speaker_type,
                speaker_package_id,
                message_kind,
                content,
                task_id,
                event_ref,
                created_at,
            ),
        )

    def _touch_session_conn(self, conn: sqlite3.Connection, collaboration_id: str, updated_at: str) -> None:
        conn.execute(
            "update collaboration_sessions set updated_at = ? where collaboration_id = ?",
            (updated_at, collaboration_id),
        )

    def _mark_session_running_conn(self, conn: sqlite3.Connection, collaboration_id: str, updated_at: str) -> None:
        conn.execute(
            """
            update collaboration_sessions
            set status = case
                    when status in ('completed', 'failed', 'cancelled') then status
                    else 'running'
                end,
                started_at = coalesce(started_at, ?),
                updated_at = ?
            where collaboration_id = ?
            """,
            (updated_at, updated_at, collaboration_id),
        )

    def _session_root(self, collaboration_id: str) -> Path:
        return self.path.parent / "sessions" / collaboration_id

    def _session_workdir(self, collaboration_id: str) -> Path:
        return self._session_root(collaboration_id) / "workdir"

    def _write_final_delivery(self, collaboration_id: str, content: str) -> str:
        relative = "final/final-delivery.md"
        path = self._session_workdir(collaboration_id) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        return relative

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        rows = conn.execute(f"pragma table_info({table})").fetchall()
        if any(str(row["name"]) == column for row in rows):
            return
        conn.execute(f"alter table {table} add column {column} {ddl}")

    def session_workdir(self, collaboration_id: str) -> Path:
        self.get_session(collaboration_id)
        path = self._session_workdir(collaboration_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ready_tasks(self, collaboration_id: str) -> list[dict[str, Any]]:
        session = self.get_session(collaboration_id)
        return self._ready_tasks_from_session(session)

    def active_worker_task_keys(self) -> set[tuple[str, str]]:
        statuses = sorted(ACTIVE_WORKER_TASK_STATUSES)
        placeholders = ", ".join("?" for _ in statuses)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select collaboration_id, task_id
                from collaboration_tasks
                where status in ({placeholders})
                """,
                tuple(statuses),
            ).fetchall()
        return {
            (str(row["collaboration_id"]), str(row["task_id"]))
            for row in rows
        }

    def active_worker_task_count(self, collaboration_id: str | None = None) -> int:
        keys = self.active_worker_task_keys()
        if collaboration_id is None:
            return len(keys)
        return sum(1 for active_collaboration_id, _ in keys if active_collaboration_id == collaboration_id)

    def mark_tasks_waiting_for_inference_capacity(
        self,
        collaboration_id: str,
        *,
        task_ids: list[str],
        capacity: dict[str, Any],
        message: str,
    ) -> dict[str, Any]:
        requested_ids = {str(task_id or "").strip() for task_id in task_ids if str(task_id or "").strip()}
        if not requested_ids:
            return self.get_session(collaboration_id)
        session = self.get_session(collaboration_id)
        ready_by_id = {
            str(task.get("task_id") or ""): task
            for task in self._ready_tasks_from_session(session)
            if str(task.get("task_id") or "") in requested_ids
        }
        if not ready_by_id:
            return session
        now = utc_now_text()
        changed = False
        with self._connect() as conn:
            conn.execute("begin immediate")
            for task_id, task in ready_by_id.items():
                result_payload = task.get("result_payload") if isinstance(task.get("result_payload"), dict) else {}
                if result_payload.get("runtime_status") == "waiting_for_inference_capacity":
                    continue
                next_payload = {
                    **result_payload,
                    "runtime_status": "waiting_for_inference_capacity",
                    "inference_capacity": capacity,
                }
                updated = conn.execute(
                    f"""
                    update collaboration_tasks
                    set result_summary = ?, result_payload_json = ?, updated_at = ?
                    where collaboration_id = ? and task_id = ?
                      and status in ({READY_TO_START_STATUS_PLACEHOLDERS})
                    """,
                    (
                        message,
                        json_dumps(next_payload),
                        now,
                        collaboration_id,
                        task_id,
                        *sorted(READY_TO_START_STATUSES),
                    ),
                )
                if updated.rowcount != 1:
                    continue
                changed = True
                self._insert_message_conn(
                    conn,
                    collaboration_id=collaboration_id,
                    speaker_type="system",
                    speaker_package_id=task.get("assignee_package_id"),
                    message_kind="progress",
                    content=message,
                    task_id=task_id,
                    event_ref=f"inference-capacity-wait:{task_id}:{now}",
                    created_at=now,
                )
            if changed:
                self._mark_session_running_conn(conn, collaboration_id, now)
        return self.get_session(collaboration_id)

    @staticmethod
    def _worker_lease_owned_conn(
        conn: sqlite3.Connection,
        *,
        package_id: str,
        collaboration_id: str,
        task_id: str,
    ) -> bool:
        lease = conn.execute(
            """
            select collaboration_id, task_id
            from collaboration_worker_leases
            where assignee_package_id = ?
            """,
            (package_id,),
        ).fetchone()
        return bool(
            lease is not None
            and str(lease["collaboration_id"]) == collaboration_id
            and str(lease["task_id"]) == task_id
        )

    @staticmethod
    def _acquire_worker_lease_conn(
        conn: sqlite3.Connection,
        *,
        package_id: str,
        collaboration_id: str,
        task_id: str,
        acquired_at: str,
    ) -> bool:
        conn.execute(
            """
            insert or ignore into collaboration_worker_leases (
              assignee_package_id, collaboration_id, task_id, acquired_at
            ) values (?, ?, ?, ?)
            """,
            (package_id, collaboration_id, task_id, acquired_at),
        )
        return CollaborationStore._worker_lease_owned_conn(
            conn,
            package_id=package_id,
            collaboration_id=collaboration_id,
            task_id=task_id,
        )

    @staticmethod
    def _release_worker_lease_conn(
        conn: sqlite3.Connection,
        *,
        package_id: str,
        collaboration_id: str,
        task_id: str,
    ) -> bool:
        deleted = conn.execute(
            """
            delete from collaboration_worker_leases
            where assignee_package_id = ? and collaboration_id = ? and task_id = ?
            """,
            (package_id, collaboration_id, task_id),
        )
        return deleted.rowcount == 1

    def acquire_worker_lease(self, collaboration_id: str, task_id: str) -> bool:
        now = utc_now_text()
        with self._connect() as conn:
            conn.execute("begin immediate")
            row = conn.execute(
                """
                select assignee_package_id
                from collaboration_tasks
                where collaboration_id = ? and task_id = ?
                """,
                (collaboration_id, task_id),
            ).fetchone()
            if row is None:
                raise CollaborationStoreError(f"collaboration task not found: {task_id}")
            package_id = str(row["assignee_package_id"])
            return self._acquire_worker_lease_conn(
                conn,
                package_id=package_id,
                collaboration_id=collaboration_id,
                task_id=task_id,
                acquired_at=now,
            )

    def release_worker_lease_unless_blocked(self, collaboration_id: str, task_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                """
                select assignee_package_id, status
                from collaboration_tasks
                where collaboration_id = ? and task_id = ?
                """,
                (collaboration_id, task_id),
            ).fetchone()
            if row is None or str(row["status"]) == "blocked":
                return False
            return self._release_worker_lease_conn(
                conn,
                package_id=str(row["assignee_package_id"]),
                collaboration_id=collaboration_id,
                task_id=task_id,
            )

    def claim_ready_tasks(self, collaboration_id: str, *, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        session = self.get_session(collaboration_id)
        selected = self._ready_tasks_from_session(session)
        if not selected:
            return []
        now = utc_now_text()
        selected_ids: list[str] = []
        with self._connect() as conn:
            conn.execute("begin immediate")
            for task in selected:
                if len(selected_ids) >= limit:
                    break
                task_id = str(task.get("task_id") or "")
                if not task_id:
                    continue
                package_id = str(task.get("assignee_package_id") or "").strip()
                if not self._acquire_worker_lease_conn(
                    conn,
                    package_id=package_id,
                    collaboration_id=collaboration_id,
                    task_id=task_id,
                    acquired_at=now,
                ):
                    continue
                depends_on = normalize_dependency_ids(task.get("depends_on"))
                input_artifacts = merge_artifact_refs(
                    dependency_artifact_refs(session, depends_on),
                    normalize_artifact_refs(task.get("input_artifacts")),
                )
                if depends_on and not input_artifacts:
                    conn.execute(
                        """
                        update collaboration_tasks
                        set status = ?, result_summary = ?, result_payload_json = ?, updated_at = ?
                        where collaboration_id = ? and task_id = ?
                        """,
                        (
                            "failed",
                            "依赖任务没有可传递的 artifact_refs，无法启动 worker。",
                            json_dumps({"runtime_status": "missing_dependency_artifacts"}),
                            now,
                            collaboration_id,
                            task_id,
                        ),
                    )
                    self._insert_message_conn(
                        conn,
                        collaboration_id=collaboration_id,
                        speaker_type="system",
                        speaker_package_id=task.get("assignee_package_id"),
                        message_kind="progress",
                        content="依赖任务没有可传递的 artifact_refs，无法启动 worker。",
                        task_id=task_id,
                        event_ref=f"claim-missing-artifacts:{task_id}:{now}",
                        created_at=now,
                    )
                    self._release_worker_lease_conn(
                        conn,
                        package_id=package_id,
                        collaboration_id=collaboration_id,
                        task_id=task_id,
                    )
                    continue
                claimed = conn.execute(
                    f"""
                    update collaboration_tasks
                    set status = ?, input_artifacts_json = ?, result_summary = ?, result_payload_json = ?, updated_at = ?
                    where collaboration_id = ? and task_id = ?
                      and status in ({READY_TO_START_STATUS_PLACEHOLDERS})
                    """,
                    (
                        "accepted",
                        json_dumps(input_artifacts),
                        "任务已被协作调度器领取，准备启动 worker。",
                        json_dumps({"runtime_status": "claimed"}),
                        now,
                        collaboration_id,
                        task_id,
                        *sorted(READY_TO_START_STATUSES),
                    ),
                )
                if claimed.rowcount != 1:
                    self._release_worker_lease_conn(
                        conn,
                        package_id=package_id,
                        collaboration_id=collaboration_id,
                        task_id=task_id,
                    )
                    continue
                selected_ids.append(task_id)
                self._insert_message_conn(
                    conn,
                    collaboration_id=collaboration_id,
                    speaker_type="system",
                    speaker_package_id=task.get("assignee_package_id"),
                    message_kind="progress",
                    content="任务已被协作调度器领取，准备启动 worker。",
                    task_id=task_id,
                    event_ref=f"claim:{task_id}:{now}",
                    created_at=now,
                )
            self._mark_session_running_conn(conn, collaboration_id, now)
        refreshed = self.get_session(collaboration_id)
        tasks = refreshed.get("tasks") if isinstance(refreshed.get("tasks"), list) else []
        by_id = {str(task.get("task_id") or ""): task for task in tasks}
        return [by_id[task_id] for task_id in selected_ids if task_id in by_id]

    def _ready_tasks_from_session(self, session: dict[str, Any]) -> list[dict[str, Any]]:
        tasks = session.get("tasks") if isinstance(session.get("tasks"), list) else []
        by_id = {str(task.get("task_id")): task for task in tasks if task.get("task_id")}
        ready: list[dict[str, Any]] = []
        for task in tasks:
            status = str(task.get("status") or "")
            if status not in READY_TO_START_STATUSES:
                continue
            dependencies = normalize_dependency_ids(task.get("depends_on"))
            if all(str(by_id.get(item, {}).get("status") or "") in DEPENDENCY_SATISFIED_TASK_STATUSES for item in dependencies):
                ready.append(task)
        return ready

    def _validate_task_dependencies(
        self,
        collaboration_id: str,
        *,
        task_id: str | None,
        depends_on: list[str],
    ) -> None:
        session = self.get_session(collaboration_id)
        existing_tasks = session.get("tasks") if isinstance(session.get("tasks"), list) else []
        existing_ids = {str(task.get("task_id") or "") for task in existing_tasks if task.get("task_id")}
        if task_id and task_id in depends_on:
            raise CollaborationStoreError("task cannot depend on itself")
        missing = [dependency_id for dependency_id in depends_on if dependency_id not in existing_ids]
        if missing:
            raise CollaborationStoreError("unknown collaboration task dependencies: " + ", ".join(missing))
        graph = {
            str(task.get("task_id") or ""): normalize_dependency_ids(task.get("depends_on"))
            for task in existing_tasks
            if task.get("task_id")
        }
        if task_id:
            graph[task_id] = depends_on
        elif depends_on:
            graph["__new_task__"] = depends_on
        _ensure_acyclic_dependency_graph(graph)


def resolve_collaboration_store_path(value: str | Path | None = None) -> Path:
    if value:
        return resolve_project_path(value)
    return factory_artifact_path("collaboration", "factory.sqlite")


def normalize_package_id(value: Any) -> str:
    text = str(value or "").strip()
    return text or SYSTEM_CHAT_PACKAGE_ID


def normalize_optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def normalize_dependency_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        raw_items = [str(item or "").strip() for item in value]
    else:
        raw_items = []
    result: list[str] = []
    for item in raw_items:
        if item and item not in result:
            result.append(item)
    return result


def normalize_artifact_refs(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    result: list[Any] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, dict):
            key = json_dumps(item)
            clean = item
        else:
            clean_text = str(item or "").strip()
            if not clean_text:
                continue
            key = clean_text
            clean = clean_text
        if key in seen:
            continue
        seen.add(key)
        result.append(clean)
    return result


def dependency_artifact_refs(session: dict[str, Any], depends_on: list[str]) -> list[Any]:
    if not depends_on:
        return []
    tasks = session.get("tasks") if isinstance(session.get("tasks"), list) else []
    by_id = {str(task.get("task_id") or ""): task for task in tasks if task.get("task_id")}
    refs: list[Any] = []
    for task_id in depends_on:
        task = by_id.get(task_id)
        if not isinstance(task, dict):
            continue
        refs.extend(normalize_artifact_refs(task.get("artifact_refs")))
    return refs


def dependencies_satisfied(session: dict[str, Any], depends_on: list[str]) -> bool:
    if not depends_on:
        return True
    tasks = session.get("tasks") if isinstance(session.get("tasks"), list) else []
    by_id = {str(task.get("task_id") or ""): task for task in tasks if task.get("task_id")}
    return all(str(by_id.get(task_id, {}).get("status") or "") in DEPENDENCY_SATISFIED_TASK_STATUSES for task_id in depends_on)


def collaboration_runtime_status_view(
    *,
    tasks: list[dict[str, Any]],
    manufacturing_requests: list[dict[str, Any]],
    pending_event_count: int,
    processing_event_count: int,
) -> tuple[str | None, dict[str, Any]]:
    task_by_id = {
        str(task.get("task_id") or ""): task
        for task in tasks
        if str(task.get("task_id") or "")
    }
    if processing_event_count > 0:
        return "resuming_from_event", {
            "reason": "main_agent_event_processing",
            "processing_event_count": processing_event_count,
            "pending_event_count": pending_event_count,
        }

    approval_task_ids = [
        task_id
        for task_id, task in task_by_id.items()
        if str(task.get("status") or "") == "blocked"
        and isinstance((task.get("result_payload") or {}).get("pending_interrupt"), dict)
    ]
    if approval_task_ids:
        return "waiting_for_approval", {
            "reason": "worker_tool_approval",
            "task_ids": approval_task_ids,
            "task_count": len(approval_task_ids),
        }

    if pending_event_count > 0:
        return "resuming_from_event", {
            "reason": "main_agent_event_pending",
            "processing_event_count": 0,
            "pending_event_count": pending_event_count,
        }

    dependency_task_ids: list[str] = []
    dependency_reasons: set[str] = set()
    for task_id, task in task_by_id.items():
        if str(task.get("status") or "") == "blocked":
            dependency_task_ids.append(task_id)
            dependency_reasons.add("worker_blocked")
            continue
        if str(task.get("status") or "") not in READY_TO_START_STATUSES:
            continue
        result_payload = task.get("result_payload") if isinstance(task.get("result_payload"), dict) else {}
        if str(result_payload.get("runtime_status") or "") == "waiting_for_inference_capacity":
            dependency_task_ids.append(task_id)
            dependency_reasons.add("inference_capacity")
            continue
        depends_on = normalize_dependency_ids(task.get("depends_on"))
        if depends_on and not all(
            str(task_by_id.get(dependency_id, {}).get("status") or "") in DEPENDENCY_SATISFIED_TASK_STATUSES
            for dependency_id in depends_on
        ):
            dependency_task_ids.append(task_id)
            dependency_reasons.add("task_dependency")

    active_task_ids = [
        task_id
        for task_id, task in task_by_id.items()
        if str(task.get("status") or "") in ACTIVE_WORKER_TASK_STATUSES
    ]
    active_manufacturing_ids = [
        str(request.get("request_id") or "")
        for request in manufacturing_requests
        if str(request.get("status") or "") in MANUFACTURING_REQUEST_ACTIVE_STATUSES
        and str(request.get("request_id") or "")
    ]
    if active_task_ids or active_manufacturing_ids:
        return "waiting_for_workers", {
            "reason": "worker_activity",
            "task_ids": active_task_ids,
            "task_count": len(active_task_ids),
            "manufacturing_request_ids": active_manufacturing_ids,
            "manufacturing_request_count": len(active_manufacturing_ids),
        }

    if dependency_task_ids:
        return "waiting_for_dependency", {
            "reason": "external_or_task_dependency",
            "dependency_types": sorted(dependency_reasons),
            "task_ids": dependency_task_ids,
            "task_count": len(dependency_task_ids),
        }

    outstanding_task_ids = [
        task_id
        for task_id, task in task_by_id.items()
        if str(task.get("status") or "") not in {"completed", "cancelled", "failed"}
    ]
    if outstanding_task_ids:
        return "waiting_for_workers", {
            "reason": "outstanding_tasks",
            "task_ids": outstanding_task_ids,
            "task_count": len(outstanding_task_ids),
        }
    return None, {}


def merge_artifact_refs(*groups: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[str] = set()
    for group in groups:
        for item in normalize_artifact_refs(group):
            key = _artifact_ref_key(item)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
    return result


def _artifact_ref_key(item: Any) -> str:
    if isinstance(item, dict):
        path = str(item.get("path") or "").strip()
        if path:
            return path
        return json_dumps(item)
    return str(item or "").strip()


def validate_delivery_standard(value: Any) -> dict[str, Any]:
    try:
        return normalize_delivery_standard(value)
    except (TypeError, ValueError) as exc:
        raise CollaborationStoreError(f"invalid delivery_standard: {exc}") from exc


def _validate_replacement_task_dependencies(
    tasks: list[dict[str, Any]],
    *,
    replaced_task_id: str,
    replacement_task_id: str,
    depends_on: list[str],
) -> None:
    if replaced_task_id in depends_on or replacement_task_id in depends_on:
        raise CollaborationStoreError("task cannot depend on itself")
    existing_ids = {str(task.get("task_id") or "") for task in tasks if task.get("task_id")}
    missing = [dependency_id for dependency_id in depends_on if dependency_id not in existing_ids]
    if missing:
        raise CollaborationStoreError("unknown collaboration task dependencies: " + ", ".join(missing))
    graph: dict[str, list[str]] = {}
    for task in tasks:
        existing_task_id = str(task.get("task_id") or "")
        if not existing_task_id or existing_task_id == replaced_task_id:
            continue
        graph[existing_task_id] = [
            replacement_task_id if dependency_id == replaced_task_id else dependency_id
            for dependency_id in normalize_dependency_ids(task.get("depends_on"))
        ]
    graph[replacement_task_id] = list(depends_on)
    _ensure_acyclic_dependency_graph(graph)


def _reject_duplicate_retry_task(
    tasks: list[dict[str, Any]],
    *,
    assignee_package_id: str,
    task_text: str,
    depends_on: list[str],
    delivery_standard: dict[str, Any],
) -> None:
    for task in tasks:
        if str(task.get("status") or "") not in RETRYABLE_TASK_STATUSES:
            continue
        if str(task.get("assignee_package_id") or "") != assignee_package_id:
            continue
        if str(task.get("task_text") or "").strip() != task_text:
            continue
        if normalize_dependency_ids(task.get("depends_on")) != depends_on:
            continue
        if dict(task.get("delivery_standard") or {}) != delivery_standard:
            continue
        raise CollaborationStoreError(
            f"matching retryable task already exists: {task.get('task_id')}; use retry_task instead of create_task"
        )


def _task_retry_context(task: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    previous_context = task.get("visible_context") if isinstance(task.get("visible_context"), dict) else {}
    previous_retry = previous_context.get("retry") if isinstance(previous_context.get("retry"), dict) else {}
    result_payload = task.get("result_payload") if isinstance(task.get("result_payload"), dict) else {}
    reasons = [
        str(task.get("review_notes") or "").strip(),
        str(task.get("result_summary") or "").strip(),
        str(result_payload.get("error") or result_payload.get("last_error") or "").strip(),
    ]
    failure_reason = next((reason for reason in reasons if reason), "上一次任务未完成，需要重新执行。")
    previous_attempt = previous_retry.get("attempt")
    attempt = int(previous_attempt) + 1 if isinstance(previous_attempt, int) and previous_attempt > 0 else 1
    return {
        "attempt": attempt,
        "previous_task_id": str(task.get("task_id") or ""),
        "previous_status": str(task.get("status") or ""),
        "failure_reason": failure_reason,
        "retry_guidance": str(payload.get("retry_guidance") or "").strip(),
        "review_notes": str(task.get("review_notes") or "").strip(),
        "previous_result_summary": str(task.get("result_summary") or "").strip(),
    }


def _validate_task_completion_transition(
    *,
    current_status: str,
    next_status: str,
    current_delivery_standard: dict[str, Any],
    next_delivery_standard: dict[str, Any],
    result_payload: Any,
    artifact_refs: Any,
) -> None:
    if current_status == "submitted" and next_status != "revision_requested":
        if next_delivery_standard != current_delivery_standard:
            raise CollaborationStoreError(
                "a submitted task delivery standard can only change when requesting revision"
            )
    if next_status != "completed" or current_status == "completed":
        return
    if current_status != "submitted":
        raise CollaborationStoreError("a collaboration task can only be completed after validated submission")
    validation = result_payload.get("delivery_validation") if isinstance(result_payload, dict) else None
    if not isinstance(validation, dict) or validation.get("passed") is not True:
        raise CollaborationStoreError("task completion requires a passed delivery validation result")
    if not isinstance(artifact_refs, list) or not artifact_refs:
        raise CollaborationStoreError("task completion requires validated artifact references")


def validate_approval_mode(value: str) -> str:
    mode = str(value or "").strip() or DEFAULT_APPROVAL_MODE
    if mode not in APPROVAL_MODES:
        raise CollaborationStoreError(f"unsupported collaboration approval mode: {mode}")
    return mode


def validate_execution_config(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise CollaborationStoreError("execution_config must be an object")
    allowed = {"model_profile_id", "reasoning_intensity"}
    unsupported = sorted(str(key) for key in value if key not in allowed)
    if unsupported:
        raise CollaborationStoreError(
            "unsupported collaboration execution config fields: " + ", ".join(unsupported)
        )
    result: dict[str, Any] = {}
    if "model_profile_id" in value:
        profile_id = normalize_optional_text(value.get("model_profile_id"))
        if profile_id:
            result["model_profile_id"] = profile_id
    if "reasoning_intensity" in value:
        intensity = value.get("reasoning_intensity")
        if intensity is not None:
            if isinstance(intensity, bool) or not isinstance(intensity, int) or not 0 <= intensity <= 4:
                raise CollaborationStoreError("reasoning_intensity must be an integer from 0 to 4 or null")
            result["reasoning_intensity"] = intensity
    return result


def _main_agent_approval_message(action: str, reason: str, revision_guidance: str) -> str:
    if action == "approve":
        return f"主 Agent 批准 worker 工具调用。理由：{reason}"
    if action == "deny":
        return f"主 Agent 拒绝 worker 工具调用。理由：{reason}"
    return f"主 Agent 要求 worker 修改工具调用。理由：{reason} 修改意见：{revision_guidance}"


def _ensure_acyclic_dependency_graph(graph: dict[str, list[str]]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str, trail: list[str]) -> None:
        if task_id in visited:
            return
        if task_id in visiting:
            cycle = [*trail, task_id]
            raise CollaborationStoreError("collaboration task dependency cycle: " + " -> ".join(cycle))
        visiting.add(task_id)
        for dependency_id in graph.get(task_id, []):
            if dependency_id in graph:
                visit(dependency_id, [*trail, task_id])
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in graph:
        visit(task_id, [])


def utc_now_text() -> str:
    return datetime.now(UTC).isoformat()


def _task_message_kind(status: str) -> str:
    if status in {"submitted", "completed", "revision_requested"}:
        return "review"
    return "progress"


def _task_status_message(status: str, payload: dict[str, Any]) -> str:
    review_notes = str(payload.get("review_notes") or "").strip()
    result_summary = str(payload.get("result_summary") or "").strip()
    if status == "completed":
        return "任务已验收通过。" + (f" 验收意见：{review_notes}" if review_notes else "")
    if status == "revision_requested":
        return "任务需要返工。" + (f" 返工要求：{review_notes}" if review_notes else "")
    if status == "submitted":
        return "任务已提交待验收。" + (f" 摘要：{result_summary}" if result_summary else "")
    if status == "failed":
        return "任务执行失败。" + (f" 原因：{result_summary}" if result_summary else "")
    return f"任务状态更新为 {status}。" + (f" 备注：{review_notes}" if review_notes else "")


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_loads(value: str, default: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default
