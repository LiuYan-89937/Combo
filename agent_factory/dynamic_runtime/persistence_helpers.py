from __future__ import annotations

import sqlite3

from agent_factory.runtime_protocol import (
    CapabilitySnapshot,
    ConversationMessage,
    ConversationTurn,
    OutboxRecord,
    RuntimeInstance,
)
from agent_factory.runtime_protocol.contracts import utc_now_text


def upsert_capability_snapshot(conn: sqlite3.Connection, snapshot: CapabilitySnapshot) -> None:
    row = conn.execute(
        "select payload_json from capability_snapshots where snapshot_id = ? or content_digest = ?",
        (snapshot.snapshot_id, snapshot.content_digest),
    ).fetchone()
    if row is not None:
        existing = CapabilitySnapshot.model_validate_json(str(row["payload_json"]))
        if existing != snapshot:
            raise RuntimeError("capability snapshot identity or digest collision")
        return
    conn.execute(
        """
        insert into capability_snapshots(snapshot_id, content_digest, payload_json, created_at)
        values (?, ?, ?, ?)
        """,
        (snapshot.snapshot_id, snapshot.content_digest, snapshot.model_dump_json(), utc_now_text()),
    )


def insert_runtime_instance(conn: sqlite3.Connection, instance: RuntimeInstance) -> None:
    request = instance.request
    conn.execute(
        """
        insert into runtime_instances(
          runtime_instance_id, request_id, session_id, turn_id,
          parent_runtime_instance_id, capability_snapshot_id, generation,
          status, attempt_id, last_event_sequence, payload_json,
          created_at, updated_at, terminal_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            instance.runtime_instance_id,
            request.request_id,
            request.session_id,
            request.turn_id,
            request.parent_runtime_instance_id,
            instance.capability_snapshot_id,
            instance.generation,
            instance.status,
            instance.attempt_id,
            instance.last_event_sequence,
            instance.model_dump_json(),
            instance.created_at,
            instance.updated_at,
            instance.terminal_at,
        ),
    )


def insert_outbox(conn: sqlite3.Connection, record: OutboxRecord) -> None:
    conn.execute(
        """
        insert into runtime_outbox(
          outbox_id, aggregate_kind, aggregate_id, aggregate_revision,
          event_id, event_kind, status, payload_json, publish_attempts,
          next_attempt_at, published_at, error_code, created_at, updated_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.outbox_id,
            record.aggregate_kind,
            record.aggregate_id,
            record.aggregate_revision,
            record.event_id,
            record.event_kind,
            record.status,
            record.model_dump_json(),
            record.publish_attempts,
            record.next_attempt_at,
            record.published_at,
            record.error_code,
            record.created_at,
            record.updated_at,
        ),
    )


def insert_turn(conn: sqlite3.Connection, turn: ConversationTurn) -> None:
    conn.execute(
        """
        insert into conversation_turns(
          turn_id, session_id, user_message_id, task_revision, status,
          active_runtime_instance_id, payload_json, created_at, updated_at, terminal_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            turn.turn_id,
            turn.session_id,
            turn.user_message_id,
            turn.task_revision,
            turn.status,
            turn.active_runtime_instance_id,
            turn.model_dump_json(),
            turn.created_at,
            turn.updated_at,
            turn.terminal_at,
        ),
    )


def insert_message(conn: sqlite3.Connection, message: ConversationMessage) -> None:
    conn.execute(
        """
        insert into conversation_messages(
          message_id, session_id, turn_id, role, status,
          payload_json, created_at, committed_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            message.message_id,
            message.session_id,
            message.turn_id,
            message.role,
            message.status,
            message.model_dump_json(),
            message.created_at,
            message.committed_at,
        ),
    )


def advance_conversation_revision(conn: sqlite3.Connection, session_id: str, *, updated_at: str) -> None:
    changed = conn.execute(
        """
        update conversations set revision = revision + 1, updated_at = ?
        where session_id = ? and status = 'active'
        """,
        (updated_at, session_id),
    ).rowcount
    if changed != 1:
        raise LookupError(f"active conversation not found: {session_id}")
