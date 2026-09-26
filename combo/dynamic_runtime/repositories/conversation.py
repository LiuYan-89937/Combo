from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
from typing import Any, Literal

from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.dynamic_runtime.persistence_helpers import (
    advance_conversation_revision,
    insert_message,
    insert_outbox,
    insert_turn,
)
from combo.dynamic_runtime.repositories.shared import _required_text, utc_now_text
from combo.runtime_protocol import ConversationMessage, ConversationTurn, OutboxRecord
from combo.runtime_protocol.state_machines import CONVERSATION_TURN_TRANSITIONS, require_transition


@dataclass(frozen=True, slots=True)
class ConversationIdentity:
    session_id: str
    principal_id: str
    workspace_id: str
    revision: int
    status: str


@dataclass(frozen=True, slots=True)
class ConversationSummary:
    session_id: str
    principal_id: str
    workspace_id: str
    title: str
    revision: int
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class WorkspaceIdentity:
    workspace_id: str
    principal_id: str
    kind: str
    managed_path: str | None
    mount_record_id: str | None
    revision: int
    status: str
    title: str | None
    mode: Literal["isolated", "project"]
    created_at: str
    updated_at: str


def _workspace_from_row(row: sqlite3.Row) -> WorkspaceIdentity:
    mode = str(row["mode"])
    if mode != "isolated" and mode != "project":
        raise ValueError(f"stored workspace has unsupported mode: {mode}")
    return WorkspaceIdentity(
        workspace_id=str(row["workspace_id"]),
        principal_id=str(row["principal_id"]),
        kind=str(row["kind"]),
        managed_path=str(row["managed_path"]) if row["managed_path"] is not None else None,
        mount_record_id=str(row["mount_record_id"]) if row["mount_record_id"] is not None else None,
        revision=int(row["revision"]),
        status=str(row["status"]),
        title=str(row["title"]) if row["title"] is not None else None,
        mode=mode,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


class ConversationStore:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def create_principal(self, principal_id: str) -> None:
        value = _required_text(principal_id, "principal_id")
        with self._database.transaction() as conn:
            conn.execute(
                "insert or ignore into principals(principal_id, created_at) values (?, ?)",
                (value, utc_now_text()),
            )

    def create_managed_workspace(
        self,
        *,
        workspace_id: str,
        principal_id: str,
        managed_path: str,
        title: str = "工作区",
        mode: Literal["isolated", "project"] = "project",
    ) -> None:
        now = utc_now_text()
        owner = _required_text(principal_id, "principal_id")
        with self._database.transaction() as conn:
            conn.execute(
                "insert or ignore into principals(principal_id, created_at) values (?, ?)",
                (owner, now),
            )
            conn.execute(
                """
                insert into workspaces(
                  workspace_id, principal_id, kind, managed_path, mount_record_id,
                  revision, status, created_at, updated_at, title, mode
                ) values (?, ?, 'managed', ?, null, 1, 'active', ?, ?, ?, ?)
                """,
                (
                    _required_text(workspace_id, "workspace_id"),
                    owner,
                    _required_text(managed_path, "managed_path"),
                    now,
                    now,
                    _required_text(title, "title"),
                    mode,
                ),
            )

    def create_managed_conversation(
        self,
        *,
        session_id: str,
        workspace_id: str,
        principal_id: str,
        managed_path: str,
        title: str,
    ) -> None:
        now = utc_now_text()
        owner = _required_text(principal_id, "principal_id")
        with self._database.transaction() as conn:
            conn.execute(
                "insert or ignore into principals(principal_id, created_at) values (?, ?)",
                (owner, now),
            )
            conn.execute(
                """
                insert into workspaces(
                  workspace_id, principal_id, kind, managed_path, mount_record_id,
                  revision, status, created_at, updated_at
                ) values (?, ?, 'managed', ?, null, 1, 'active', ?, ?)
                """,
                (
                    _required_text(workspace_id, "workspace_id"),
                    owner,
                    _required_text(managed_path, "managed_path"),
                    now,
                    now,
                ),
            )
            conn.execute(
                """
                insert into conversations(
                  session_id, principal_id, workspace_id, title, revision,
                  status, created_at, updated_at
                ) values (?, ?, ?, ?, 1, 'active', ?, ?)
                """,
                (
                    _required_text(session_id, "session_id"),
                    owner,
                    _required_text(workspace_id, "workspace_id"),
                    _required_text(title, "title"),
                    now,
                    now,
                ),
            )

    def create_mounted_workspace(
        self,
        *,
        workspace_id: str,
        principal_id: str,
        mount_record_id: str,
    ) -> None:
        now = utc_now_text()
        with self._database.transaction() as conn:
            conn.execute(
                """
                insert into workspaces(
                  workspace_id, principal_id, kind, managed_path, mount_record_id,
                  revision, status, created_at, updated_at
                ) values (?, ?, 'mounted', null, ?, 1, 'active', ?, ?)
                """,
                (
                    _required_text(workspace_id, "workspace_id"),
                    _required_text(principal_id, "principal_id"),
                    _required_text(mount_record_id, "mount_record_id"),
                    now,
                    now,
                ),
            )

    def create_linked_workspace(
        self,
        *,
        workspace_id: str,
        principal_id: str,
        source_path: str,
        title: str,
        mode: Literal["isolated", "project"] = "project",
    ) -> WorkspaceIdentity:
        now = utc_now_text()
        mount_record_id = f"mount_{workspace_id}"
        owner = _required_text(principal_id, "principal_id")
        with self._database.transaction() as conn:
            existing = conn.execute(
                """
                select workspace.* from workspaces as workspace
                join workspace_mount_records as mount on mount.mount_record_id = workspace.mount_record_id
                where workspace.principal_id = ? and workspace.kind = 'mounted'
                  and workspace.status = 'active' and workspace.mode = ?
                  and mount.status = 'active' and mount.source_path = ?
                order by workspace.created_at, workspace.workspace_id limit 1
                """,
                (owner, mode, source_path),
            ).fetchone()
            if existing is not None:
                return _workspace_from_row(existing)
            conn.execute(
                "insert or ignore into principals(principal_id, created_at) values (?, ?)",
                (owner, now),
            )
            conn.execute(
                "insert into workspace_mount_records values (?, ?, ?, ?, 'active', 1, ?, ?)",
                (mount_record_id, owner, _required_text(source_path, "source_path"), _required_text(title, "title"), now, now),
            )
            conn.execute(
                """
                insert into workspaces(
                  workspace_id, principal_id, kind, managed_path, mount_record_id,
                  revision, status, created_at, updated_at, title, mode
                ) values (?, ?, 'mounted', null, ?, 1, 'active', ?, ?, ?, ?)
                """,
                (workspace_id, owner, mount_record_id, now, now, title, mode),
            )
        return self.require_workspace(workspace_id)

    def update_workspace(
        self,
        *,
        workspace_id: str,
        principal_id: str,
        title: str | None = None,
        mode: Literal["isolated", "project"] | None = None,
        archived: bool | None = None,
    ) -> WorkspaceIdentity:
        current = self.require_workspace(workspace_id)
        owner = _required_text(principal_id, "principal_id")
        if current.principal_id != owner or current.status == "deleted":
            raise LookupError(f"workspace not found: {workspace_id}")
        next_title = current.title if title is None else _required_text(title, "title")
        next_mode = current.mode if mode is None else mode
        next_status = current.status if archived is None else "detached" if archived else "active"
        now = utc_now_text()
        with self._database.transaction() as conn:
            changed = conn.execute(
                """
                update workspaces
                set title = ?, mode = ?, status = ?, revision = revision + 1, updated_at = ?
                where workspace_id = ? and principal_id = ? and revision = ?
                """,
                (next_title, next_mode, next_status, now, current.workspace_id, owner, current.revision),
            ).rowcount
            if changed != 1:
                raise RuntimeError("workspace compare-and-set failed")
        return self.require_workspace(workspace_id)

    def require_mount_path(self, mount_record_id: str, principal_id: str) -> str:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                "select source_path from workspace_mount_records where mount_record_id = ? and principal_id = ? and status = 'active'",
                (_required_text(mount_record_id, "mount_record_id"), _required_text(principal_id, "principal_id")),
            ).fetchone()
        if row is None:
            raise LookupError(f"workspace mount not found: {mount_record_id}")
        return str(row["source_path"])

    def require_workspace_root(self, workspace_id: str, principal_id: str) -> str:
        workspace = self.require_workspace(workspace_id)
        owner = _required_text(principal_id, "principal_id")
        if workspace.principal_id != owner or workspace.status != "active":
            raise PermissionError("workspace is unavailable to the runtime principal")
        if workspace.kind == "managed" and workspace.managed_path is not None:
            root = workspace.managed_path
        elif workspace.kind == "mounted" and workspace.mount_record_id is not None:
            root = self.require_mount_path(workspace.mount_record_id, owner)
        else:
            raise RuntimeError("workspace has no executable filesystem projection")
        resolved = Path(root).expanduser().resolve()
        if not resolved.is_dir():
            raise FileNotFoundError(f"workspace directory not found: {resolved}")
        return str(resolved)

    def create_conversation(
        self,
        *,
        session_id: str,
        principal_id: str,
        workspace_id: str,
        title: str,
        source: Literal["user", "scheduler"] = "user",
    ) -> None:
        now = utc_now_text()
        with self._database.transaction() as conn:
            conn.execute(
                """
                insert into conversations(
                  session_id, principal_id, workspace_id, title, revision,
                  status, created_at, updated_at, source
                ) values (?, ?, ?, ?, 1, 'active', ?, ?, ?)
                """,
                (
                    _required_text(session_id, "session_id"),
                    _required_text(principal_id, "principal_id"),
                    _required_text(workspace_id, "workspace_id"),
                    _required_text(title, "title"),
                    now,
                    now,
                    source,
                ),
            )

    def require_identity(self, session_id: str) -> ConversationIdentity:
        value = _required_text(session_id, "session_id")
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                """
                select session_id, principal_id, workspace_id, revision, status
                from conversations where session_id = ?
                """,
                (value,),
            ).fetchone()
        if row is None:
            raise LookupError(f"conversation not found: {value}")
        return ConversationIdentity(
            session_id=str(row["session_id"]),
            principal_id=str(row["principal_id"]),
            workspace_id=str(row["workspace_id"]),
            revision=int(row["revision"]),
            status=str(row["status"]),
        )

    def list_for_principal(self, principal_id: str) -> list[ConversationSummary]:
        owner = _required_text(principal_id, "principal_id")
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                """
                select session_id, principal_id, workspace_id, title, revision,
                       status, created_at, updated_at
                from conversations
                where principal_id = ? and source = 'user'
                order by updated_at desc, session_id
                """,
                (owner,),
            ).fetchall()
        return [
            ConversationSummary(
                session_id=str(row["session_id"]),
                principal_id=str(row["principal_id"]),
                workspace_id=str(row["workspace_id"]),
                title=str(row["title"]),
                revision=int(row["revision"]),
                status=str(row["status"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        ]

    def require_workspace(self, workspace_id: str) -> WorkspaceIdentity:
        value = _required_text(workspace_id, "workspace_id")
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                """
                select workspace_id, principal_id, kind, managed_path, mount_record_id,
                       revision, status, title, mode, created_at, updated_at
                from workspaces where workspace_id = ?
                """,
                (value,),
            ).fetchone()
        if row is None:
            raise LookupError(f"workspace not found: {value}")
        return _workspace_from_row(row)

    def list_workspaces_for_principal(self, principal_id: str) -> list[WorkspaceIdentity]:
        owner = _required_text(principal_id, "principal_id")
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                """
                select workspace_id, principal_id, kind, managed_path, mount_record_id,
                       revision, status, title, mode, created_at, updated_at
                from workspaces where principal_id = ? order by updated_at desc, workspace_id
                """,
                (owner,),
            ).fetchall()
        return [_workspace_from_row(row) for row in rows]

    def next_task_revision(self, session_id: str) -> int:
        value = _required_text(session_id, "session_id")
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                """
                select coalesce(max(task_revision), 0) + 1 as next_revision
                from conversation_turns where session_id = ?
                """,
                (value,),
            ).fetchone()
        return int(row["next_revision"])

    def append_user_turn(
        self,
        *,
        turn: ConversationTurn,
        message: ConversationMessage,
        outbox: OutboxRecord,
    ) -> None:
        if message.role != "user":
            raise ValueError("append_user_turn requires a user message")
        if turn.session_id != message.session_id or turn.turn_id != message.turn_id:
            raise ValueError("turn and user message identities do not match")
        if turn.user_message_id != message.message_id:
            raise ValueError("turn user_message_id does not match message")
        with self._database.transaction() as conn:
            insert_turn(conn, turn)
            insert_message(conn, message)
            insert_outbox(conn, outbox)
            advance_conversation_revision(conn, turn.session_id, updated_at=utc_now_text())

    def append_message(self, *, message: ConversationMessage, outbox: OutboxRecord) -> None:
        with self._database.transaction() as conn:
            insert_message(conn, message)
            insert_outbox(conn, outbox)
            advance_conversation_revision(conn, message.session_id, updated_at=utc_now_text())

    def require_turn_for_message(self, *, session_id: str, message_id: str) -> ConversationTurn:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                """
                select payload_json from conversation_turns
                where session_id = ? and user_message_id = ?
                """,
                (
                    _required_text(session_id, "session_id"),
                    _required_text(message_id, "message_id"),
                ),
            ).fetchone()
        if row is None:
            raise LookupError(f"conversation turn not found for message: {message_id}")
        return ConversationTurn.model_validate_json(str(row["payload_json"]))

    def require_message(self, *, session_id: str, message_id: str) -> ConversationMessage:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                """
                select payload_json from conversation_messages
                where session_id = ? and message_id = ?
                """,
                (
                    _required_text(session_id, "session_id"),
                    _required_text(message_id, "message_id"),
                ),
            ).fetchone()
        if row is None:
            raise LookupError(f"conversation message not found: {message_id}")
        return ConversationMessage.model_validate_json(str(row["payload_json"]))

    def fail_pre_runtime_turn(self, *, source_command_id: str) -> ConversationTurn:
        status = "failed"
        command_id = _required_text(source_command_id, "source_command_id")
        now = utc_now_text()
        with self._database.transaction() as conn:
            row = conn.execute(
                """
                select payload_json from conversation_turns
                where json_extract(payload_json, '$.source_command_id') = ?
                """,
                (command_id,),
            ).fetchone()
            if row is None:
                raise LookupError(f"conversation turn not found for command: {command_id}")
            current = ConversationTurn.model_validate_json(str(row["payload_json"]))
            if current.status == status:
                return current
            require_transition(
                current.status,
                status,
                CONVERSATION_TURN_TRANSITIONS,
                machine="conversation turn",
            )
            terminal = current.model_copy(
                update={"status": status, "updated_at": now, "terminal_at": now}
            )
            changed = conn.execute(
                """
                update conversation_turns
                set status = ?, payload_json = ?, updated_at = ?, terminal_at = ?
                where turn_id = ? and status = ?
                """,
                (status, terminal.model_dump_json(), now, now, current.turn_id, current.status),
            ).rowcount
            if changed != 1:
                raise RuntimeError("conversation turn compare-and-set failed")
            insert_outbox(
                conn,
                OutboxRecord(
                    aggregate_kind="conversation",
                    aggregate_id=current.session_id,
                    aggregate_revision=current.task_revision,
                    event_id=f"conversation:{current.session_id}:turn:{current.turn_id}:{status}",
                    event_kind=f"conversation_turn_{status}",
                    payload={
                        "session_id": current.session_id,
                        "turn_id": current.turn_id,
                        "command_id": command_id,
                        "status": status,
                    },
                    created_at=now,
                    updated_at=now,
                ),
            )
            advance_conversation_revision(conn, current.session_id, updated_at=now)
        return terminal

    def messages(self, session_id: str, *, turn_ids: list[str] | None = None) -> list[ConversationMessage]:
        if turn_ids is not None and not turn_ids:
            return []
        turn_filter = ""
        parameters: list[Any] = [_required_text(session_id, "session_id")]
        if turn_ids is not None:
            turn_filter = f"and message.turn_id in ({','.join('?' for _ in turn_ids)})"
            parameters.extend(turn_ids)
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                f"""
                select message.payload_json
                from conversation_messages as message
                join conversation_turns as turn on turn.turn_id = message.turn_id
                where message.session_id = ? {turn_filter}
                order by turn.task_revision, message.turn_sequence
                """,
                parameters,
            ).fetchall()
        return [ConversationMessage.model_validate_json(str(row["payload_json"])) for row in rows]

    def messages_through_task_revision(
        self,
        *,
        session_id: str,
        task_revision: int,
    ) -> list[ConversationMessage]:
        if task_revision < 1:
            raise ValueError("task_revision must be positive")
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                """
                select message.payload_json
                from conversation_messages as message
                join conversation_turns as turn on turn.turn_id = message.turn_id
                where message.session_id = ? and turn.task_revision <= ?
                order by turn.task_revision, message.turn_sequence
                """,
                (_required_text(session_id, "session_id"), task_revision),
            ).fetchall()
        return [ConversationMessage.model_validate_json(str(row["payload_json"])) for row in rows]

    def messages_between_task_revisions(
        self,
        *,
        session_id: str,
        after_task_revision: int,
        through_task_revision: int,
    ) -> list[ConversationMessage]:
        if after_task_revision < 0:
            raise ValueError("after_task_revision must be non-negative")
        if through_task_revision <= after_task_revision:
            return []
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                """
                select message.payload_json
                from conversation_messages as message
                join conversation_turns as turn on turn.turn_id = message.turn_id
                where message.session_id = ?
                  and turn.task_revision > ?
                  and turn.task_revision <= ?
                order by turn.task_revision, message.turn_sequence
                """,
                (
                    _required_text(session_id, "session_id"),
                    after_task_revision,
                    through_task_revision,
                ),
            ).fetchall()
        return [ConversationMessage.model_validate_json(str(row["payload_json"])) for row in rows]

    def compactable_task_revision(self, session_id: str) -> int | None:
        value = _required_text(session_id, "session_id")
        with self._database.connection(query_only=True) as conn:
            active = conn.execute(
                """
                select 1 from conversation_turns
                where session_id = ?
                  and status in ('queued', 'running', 'waiting_approval', 'waiting_external')
                limit 1
                """,
                (value,),
            ).fetchone()
            if active is not None:
                raise RuntimeError("conversation context cannot be compressed while a turn is active")
            row = conn.execute(
                """
                select max(task_revision) as task_revision
                from conversation_turns
                where session_id = ? and status = 'completed'
                """,
                (value,),
            ).fetchone()
        revision = row["task_revision"] if row is not None else None
        return int(revision) if revision is not None else None
