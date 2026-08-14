from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.dynamic_runtime.event_persistence import (
    insert_runtime_event_and_outbox,
    next_session_event_sequence,
    runtime_event_for_instance,
)
from combo.dynamic_runtime.persistence_helpers import (
    advance_conversation_revision,
    insert_runtime_instance,
    insert_outbox,
    upsert_capability_snapshot,
)
from combo.dynamic_runtime.repositories import utc_now_text
from combo.runtime_protocol import (
    CapabilitySnapshot,
    CommandEnvelope,
    CommandReceipt,
    ConversationMessage,
    ConversationTurn,
    OutboxRecord,
    RuntimeInstance,
    SendMessagePayload,
)


@dataclass(frozen=True, slots=True)
class RuntimeStartResult:
    receipt: CommandReceipt
    runtime_instance: RuntimeInstance


class RuntimeStartStore:
    """Atomically attach one durable command to a queued runtime turn."""

    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def attach(
        self,
        *,
        envelope: CommandEnvelope,
        claimed_receipt: CommandReceipt,
        turn: ConversationTurn,
        user_message: ConversationMessage,
        capability_snapshot: CapabilitySnapshot,
        runtime_instance: RuntimeInstance,
    ) -> RuntimeStartResult:
        _validate_start_objects(
            envelope=envelope,
            receipt=claimed_receipt,
            turn=turn,
            user_message=user_message,
            capability_snapshot=capability_snapshot,
            runtime_instance=runtime_instance,
        )
        now = utc_now_text()
        with self._database.transaction() as conn:
            _require_conversation_owner(
                conn,
                session_id=envelope.session_id,
                principal_id=envelope.principal_id,
                workspace_id=runtime_instance.request.workspace_id,
            )
            current_receipt = _load_receipt(conn, envelope.command_id)
            if current_receipt != claimed_receipt:
                raise RuntimeError("command receipt changed before runtime creation")

            upsert_capability_snapshot(conn, capability_snapshot)
            _attach_prepared_turn(
                conn,
                envelope=envelope,
                turn=turn,
                user_message=user_message,
            )
            insert_runtime_instance(conn, runtime_instance)

            attached_receipt = claimed_receipt.model_copy(
                update={
                    "receipt_revision": claimed_receipt.receipt_revision + 1,
                    "request_id": runtime_instance.request.request_id,
                    "runtime_instance_id": runtime_instance.runtime_instance_id,
                    "updated_at": now,
                }
            )
            _attach_command_receipt(conn, attached_receipt, expected_revision=claimed_receipt.receipt_revision)
            event = runtime_event_for_instance(
                runtime_instance,
                payload={"kind": "runtime_queued", "status": "queued"},
                sequence=runtime_instance.last_event_sequence,
                session_sequence=next_session_event_sequence(conn, envelope.session_id),
                created_at=now,
            )
            insert_runtime_event_and_outbox(conn, event)
            insert_outbox(
                conn,
                OutboxRecord(
                    aggregate_kind="command",
                    aggregate_id=attached_receipt.command_id,
                    aggregate_revision=attached_receipt.receipt_revision,
                    event_id=f"command:{attached_receipt.command_id}:{attached_receipt.receipt_revision}",
                    event_kind="command_attached_runtime",
                    payload={
                        **attached_receipt.model_dump(mode="json"),
                        "command_kind": envelope.payload.kind,
                        "request_source": (
                            "internal"
                            if isinstance(envelope.payload, SendMessagePayload)
                            and envelope.payload.visibility == "internal"
                            else "user"
                        ),
                    },
                    created_at=now,
                    updated_at=now,
                ),
            )
            advance_conversation_revision(conn, envelope.session_id, updated_at=now)
        return RuntimeStartResult(receipt=attached_receipt, runtime_instance=runtime_instance)


def _validate_start_objects(
    *,
    envelope: CommandEnvelope,
    receipt: CommandReceipt,
    turn: ConversationTurn,
    user_message: ConversationMessage,
    capability_snapshot: CapabilitySnapshot,
    runtime_instance: RuntimeInstance,
) -> None:
    if envelope.payload.kind != "send_message":
        raise ValueError("runtime start requires a send_message command")
    if receipt.status != "running":
        raise ValueError("runtime start requires a claimed running command")
    if (envelope.command_id, envelope.client_instance_id, envelope.principal_id, envelope.session_id) != (
        receipt.command_id,
        receipt.client_instance_id,
        receipt.principal_id,
        receipt.session_id,
    ):
        raise ValueError("command envelope and receipt identities differ")
    request = runtime_instance.request
    if runtime_instance.status != "queued" or runtime_instance.attempt_id is not None:
        raise ValueError("new runtime instance must be queued and unclaimed")
    if runtime_instance.last_event_sequence != 1:
        raise ValueError("new runtime instance must reserve event sequence 1")
    if request.runtime_role != "main" or request.parent_runtime_instance_id is not None:
        raise ValueError("send_message runtime start only creates a main runtime")
    if (
        request.principal_id,
        request.session_id,
        request.turn_id,
        request.capability_snapshot_id,
    ) != (
        envelope.principal_id,
        envelope.session_id,
        turn.turn_id,
        capability_snapshot.snapshot_id,
    ):
        raise ValueError("runtime request ownership differs from command turn or capability snapshot")
    if turn.status != "queued" or turn.active_runtime_instance_id != runtime_instance.runtime_instance_id:
        raise ValueError("new conversation turn must be queued and owned by the runtime instance")
    if turn.user_message_id != user_message.message_id or turn.task_revision != request.task_revision:
        raise ValueError("conversation turn does not match user message or task revision")
    if turn.source_command_id != envelope.command_id:
        raise ValueError("conversation turn does not match source command")
    if user_message.role != "user" or user_message.status != "committed":
        raise ValueError("runtime start requires one committed user message")
    if user_message.session_id != envelope.session_id or user_message.turn_id != turn.turn_id:
        raise ValueError("user message ownership differs from command turn")
    if user_message.message_id != envelope.payload.message_id:
        raise ValueError("command message_id differs from canonical user message")


def _require_conversation_owner(
    conn: sqlite3.Connection,
    *,
    session_id: str,
    principal_id: str,
    workspace_id: str,
) -> None:
    row = conn.execute(
        """
        select principal_id, workspace_id, status from conversations where session_id = ?
        """,
        (session_id,),
    ).fetchone()
    if row is None or str(row["status"]) != "active":
        raise LookupError(f"active conversation not found: {session_id}")
    if str(row["principal_id"]) != principal_id or str(row["workspace_id"]) != workspace_id:
        raise RuntimeError("command principal or workspace does not own the conversation")


def _attach_prepared_turn(
    conn: sqlite3.Connection,
    *,
    envelope: CommandEnvelope,
    turn: ConversationTurn,
    user_message: ConversationMessage,
) -> None:
    turn_row = conn.execute(
        """
        select payload_json from conversation_turns where turn_id = ?
        """,
        (turn.turn_id,),
    ).fetchone()
    message_row = conn.execute(
        "select payload_json from conversation_messages where message_id = ?",
        (user_message.message_id,),
    ).fetchone()
    if turn_row is None or message_row is None:
        raise RuntimeError("runtime start requires a durably prepared conversation turn")
    prepared_turn = ConversationTurn.model_validate_json(str(turn_row["payload_json"]))
    prepared_message = ConversationMessage.model_validate_json(str(message_row["payload_json"]))
    expected_turn = turn.model_copy(
        update={
            "active_runtime_instance_id": None,
            "updated_at": prepared_turn.updated_at,
        }
    )
    if prepared_turn != expected_turn or prepared_message != user_message:
        raise RuntimeError("prepared conversation turn changed before runtime attachment")
    if prepared_turn.source_command_id != envelope.command_id:
        raise RuntimeError("prepared conversation turn belongs to a different command")
    changed = conn.execute(
        """
        update conversation_turns
        set active_runtime_instance_id = ?, payload_json = ?, updated_at = ?
        where turn_id = ? and status = 'queued' and active_runtime_instance_id is null
        """,
        (
            turn.active_runtime_instance_id,
            turn.model_dump_json(),
            turn.updated_at,
            turn.turn_id,
        ),
    ).rowcount
    if changed != 1:
        raise RuntimeError("conversation turn runtime attachment compare-and-set failed")


def _load_receipt(conn: sqlite3.Connection, command_id: str) -> CommandReceipt:
    row = conn.execute(
        "select receipt_json from command_inbox where command_id = ?",
        (command_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"command receipt not found: {command_id}")
    return CommandReceipt.model_validate_json(str(row["receipt_json"]))




def _attach_command_receipt(
    conn: sqlite3.Connection,
    receipt: CommandReceipt,
    *,
    expected_revision: int,
) -> None:
    changed = conn.execute(
        """
        update command_inbox
        set receipt_revision = ?, receipt_json = ?, updated_at = ?
        where command_id = ? and status = 'running' and receipt_revision = ?
        """,
        (
            receipt.receipt_revision,
            receipt.model_dump_json(),
            receipt.updated_at,
            receipt.command_id,
            expected_revision,
        ),
    ).rowcount
    if changed != 1:
        raise RuntimeError("command runtime attachment compare-and-set failed")
