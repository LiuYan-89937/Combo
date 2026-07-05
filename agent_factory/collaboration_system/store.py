from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from agent_factory.paths import factory_artifact_path, resolve_project_path


SYSTEM_CHAT_PACKAGE_ID = "factory_chat"
DEFAULT_APPROVAL_MODE = "user_controlled"
APPROVAL_MODES = {"user_controlled", "main_agent_delegated"}
SESSION_STATUSES = {"draft", "running", "completed", "failed", "cancelled"}
TERMINAL_SESSION_STATUSES = {"completed", "failed", "cancelled"}
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
READY_TO_START_STATUSES = {"assigned", "queued", "revision_requested"}
DEPENDENCY_SATISFIED_TASK_STATUSES = {"completed"}
RECOVERABLE_RUNNING_TASK_STATUSES = {"accepted", "planning", "working"}
SQLITE_BUSY_TIMEOUT_MS = 10000


class CollaborationStoreError(RuntimeError):
    pass


class CollaborationStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = resolve_collaboration_store_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from collaboration_sessions
                order by updated_at desc, created_at desc
                """
            ).fetchall()
        return [self._session_view(row) for row in rows]

    def list_auto_dispatch_sessions(self) -> list[dict[str, Any]]:
        sessions = [
            session
            for session in self.list_sessions()
            if session.get("approval_mode") == "main_agent_delegated"
            and session.get("status") not in {"completed", "failed", "cancelled"}
        ]
        return [session for session in sessions if self.ready_tasks(str(session.get("collaboration_id") or ""))]

    def recover_interrupted_tasks(self) -> dict[str, Any]:
        now = utc_now_text()
        recovered: list[dict[str, str]] = []
        with self._connect() as conn:
            statuses = sorted(RECOVERABLE_RUNNING_TASK_STATUSES)
            placeholders = ", ".join("?" for _ in statuses)
            rows = conn.execute(
                f"""
                select task_id, collaboration_id, assignee_package_id, status
                from collaboration_tasks
                where status in ({placeholders})
                """,
                tuple(statuses),
            ).fetchall()
            for row in rows:
                collaboration_id = str(row["collaboration_id"])
                task_id = str(row["task_id"])
                previous_status = str(row["status"])
                conn.execute(
                    """
                    update collaboration_tasks
                    set status = ?, result_summary = ?, result_payload_json = ?, updated_at = ?
                    where collaboration_id = ? and task_id = ?
                    """,
                    (
                        "queued",
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
                recovered.append(
                    {
                        "collaboration_id": collaboration_id,
                        "task_id": task_id,
                        "previous_status": previous_status,
                    }
                )
        return {"recovered_count": len(recovered), "tasks": recovered}

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
                  status, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?)
                """,
                (collaboration_id, clean_title, clean_main, clean_mode, "draft", now, now),
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
        return session

    def update_session(self, collaboration_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        existing = self.get_session(collaboration_id)
        title = str(payload.get("title") if "title" in payload else existing["title"]).strip() or existing["title"]
        main_agent_package_id = (
            normalize_package_id(payload.get("main_agent_package_id"))
            if "main_agent_package_id" in payload
            else existing["main_agent_package_id"]
        )
        main_agent_session_id = (
            normalize_optional_text(payload.get("main_agent_session_id"))
            if "main_agent_session_id" in payload
            else existing["main_agent_session_id"]
        )
        approval_mode = (
            validate_approval_mode(str(payload.get("approval_mode")))
            if "approval_mode" in payload
            else existing["approval_mode"]
        )
        status = str(payload.get("status") if "status" in payload else existing["status"]).strip()
        if status not in SESSION_STATUSES:
            raise CollaborationStoreError(f"unsupported collaboration session status: {status}")
        now = utc_now_text()
        with self._connect() as conn:
            conn.execute(
                """
                update collaboration_sessions
                set title = ?, main_agent_package_id = ?, main_agent_session_id = ?,
                    approval_mode = ?, status = ?, updated_at = ?
                where collaboration_id = ?
                """,
                (title, main_agent_package_id, main_agent_session_id, approval_mode, status, now, collaboration_id),
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
                set status = ?, updated_at = ?
                where collaboration_id = ?
                """,
                ("completed", now, collaboration_id),
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

    def create_task(self, collaboration_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.get_session(collaboration_id)
        task_text = str(payload.get("task_text") or "").strip()
        if not task_text:
            raise CollaborationStoreError("task_text must not be empty")
        assignee = normalize_package_id(payload.get("assignee_package_id"))
        depends_on = normalize_dependency_ids(payload.get("depends_on"))
        self._validate_task_dependencies(collaboration_id, task_id=None, depends_on=depends_on)
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
                    json_dumps(payload.get("delivery_standard") or {}),
                    json_dumps(payload.get("visible_context") or {}),
                    json_dumps(payload.get("input_artifacts") or []),
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

    def update_task(self, collaboration_id: str, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.get_session(collaboration_id)
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
            self._validate_task_dependencies(collaboration_id, task_id=task_id, depends_on=depends_on)
            now = utc_now_text()
            conn.execute(
                """
                update collaboration_tasks
                set task_text = ?, status = ?, assignee_session_id = ?, depends_on_json = ?,
                    delivery_standard_json = ?, visible_context_json = ?, input_artifacts_json = ?,
                    result_summary = ?, result_payload_json = ?,
                    artifact_refs_json = ?, review_notes = ?, updated_at = ?
                where collaboration_id = ? and task_id = ?
                """,
                (
                    str(payload.get("task_text") if "task_text" in payload else current["task_text"]),
                    status,
                    normalize_optional_text(payload.get("assignee_session_id"))
                    if "assignee_session_id" in payload
                    else current["assignee_session_id"],
                    json_dumps(depends_on),
                    json_dumps(payload.get("delivery_standard"))
                    if "delivery_standard" in payload
                    else json_dumps(current["delivery_standard"]),
                    json_dumps(payload.get("visible_context"))
                    if "visible_context" in payload
                    else json_dumps(current["visible_context"]),
                    json_dumps(payload.get("input_artifacts"))
                    if "input_artifacts" in payload
                    else json_dumps(current["input_artifacts"]),
                    str(payload.get("result_summary") if "result_summary" in payload else current["result_summary"]),
                    json_dumps(payload.get("result_payload") if "result_payload" in payload else current["result_payload"]),
                    json_dumps(payload.get("artifact_refs") if "artifact_refs" in payload else current["artifact_refs"]),
                    str(payload.get("review_notes") if "review_notes" in payload else current["review_notes"]),
                    now,
                    collaboration_id,
                    task_id,
                ),
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

    def delete_session(self, collaboration_id: str) -> dict[str, Any]:
        existing = self.get_session(collaboration_id)
        with self._connect() as conn:
            conn.execute("delete from collaboration_tasks where collaboration_id = ?", (collaboration_id,))
            conn.execute("delete from collaboration_messages where collaboration_id = ?", (collaboration_id,))
            conn.execute("delete from collaboration_sessions where collaboration_id = ?", (collaboration_id,))
        workdir = self._session_root(collaboration_id)
        if workdir.exists():
            shutil.rmtree(workdir)
        return {
            "collaboration_id": collaboration_id,
            "deleted": True,
            "main_agent_package_id": existing["main_agent_package_id"],
            "main_agent_session_id": existing.get("main_agent_session_id"),
            "sessions": self.list_sessions(),
        }

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists collaboration_sessions (
                  collaboration_id text primary key,
                  title text not null,
                  main_agent_package_id text not null,
                  main_agent_session_id text,
                  approval_mode text not null,
                  status text not null,
                  created_at text not null,
                  updated_at text not null
                )
                """
            )
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
            self._ensure_column(conn, "collaboration_tasks", "depends_on_json", "text not null default '[]'")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000)
        conn.row_factory = sqlite3.Row
        conn.execute(f"pragma busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
        conn.execute("pragma journal_mode = wal")
        conn.execute("pragma foreign_keys = on")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _session_view(self, row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["acceptance_workspace"] = {
            "resource_mode": "collaboration",
            "collaboration_id": data["collaboration_id"],
            "workdir": str(self._session_workdir(data["collaboration_id"])),
        }
        return data

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
                updated_at = ?
            where collaboration_id = ?
            """,
            (updated_at, collaboration_id),
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


def validate_approval_mode(value: str) -> str:
    mode = str(value or "").strip() or DEFAULT_APPROVAL_MODE
    if mode not in APPROVAL_MODES:
        raise CollaborationStoreError(f"unsupported collaboration approval mode: {mode}")
    return mode


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
    if status in {"failed", "blocked", "cancelled"}:
        return "progress"
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
