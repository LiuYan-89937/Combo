from __future__ import annotations

import sqlite3

from agent_factory.runtime_protocol import ConversationMessage, ConversationTurn, OutboxRecord


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
