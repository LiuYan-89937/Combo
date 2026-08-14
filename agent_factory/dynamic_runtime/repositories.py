from __future__ import annotations

from datetime import UTC, datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from agent_factory.dynamic_runtime.database import DynamicRuntimeDatabase
from agent_factory.dynamic_runtime.persistence_helpers import (
    advance_conversation_revision,
    insert_runtime_instance,
    insert_message,
    insert_outbox,
    insert_turn,
    upsert_capability_snapshot,
)
from agent_factory.runtime_protocol import (
    CapabilitySnapshot,
    AttachmentPart,
    CommandEnvelope,
    CommandReceipt,
    ConversationMessage,
    ConversationTurn,
    OutboxRecord,
    RuntimeInstance,
    RuntimeEvent,
    SendMessagePayload,
    TextPart,
    ToolCallRecord,
)
from agent_factory.runtime_protocol.state_machines import (
    COMMAND_TRANSITIONS,
    CONVERSATION_TURN_TRANSITIONS,
    RUNTIME_INSTANCE_TRANSITIONS,
    TOOL_CALL_TRANSITIONS,
    require_transition,
)


def utc_now_text() -> str:
    return datetime.now(UTC).isoformat()


CONTROL_COMMAND_KINDS = (
    "cancel_command_request",
    "cancel_runtime_request",
    "steer_runtime_request",
)


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
    ) -> None:
        now = utc_now_text()
        mount_record_id = f"mount_{workspace_id}"
        owner = _required_text(principal_id, "principal_id")
        with self._database.transaction() as conn:
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
        return WorkspaceIdentity(
            workspace_id=str(row["workspace_id"]),
            principal_id=str(row["principal_id"]),
            kind=str(row["kind"]),
            managed_path=str(row["managed_path"]) if row["managed_path"] is not None else None,
            mount_record_id=str(row["mount_record_id"]) if row["mount_record_id"] is not None else None,
            revision=int(row["revision"]),
            status=str(row["status"]),
            title=str(row["title"]) if row["title"] is not None else None,
            mode=str(row["mode"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )

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
        return [WorkspaceIdentity(
            workspace_id=str(row["workspace_id"]),
            principal_id=str(row["principal_id"]),
            kind=str(row["kind"]),
            managed_path=str(row["managed_path"]) if row["managed_path"] is not None else None,
            mount_record_id=str(row["mount_record_id"]) if row["mount_record_id"] is not None else None,
            revision=int(row["revision"]),
            status=str(row["status"]),
            title=str(row["title"]) if row["title"] is not None else None,
            mode=str(row["mode"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        ) for row in rows]

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
        return self._terminalize_pre_runtime_turn(
            source_command_id=source_command_id,
            status="failed",
        )

    def cancel_pre_runtime_turn(self, *, source_command_id: str) -> ConversationTurn:
        return self._terminalize_pre_runtime_turn(
            source_command_id=source_command_id,
            status="cancelled",
        )

    def _terminalize_pre_runtime_turn(
        self,
        *,
        source_command_id: str,
        status: Literal["failed", "cancelled"],
    ) -> ConversationTurn:
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

    def messages(self, session_id: str) -> list[ConversationMessage]:
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                """
                select payload_json from conversation_messages
                where session_id = ? order by created_at, rowid
                """,
                (_required_text(session_id, "session_id"),),
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
                order by turn.task_revision, message.created_at, message.rowid
                """,
                (_required_text(session_id, "session_id"), task_revision),
            ).fetchall()
        return [ConversationMessage.model_validate_json(str(row["payload_json"])) for row in rows]


class CommandInbox:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def accept(self, envelope: CommandEnvelope, receipt: CommandReceipt) -> CommandReceipt:
        if receipt.status != "received" or receipt.receipt_revision != 1:
            raise ValueError("new command receipt must start at received revision 1")
        if envelope.command_id != receipt.command_id:
            raise ValueError("command envelope and receipt IDs do not match")
        if envelope.client_instance_id != receipt.client_instance_id:
            raise ValueError("command envelope and receipt client identities do not match")
        if envelope.principal_id != receipt.principal_id or envelope.session_id != receipt.session_id:
            raise ValueError("command envelope and receipt ownership does not match")
        envelope_json = envelope.model_dump_json()
        with self._database.transaction() as conn:
            existing = conn.execute(
                "select envelope_json, receipt_json from command_inbox where command_id = ?",
                (envelope.command_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["envelope_json"]) != envelope_json:
                    raise ValueError("command_id was already submitted with a different envelope")
                return CommandReceipt.model_validate_json(str(existing["receipt_json"]))
            queued = receipt.model_copy(
                update={
                    "status": "queued",
                    "receipt_revision": 2,
                    "updated_at": utc_now_text(),
                }
            )
            sequence = int(
                conn.execute("select coalesce(max(queue_sequence), 0) + 1 from command_inbox").fetchone()[0]
            )
            conn.execute(
                """
                insert into command_inbox(
                  command_id, client_instance_id, principal_id, session_id, status,
                  receipt_revision, envelope_json, receipt_json, queue_sequence,
                  claimed_generation, received_at, updated_at, terminal_at, command_kind
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, null, ?, ?, ?, ?)
                """,
                (
                    receipt.command_id,
                    receipt.client_instance_id,
                    receipt.principal_id,
                    receipt.session_id,
                    queued.status,
                    queued.receipt_revision,
                    envelope_json,
                    queued.model_dump_json(),
                    sequence,
                    receipt.received_at,
                    queued.updated_at,
                    queued.terminal_at,
                    envelope.payload.kind,
                ),
            )
            if isinstance(envelope.payload, SendMessagePayload):
                _insert_send_message_intake(conn, envelope)
            queue_position = int(
                conn.execute(
                    """
                    select count(*) from command_inbox
                    where session_id = ? and command_id <> ?
                      and command_kind = 'send_message'
                      and status in ('queued', 'running')
                      and queue_sequence < ?
                    """,
                    (envelope.session_id, envelope.command_id, sequence),
                ).fetchone()[0]
            )
            insert_outbox(
                conn,
                OutboxRecord(
                    aggregate_kind="command",
                    aggregate_id=queued.command_id,
                    aggregate_revision=queued.receipt_revision,
                    event_id=f"command:{queued.command_id}:{queued.receipt_revision}",
                    event_kind="command_queued",
                    payload={
                        **queued.model_dump(mode="json"),
                        "command_kind": envelope.payload.kind,
                        "request_source": (
                            "internal"
                            if isinstance(envelope.payload, SendMessagePayload)
                            and envelope.payload.visibility == "internal"
                            else "user"
                        ),
                        "dispatch_state": "queued" if queue_position else "dispatching",
                        "queue_position": queue_position,
                    },
                    created_at=queued.updated_at,
                    updated_at=queued.updated_at,
                ),
            )
        return queued

    def queued_message_payload(
        self,
        *,
        command_id: str,
        principal_id: str,
        session_id: str,
    ) -> SendMessagePayload:
        target_id = _required_text(command_id, "command_id")
        owner = _required_text(principal_id, "principal_id")
        session = _required_text(session_id, "session_id")
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                """
                select receipt_json, envelope_json from command_inbox
                where command_id = ? and principal_id = ? and session_id = ?
                  and command_kind = 'send_message'
                """,
                (target_id, owner, session),
            ).fetchone()
            if row is None:
                raise LookupError(f"queued message command not found: {target_id}")
            receipt = CommandReceipt.model_validate_json(str(row["receipt_json"]))
            if receipt.status != "queued":
                raise ValueError(f"message command is not queued: {target_id}")
            envelope = CommandEnvelope.model_validate_json(str(row["envelope_json"]))
            if not isinstance(envelope.payload, SendMessagePayload):
                raise TypeError("queued steering target is not a send-message command")
        return envelope.payload

    def complete_queued_as_steering(
        self,
        *,
        command_id: str,
        principal_id: str,
        session_id: str,
    ) -> CommandReceipt:
        target_id = _required_text(command_id, "command_id")
        owner = _required_text(principal_id, "principal_id")
        session = _required_text(session_id, "session_id")
        with self._database.transaction() as conn:
            row = conn.execute(
                """
                select receipt_json from command_inbox
                where command_id = ? and principal_id = ? and session_id = ?
                  and command_kind = 'send_message'
                """,
                (target_id, owner, session),
            ).fetchone()
            if row is None:
                raise LookupError(f"queued message command not found: {target_id}")
            receipt = CommandReceipt.model_validate_json(str(row["receipt_json"]))
            if receipt.status != "queued":
                raise ValueError(f"message command is not queued: {target_id}")
            now = utc_now_text()
            completed = receipt.model_copy(
                update={
                    "status": "completed",
                    "receipt_revision": receipt.receipt_revision + 1,
                    "updated_at": now,
                    "terminal_at": now,
                }
            )
            changed = conn.execute(
                """
                update command_inbox
                set status = 'completed', receipt_revision = ?, receipt_json = ?,
                    updated_at = ?, terminal_at = ?
                where command_id = ? and status = 'queued' and receipt_revision = ?
                """,
                (
                    completed.receipt_revision,
                    completed.model_dump_json(),
                    now,
                    now,
                    target_id,
                    receipt.receipt_revision,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("queued steering command compare-and-set failed")
            turn_row = conn.execute(
                """
                select payload_json from conversation_turns
                where json_extract(payload_json, '$.source_command_id') = ?
                """,
                (target_id,),
            ).fetchone()
            if turn_row is None:
                raise LookupError(f"conversation turn not found for command: {target_id}")
            turn = ConversationTurn.model_validate_json(str(turn_row["payload_json"]))
            require_transition(turn.status, "completed", CONVERSATION_TURN_TRANSITIONS, machine="conversation turn")
            completed_turn = turn.model_copy(
                update={"status": "completed", "updated_at": now, "terminal_at": now}
            )
            turn_changed = conn.execute(
                """
                update conversation_turns
                set status = 'completed', payload_json = ?, updated_at = ?, terminal_at = ?
                where turn_id = ? and status = 'queued'
                """,
                (completed_turn.model_dump_json(), now, now, turn.turn_id),
            ).rowcount
            if turn_changed != 1:
                raise RuntimeError("queued steering turn compare-and-set failed")
            insert_outbox(
                conn,
                OutboxRecord(
                    aggregate_kind="command",
                    aggregate_id=target_id,
                    aggregate_revision=completed.receipt_revision,
                    event_id=f"command:{target_id}:steering:{uuid4().hex}",
                    event_kind="command_steering",
                    payload={
                        **completed.model_dump(mode="json"),
                        "command_kind": "send_message",
                        "dispatch_state": "promoted",
                    },
                    created_at=now,
                    updated_at=now,
                ),
            )
            insert_outbox(
                conn,
                OutboxRecord(
                    aggregate_kind="conversation",
                    aggregate_id=session,
                    aggregate_revision=turn.task_revision,
                    event_id=f"conversation:{session}:turn:{turn.turn_id}:steered",
                    event_kind="conversation_turn_completed",
                    payload={
                        "session_id": session,
                        "turn_id": turn.turn_id,
                        "command_id": target_id,
                        "status": "completed",
                        "disposition": "steered",
                    },
                    created_at=now,
                    updated_at=now,
                ),
            )
            advance_conversation_revision(conn, session, updated_at=now)
        return completed

    def cancel_queued_message(
        self,
        *,
        command_id: str,
        principal_id: str,
        session_id: str,
    ) -> CommandReceipt:
        target_id = _required_text(command_id, "command_id")
        owner = _required_text(principal_id, "principal_id")
        session = _required_text(session_id, "session_id")
        with self._database.transaction() as conn:
            row = conn.execute(
                """
                select receipt_json from command_inbox
                where command_id = ? and principal_id = ? and session_id = ?
                  and command_kind = 'send_message'
                """,
                (target_id, owner, session),
            ).fetchone()
            if row is None:
                raise LookupError(f"queued message command not found: {target_id}")
            receipt = CommandReceipt.model_validate_json(str(row["receipt_json"]))
            if receipt.status == "cancelled":
                return receipt
            if receipt.status != "queued":
                raise ValueError(f"message command is not queued: {target_id}")
            now = utc_now_text()
            cancelled = receipt.model_copy(
                update={
                    "status": "cancelled",
                    "receipt_revision": receipt.receipt_revision + 1,
                    "updated_at": now,
                    "terminal_at": now,
                }
            )
            changed = conn.execute(
                """
                update command_inbox
                set status = 'cancelled', receipt_revision = ?, receipt_json = ?,
                    updated_at = ?, terminal_at = ?
                where command_id = ? and status = 'queued' and receipt_revision = ?
                """,
                (
                    cancelled.receipt_revision,
                    cancelled.model_dump_json(),
                    now,
                    now,
                    target_id,
                    receipt.receipt_revision,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("queued message cancellation compare-and-set failed")
            turn_row = conn.execute(
                """
                select payload_json from conversation_turns
                where json_extract(payload_json, '$.source_command_id') = ?
                """,
                (target_id,),
            ).fetchone()
            if turn_row is None:
                raise LookupError(f"conversation turn not found for command: {target_id}")
            turn = ConversationTurn.model_validate_json(str(turn_row["payload_json"]))
            require_transition(turn.status, "cancelled", CONVERSATION_TURN_TRANSITIONS, machine="conversation turn")
            cancelled_turn = turn.model_copy(
                update={"status": "cancelled", "updated_at": now, "terminal_at": now}
            )
            turn_changed = conn.execute(
                """
                update conversation_turns
                set status = 'cancelled', payload_json = ?, updated_at = ?, terminal_at = ?
                where turn_id = ? and status = 'queued'
                """,
                (cancelled_turn.model_dump_json(), now, now, turn.turn_id),
            ).rowcount
            if turn_changed != 1:
                raise RuntimeError("queued conversation turn cancellation compare-and-set failed")
            insert_outbox(
                conn,
                OutboxRecord(
                    aggregate_kind="command",
                    aggregate_id=target_id,
                    aggregate_revision=cancelled.receipt_revision,
                    event_id=f"command:{target_id}:{cancelled.receipt_revision}",
                    event_kind="command_cancelled",
                    payload={**cancelled.model_dump(mode="json"), "command_kind": "send_message"},
                    created_at=now,
                    updated_at=now,
                ),
            )
            insert_outbox(
                conn,
                OutboxRecord(
                    aggregate_kind="conversation",
                    aggregate_id=session,
                    aggregate_revision=turn.task_revision,
                    event_id=f"conversation:{session}:turn:{turn.turn_id}:cancelled",
                    event_kind="conversation_turn_cancelled",
                    payload={
                        "session_id": session,
                        "turn_id": turn.turn_id,
                        "command_id": target_id,
                        "status": "cancelled",
                    },
                    created_at=now,
                    updated_at=now,
                ),
            )
            advance_conversation_revision(conn, session, updated_at=now)
        return cancelled

    def get_receipt(self, command_id: str) -> CommandReceipt:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                "select receipt_json from command_inbox where command_id = ?",
                (_required_text(command_id, "command_id"),),
            ).fetchone()
        if row is None:
            raise LookupError(f"command receipt not found: {command_id}")
        return CommandReceipt.model_validate_json(str(row["receipt_json"]))

    def claim_next(
        self,
        *,
        generation: int,
        lane: Literal["work", "control"],
    ) -> tuple[CommandEnvelope, CommandReceipt] | None:
        if generation < 1:
            raise ValueError("generation must be positive")
        with self._database.transaction() as conn:
            now = utc_now_text()
            owner = conn.execute(
                """
                select 1 from application_generations
                where generation = ? and status = 'active' and lease_expires_at > ?
                """,
                (generation, now),
            ).fetchone()
            if owner is None:
                raise RuntimeError("command dispatcher generation is not active or its lease expired")
            control_placeholders = ", ".join("?" for _ in CONTROL_COMMAND_KINDS)
            lane_filter = (
                f"queued.command_kind in ({control_placeholders})"
                if lane == "control"
                else f"queued.command_kind not in ({control_placeholders})"
            )
            row = conn.execute(
                f"""
                select * from command_inbox queued
                where queued.status = 'queued'
                  and {lane_filter}
                  and (
                    queued.command_kind in ({control_placeholders})
                    or not exists (
                      select 1 from command_inbox active
                      where active.session_id = queued.session_id and active.status = 'running'
                    )
                  )
                order by
                  queued.queue_sequence
                limit 1
                """,
                (*CONTROL_COMMAND_KINDS, *CONTROL_COMMAND_KINDS),
            ).fetchone()
            if row is None:
                return None
            current = CommandReceipt.model_validate_json(str(row["receipt_json"]))
            require_transition(current.status, "running", COMMAND_TRANSITIONS, machine="command")
            updated = current.model_copy(
                update={
                    "status": "running",
                    "receipt_revision": current.receipt_revision + 1,
                    "updated_at": utc_now_text(),
                }
            )
            changed = conn.execute(
                """
                update command_inbox
                set status = 'running', receipt_revision = ?, receipt_json = ?,
                    claimed_generation = ?, updated_at = ?
                where command_id = ? and status = 'queued' and receipt_revision = ?
                """,
                (
                    updated.receipt_revision,
                    updated.model_dump_json(),
                    generation,
                    updated.updated_at,
                    updated.command_id,
                    current.receipt_revision,
                ),
            ).rowcount
            if changed != 1:
                return None
            envelope = CommandEnvelope.model_validate_json(str(row["envelope_json"]))
            return envelope, updated

    def replace_receipt(
        self,
        *,
        receipt: CommandReceipt,
        expected_revision: int,
        outbox: OutboxRecord,
    ) -> None:
        with self._database.transaction() as conn:
            row = conn.execute(
                "select receipt_json from command_inbox where command_id = ?",
                (receipt.command_id,),
            ).fetchone()
            if row is None:
                raise LookupError(f"command receipt not found: {receipt.command_id}")
            current = CommandReceipt.model_validate_json(str(row["receipt_json"]))
            require_transition(current.status, receipt.status, COMMAND_TRANSITIONS, machine="command")
            if receipt.receipt_revision != expected_revision + 1:
                raise ValueError("command receipt revision must increase by one")
            changed = conn.execute(
                """
                update command_inbox
                set status = ?, receipt_revision = ?, receipt_json = ?, updated_at = ?, terminal_at = ?
                where command_id = ? and receipt_revision = ?
                """,
                (
                    receipt.status,
                    receipt.receipt_revision,
                    receipt.model_dump_json(),
                    receipt.updated_at,
                    receipt.terminal_at,
                    receipt.command_id,
                    expected_revision,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("command receipt compare-and-set failed")
            insert_outbox(conn, outbox)


class RuntimeInstanceStore:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def create(
        self,
        *,
        snapshot: CapabilitySnapshot,
        instance: RuntimeInstance,
        outbox: OutboxRecord,
    ) -> None:
        if snapshot.snapshot_id != instance.capability_snapshot_id:
            raise ValueError("runtime instance references a different capability snapshot")
        with self._database.transaction() as conn:
            upsert_capability_snapshot(conn, snapshot)
            insert_runtime_instance(conn, instance)
            insert_outbox(conn, outbox)

    def get(self, runtime_instance_id: str) -> RuntimeInstance:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                "select payload_json from runtime_instances where runtime_instance_id = ?",
                (_required_text(runtime_instance_id, "runtime_instance_id"),),
            ).fetchone()
        if row is None:
            raise LookupError(f"runtime instance not found: {runtime_instance_id}")
        return RuntimeInstance.model_validate_json(str(row["payload_json"]))

    def active_main_for_session(self, *, session_id: str, principal_id: str) -> RuntimeInstance:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                """
                select payload_json from runtime_instances
                where session_id = ?
                  and json_extract(payload_json, '$.request.principal_id') = ?
                  and json_extract(payload_json, '$.request.runtime_role') = 'main'
                  and status in ('queued', 'running', 'waiting_approval', 'waiting_external', 'cancelling')
                order by updated_at desc, rowid desc limit 1
                """,
                (
                    _required_text(session_id, "session_id"),
                    _required_text(principal_id, "principal_id"),
                ),
            ).fetchone()
        if row is None:
            raise LookupError(f"active runtime not found for session: {session_id}")
        return RuntimeInstance.model_validate_json(str(row["payload_json"]))

    def capability_snapshot(self, snapshot_id: str) -> CapabilitySnapshot:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                "select payload_json from capability_snapshots where snapshot_id = ?",
                (_required_text(snapshot_id, "snapshot_id"),),
            ).fetchone()
        if row is None:
            raise LookupError(f"capability snapshot not found: {snapshot_id}")
        return CapabilitySnapshot.model_validate_json(str(row["payload_json"]))

    def replace(
        self,
        *,
        instance: RuntimeInstance,
        expected_status: str,
        expected_generation: int,
        outbox: OutboxRecord,
    ) -> None:
        require_transition(expected_status, instance.status, RUNTIME_INSTANCE_TRANSITIONS, machine="runtime instance")
        if instance.generation != expected_generation:
            raise ValueError("runtime instance generation cannot change during state transition")
        with self._database.transaction() as conn:
            changed = conn.execute(
                """
                update runtime_instances
                set status = ?, attempt_id = ?, last_event_sequence = ?,
                    payload_json = ?, updated_at = ?, terminal_at = ?
                where runtime_instance_id = ? and status = ? and generation = ?
                """,
                (
                    instance.status,
                    instance.attempt_id,
                    instance.last_event_sequence,
                    instance.model_dump_json(),
                    instance.updated_at,
                    instance.terminal_at,
                    instance.runtime_instance_id,
                    expected_status,
                    expected_generation,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("runtime instance compare-and-set failed")
            insert_outbox(conn, outbox)


class ToolCallStore:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def create(self, record: ToolCallRecord, *, outbox: OutboxRecord) -> None:
        with self._database.transaction() as conn:
            conn.execute(
                """
                insert into tool_calls(
                  tool_call_id, runtime_instance_id, request_id, turn_id,
                  status, payload_json, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.tool_call_id,
                    record.runtime_instance_id,
                    record.request_id,
                    record.turn_id,
                    record.status,
                    record.model_dump_json(),
                    record.created_at,
                    record.updated_at,
                ),
            )
            insert_outbox(conn, outbox)

    def replace(self, record: ToolCallRecord, *, expected_status: str, outbox: OutboxRecord) -> None:
        require_transition(expected_status, record.status, TOOL_CALL_TRANSITIONS, machine="tool call")
        with self._database.transaction() as conn:
            changed = conn.execute(
                """
                update tool_calls
                set status = ?, payload_json = ?, updated_at = ?
                where tool_call_id = ? and status = ?
                """,
                (
                    record.status,
                    record.model_dump_json(),
                    record.updated_at,
                    record.tool_call_id,
                    expected_status,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("tool call compare-and-set failed")
            insert_outbox(conn, outbox)


class OutboxStore:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def pending(self, *, limit: int = 100) -> list[OutboxRecord]:
        if limit < 1:
            raise ValueError("limit must be positive")
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                """
                select payload_json from runtime_outbox
                where status in ('pending', 'failed')
                  and (next_attempt_at is null or next_attempt_at <= ?)
                order by created_at, rowid limit ?
                """,
                (utc_now_text(), limit),
            ).fetchall()
        return [OutboxRecord.model_validate_json(str(row["payload_json"])) for row in rows]

    def replace(self, record: OutboxRecord, *, expected_status: str) -> None:
        with self._database.transaction() as conn:
            changed = conn.execute(
                """
                update runtime_outbox
                set status = ?, payload_json = ?, publish_attempts = ?,
                    next_attempt_at = ?, published_at = ?, error_code = ?, updated_at = ?
                where outbox_id = ? and status = ?
                """,
                (
                    record.status,
                    record.model_dump_json(),
                    record.publish_attempts,
                    record.next_attempt_at,
                    record.published_at,
                    record.error_code,
                    record.updated_at,
                    record.outbox_id,
                    expected_status,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("outbox compare-and-set failed")

    def claim_next(self) -> OutboxRecord | None:
        now = utc_now_text()
        with self._database.transaction() as conn:
            row = conn.execute(
                """
                select payload_json from runtime_outbox
                where status in ('pending', 'failed')
                  and (next_attempt_at is null or next_attempt_at <= ?)
                order by created_at, rowid limit 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                return None
            current = OutboxRecord.model_validate_json(str(row["payload_json"]))
            claimed = current.model_copy(
                update={
                    "status": "publishing",
                    "publish_attempts": current.publish_attempts + 1,
                    "next_attempt_at": None,
                    "error_code": None,
                    "updated_at": now,
                }
            )
            changed = conn.execute(
                """
                update runtime_outbox
                set status = 'publishing', payload_json = ?, publish_attempts = ?,
                    next_attempt_at = null, error_code = null, updated_at = ?
                where outbox_id = ? and status = ? and publish_attempts = ?
                """,
                (
                    claimed.model_dump_json(),
                    claimed.publish_attempts,
                    claimed.updated_at,
                    claimed.outbox_id,
                    current.status,
                    current.publish_attempts,
                ),
            ).rowcount
            if changed != 1:
                return None
        return claimed

    def recover_publishing(self, *, error_code: str, retry_at: str) -> int:
        code = _required_text(error_code, "error_code")
        when = _required_text(retry_at, "retry_at")
        recovered = 0
        with self._database.transaction() as conn:
            rows = conn.execute(
                "select payload_json from runtime_outbox where status = 'publishing'"
            ).fetchall()
            for row in rows:
                current = OutboxRecord.model_validate_json(str(row["payload_json"]))
                updated = current.model_copy(
                    update={
                        "status": "failed",
                        "next_attempt_at": when,
                        "error_code": code,
                        "updated_at": utc_now_text(),
                    }
                )
                changed = conn.execute(
                    """
                    update runtime_outbox
                    set status = 'failed', payload_json = ?, next_attempt_at = ?,
                        error_code = ?, updated_at = ?
                    where outbox_id = ? and status = 'publishing'
                    """,
                    (
                        updated.model_dump_json(),
                        updated.next_attempt_at,
                        updated.error_code,
                        updated.updated_at,
                        updated.outbox_id,
                    ),
                ).rowcount
                recovered += changed
        return recovered


class RuntimeEventStore:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def after(self, *, stream_id: str, sequence: int = 0, limit: int = 500) -> list[RuntimeEvent]:
        if sequence < 0:
            raise ValueError("runtime event sequence cannot be negative")
        if limit < 1:
            raise ValueError("runtime event limit must be positive")
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                """
                select payload_json from runtime_events
                where stream_id = ? and sequence > ?
                order by sequence limit ?
                """,
                (_required_text(stream_id, "stream_id"), sequence, limit),
            ).fetchall()
        return [RuntimeEvent.model_validate_json(str(row["payload_json"])) for row in rows]

    def for_session(self, session_id: str, *, limit: int = 1000) -> list[RuntimeEvent]:
        if limit < 1:
            raise ValueError("runtime event limit must be positive")
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                """
                select payload_json from runtime_events
                where session_id = ? order by session_sequence limit ?
                """,
                (_required_text(session_id, "session_id"), limit),
            ).fetchall()
        return [RuntimeEvent.model_validate_json(str(row["payload_json"])) for row in rows]

    def after_event_id_for_session(
        self,
        *,
        session_id: str,
        after_event_id: str | None,
        limit: int = 1000,
    ) -> list[RuntimeEvent]:
        if limit < 1:
            raise ValueError("runtime event limit must be positive")
        cursor = self.session_sequence_for_event(
            session_id=session_id,
            event_id=after_event_id,
        )
        return self.after_session_sequence(
            session_id=session_id,
            session_sequence=cursor,
            limit=limit,
        )

    def session_sequence_for_event(
        self,
        *,
        session_id: str,
        event_id: str | None,
    ) -> int:
        session = _required_text(session_id, "session_id")
        if event_id is None:
            return 0
        value = _required_text(event_id, "event_id")
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                "select session_id, session_sequence from runtime_events where event_id = ?",
                (value,),
            ).fetchone()
        if row is None or str(row["session_id"]) != session:
            raise LookupError("runtime event cursor is unknown for this session")
        return int(row["session_sequence"])

    def latest_session_sequence(self, session_id: str) -> int:
        session = _required_text(session_id, "session_id")
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                "select coalesce(max(session_sequence), 0) from runtime_events where session_id = ?",
                (session,),
            ).fetchone()
        return int(row[0])

    def after_session_sequence(
        self,
        *,
        session_id: str,
        session_sequence: int,
        limit: int = 1000,
    ) -> list[RuntimeEvent]:
        if session_sequence < 0:
            raise ValueError("runtime session event sequence cannot be negative")
        if limit < 1:
            raise ValueError("runtime event limit must be positive")
        session = _required_text(session_id, "session_id")
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                """
                select payload_json from runtime_events
                where session_id = ? and session_sequence > ?
                order by session_sequence limit ?
                """,
                (session, session_sequence, limit),
            ).fetchall()
        return [RuntimeEvent.model_validate_json(str(row["payload_json"])) for row in rows]


def _insert_send_message_intake(conn: Any, envelope: CommandEnvelope) -> None:
    payload = envelope.payload
    if not isinstance(payload, SendMessagePayload):
        raise TypeError("send-message intake requires SendMessagePayload")
    conversation = conn.execute(
        """
        select principal_id, status from conversations where session_id = ?
        """,
        (envelope.session_id,),
    ).fetchone()
    if conversation is None or str(conversation["status"]) != "active":
        raise LookupError(f"active conversation not found: {envelope.session_id}")
    if str(conversation["principal_id"]) != envelope.principal_id:
        raise PermissionError("command principal does not own the conversation")
    existing_message = conn.execute(
        "select 1 from conversation_messages where message_id = ?",
        (payload.message_id,),
    ).fetchone()
    if existing_message is not None:
        raise ValueError(f"message_id is already committed: {payload.message_id}")

    task_revision = int(
        conn.execute(
            """
            select coalesce(max(task_revision), 0) + 1
            from conversation_turns where session_id = ?
            """,
            (envelope.session_id,),
        ).fetchone()[0]
    )
    now = utc_now_text()
    turn = ConversationTurn(
        turn_id=uuid4().hex,
        session_id=envelope.session_id,
        user_message_id=payload.message_id,
        task_revision=task_revision,
        status="queued",
        source_command_id=envelope.command_id,
        created_at=now,
        updated_at=now,
    )
    message = ConversationMessage(
        message_id=payload.message_id,
        session_id=envelope.session_id,
        turn_id=turn.turn_id,
        role="user",
        status="committed",
        parts=(
            TextPart(text=payload.content),
            *(AttachmentPart(attachment=attachment) for attachment in payload.attachments),
        ),
        created_at=envelope.submitted_at,
        committed_at=now,
        visibility=payload.visibility,
        notification_event_ids=payload.notification_event_ids,
    )
    insert_turn(conn, turn)
    insert_message(conn, message)
    if payload.visibility == "public":
        prior_public_user_messages = int(
            conn.execute(
                """
                select count(*) from conversation_messages
                where session_id = ? and role = 'user'
                  and json_extract(payload_json, '$.visibility') = 'public'
                  and message_id <> ?
                """,
                (envelope.session_id, payload.message_id),
            ).fetchone()[0]
        )
        if prior_public_user_messages == 0:
            conn.execute(
                "update conversations set title = ? where session_id = ?",
                (_conversation_title(payload.content), envelope.session_id),
            )
    insert_outbox(
        conn,
        OutboxRecord(
            aggregate_kind="conversation",
            aggregate_id=envelope.session_id,
            aggregate_revision=task_revision,
            event_id=f"conversation:{envelope.session_id}:turn:{turn.turn_id}:committed",
            event_kind="conversation_user_message_committed",
            payload={
                "session_id": envelope.session_id,
                "turn_id": turn.turn_id,
                "message_id": message.message_id,
                "command_id": envelope.command_id,
                "task_revision": task_revision,
            },
            created_at=now,
            updated_at=now,
        ),
    )
    advance_conversation_revision(conn, envelope.session_id, updated_at=now)


def _conversation_title(content: str) -> str:
    return " ".join(_required_text(content, "content").split())


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text
