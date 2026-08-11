from __future__ import annotations

from datetime import UTC, datetime
from dataclasses import dataclass
from typing import Any, Literal

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
    CommandEnvelope,
    CommandReceipt,
    ConversationMessage,
    ConversationTurn,
    OutboxRecord,
    RuntimeInstance,
    RuntimeEvent,
    ToolCallRecord,
)
from agent_factory.runtime_protocol.state_machines import (
    COMMAND_TRANSITIONS,
    RUNTIME_INSTANCE_TRANSITIONS,
    TOOL_CALL_TRANSITIONS,
    require_transition,
)


def utc_now_text() -> str:
    return datetime.now(UTC).isoformat()


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
    ) -> None:
        now = utc_now_text()
        with self._database.transaction() as conn:
            conn.execute(
                """
                insert into workspaces(
                  workspace_id, principal_id, kind, managed_path, mount_record_id,
                  revision, status, created_at, updated_at
                ) values (?, ?, 'managed', ?, null, 1, 'active', ?, ?)
                """,
                (
                    _required_text(workspace_id, "workspace_id"),
                    _required_text(principal_id, "principal_id"),
                    _required_text(managed_path, "managed_path"),
                    now,
                    now,
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

    def create_conversation(
        self,
        *,
        session_id: str,
        principal_id: str,
        workspace_id: str,
        title: str,
    ) -> None:
        now = utc_now_text()
        with self._database.transaction() as conn:
            conn.execute(
                """
                insert into conversations(
                  session_id, principal_id, workspace_id, title, revision,
                  status, created_at, updated_at
                ) values (?, ?, ?, ?, 1, 'active', ?, ?)
                """,
                (
                    _required_text(session_id, "session_id"),
                    _required_text(principal_id, "principal_id"),
                    _required_text(workspace_id, "workspace_id"),
                    _required_text(title, "title"),
                    now,
                    now,
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
                where principal_id = ?
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
                       revision, status
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
        )

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
            insert_outbox(
                conn,
                OutboxRecord(
                    aggregate_kind="command",
                    aggregate_id=queued.command_id,
                    aggregate_revision=queued.receipt_revision,
                    event_id=f"command:{queued.command_id}:{queued.receipt_revision}",
                    event_kind="command_queued",
                    payload=queued.model_dump(mode="json"),
                    created_at=queued.updated_at,
                    updated_at=queued.updated_at,
                ),
            )
        return queued

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
            lane_filter = (
                "queued.command_kind = 'cancel_runtime_request'"
                if lane == "control"
                else "queued.command_kind <> 'cancel_runtime_request'"
            )
            row = conn.execute(
                f"""
                select * from command_inbox queued
                where queued.status = 'queued'
                  and {lane_filter}
                  and (
                    queued.command_kind = 'cancel_runtime_request'
                    or not exists (
                      select 1 from command_inbox active
                      where active.session_id = queued.session_id and active.status = 'running'
                    )
                  )
                order by
                  queued.queue_sequence
                limit 1
                """
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


def _required_text(value: Any, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text
