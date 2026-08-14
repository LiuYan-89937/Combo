from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.dynamic_runtime.event_persistence import (
    insert_runtime_event_and_outbox,
    next_session_event_sequence,
    runtime_event_for_instance,
)
from combo.dynamic_runtime.persistence_helpers import (
    advance_conversation_revision,
    insert_message,
    insert_outbox,
)
from combo.dynamic_runtime.repositories import utc_now_text
from combo.runtime_protocol import (
    CommandReceipt,
    ConversationMessage,
    ConversationTurn,
    OutboxRecord,
    RuntimeErrorEnvelope,
    RuntimeInstance,
    ToolCallRecord,
    ToolResultPart,
)


@dataclass(frozen=True, slots=True)
class RuntimeRecoveryReport:
    restored_waiting_runtimes: int = 0
    cancelled_incomplete_runtimes: int = 0
    finalized_commands: int = 0
    rejected_unattached_commands: int = 0


class RuntimeRecoveryService:
    """Reconcile durable state left by an interrupted desktop process."""

    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def reconcile(self) -> RuntimeRecoveryReport:
        now = utc_now_text()
        counts = {
            "restored_waiting_runtimes": 0,
            "cancelled_incomplete_runtimes": 0,
            "finalized_commands": 0,
            "rejected_unattached_commands": 0,
        }
        with self._database.transaction() as conn:
            rows = conn.execute(
                """
                select payload_json from runtime_instances
                where status in ('queued','running','waiting_approval','waiting_external','cancelling')
                order by created_at, runtime_instance_id
                """
            ).fetchall()
            for row in rows:
                instance = RuntimeInstance.model_validate_json(str(row["payload_json"]))
                if not _conversation_is_active(conn, instance.request.session_id):
                    _cancel_runtime_for_inactive_conversation(conn, instance=instance, now=now)
                    counts["cancelled_incomplete_runtimes"] += 1
                    continue
                if instance.status in {"waiting_approval", "waiting_external"}:
                    _restore_waiting_runtime(
                        conn,
                        instance=instance,
                        now=now,
                    )
                    counts["restored_waiting_runtimes"] += 1
                    continue
                _cancel_incomplete_runtime(conn, instance=instance, now=now)
                counts["cancelled_incomplete_runtimes"] += 1

            command_rows = conn.execute(
                """
                select receipt_json from command_inbox
                where status = 'running'
                order by queue_sequence
                """
            ).fetchall()
            for row in command_rows:
                receipt = CommandReceipt.model_validate_json(str(row["receipt_json"]))
                if receipt.runtime_instance_id is None:
                    _reject_unattached_command(conn, receipt=receipt, now=now)
                    counts["rejected_unattached_commands"] += 1
                else:
                    _finalize_attached_command(conn, receipt=receipt, now=now)
                    counts["finalized_commands"] += 1
        return RuntimeRecoveryReport(**counts)


def _restore_waiting_runtime(
    conn,
    *,
    instance: RuntimeInstance,
    now: str,
) -> None:
    restored = instance.model_copy(
        update={
            "last_event_sequence": instance.last_event_sequence + 1,
            "updated_at": now,
        }
    )
    changed = conn.execute(
        """
        update runtime_instances
        set last_event_sequence = ?, payload_json = ?, updated_at = ?
        where runtime_instance_id = ? and status = ?
        """,
        (
            restored.last_event_sequence,
            restored.model_dump_json(),
            now,
            instance.runtime_instance_id,
            instance.status,
        ),
    ).rowcount
    if changed != 1:
        raise RuntimeError("waiting runtime recovery compare-and-set failed")
    event = runtime_event_for_instance(
        restored,
        payload={"kind": "runtime_recovered", "status": restored.status},
        sequence=restored.last_event_sequence,
        session_sequence=next_session_event_sequence(conn, instance.request.session_id),
        created_at=now,
    )
    insert_runtime_event_and_outbox(conn, event)
    advance_conversation_revision(conn, instance.request.session_id, updated_at=now)


def _conversation_is_active(conn, session_id: str) -> bool:
    row = conn.execute(
        "select status from conversations where session_id = ?",
        (session_id,),
    ).fetchone()
    return row is not None and str(row["status"]) == "active"


def _cancel_runtime_for_inactive_conversation(
    conn,
    *,
    instance: RuntimeInstance,
    now: str,
) -> None:
    error = RuntimeErrorEnvelope(
        code="conversation_inactive",
        category="cancelled",
        terminal_status="cancelled",
        retryable=False,
        user_message_key="runtime.cancelled.conversation_inactive",
        request_id=instance.request.request_id,
        runtime_instance_id=instance.runtime_instance_id,
        operation=instance.request.policy_snapshot.model.operation,
        details={"conversation_status": "inactive"},
    )
    cancelled = _cancel_runtime_record(
        conn,
        instance=instance,
        error=error,
        reason="conversation_inactive",
        reserve_event_sequence=False,
        now=now,
    )
    _cancel_turn(conn, instance=cancelled, now=now)
    _cancel_tool_calls(
        conn,
        instance=cancelled,
        error_code="conversation_inactive",
        persist_results=False,
        now=now,
    )


def _cancel_incomplete_runtime(conn, *, instance: RuntimeInstance, now: str) -> None:
    error = RuntimeErrorEnvelope(
        code="application_restarted",
        category="cancelled",
        terminal_status="cancelled",
        retryable=True,
        user_message_key="runtime.cancelled.application_restarted",
        request_id=instance.request.request_id,
        runtime_instance_id=instance.runtime_instance_id,
        operation=instance.request.policy_snapshot.model.operation,
        details={},
    )
    cancelled = _cancel_runtime_record(
        conn,
        instance=instance,
        error=error,
        reason="application_restarted",
        reserve_event_sequence=True,
        now=now,
    )
    _cancel_turn(conn, instance=cancelled, now=now)
    _cancel_tool_calls(
        conn,
        instance=cancelled,
        error_code="application_restarted",
        persist_results=True,
        now=now,
    )
    event = runtime_event_for_instance(
        cancelled,
        payload={"kind": "cancelled", "error": error.model_dump(mode="json")},
        sequence=cancelled.last_event_sequence,
        session_sequence=next_session_event_sequence(conn, instance.request.session_id),
        created_at=now,
    )
    insert_runtime_event_and_outbox(conn, event)
    advance_conversation_revision(conn, instance.request.session_id, updated_at=now)


def _cancel_runtime_record(
    conn,
    *,
    instance: RuntimeInstance,
    error: RuntimeErrorEnvelope,
    reason: str,
    reserve_event_sequence: bool,
    now: str,
) -> RuntimeInstance:
    last_event_sequence = instance.last_event_sequence + (1 if reserve_event_sequence else 0)
    cancelled = instance.model_copy(
        update={
            "status": "cancelled",
            "last_event_sequence": last_event_sequence,
            "updated_at": now,
            "terminal_at": now,
            "error": error,
            "cancel_requested_at": now,
            "cancel_reason": reason,
        }
    )
    changed = conn.execute(
        """
        update runtime_instances
        set status = 'cancelled', last_event_sequence = ?, payload_json = ?,
            updated_at = ?, terminal_at = ?, cancel_requested_at = ?
        where runtime_instance_id = ? and status = ?
        """,
        (
            cancelled.last_event_sequence,
            cancelled.model_dump_json(),
            now,
            now,
            now,
            instance.runtime_instance_id,
            instance.status,
        ),
    ).rowcount
    if changed != 1:
        raise RuntimeError("runtime recovery cancellation compare-and-set failed")
    return cancelled


def _cancel_turn(conn, *, instance: RuntimeInstance, now: str) -> None:
    row = conn.execute(
        "select payload_json from conversation_turns where turn_id = ?",
        (instance.request.turn_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"conversation turn not found: {instance.request.turn_id}")
    current = ConversationTurn.model_validate_json(str(row["payload_json"]))
    if current.status in {"completed", "failed", "cancelled"}:
        return
    cancelled = current.model_copy(
        update={"status": "cancelled", "updated_at": now, "terminal_at": now}
    )
    changed = conn.execute(
        """
        update conversation_turns
        set status = 'cancelled', payload_json = ?, updated_at = ?, terminal_at = ?
        where turn_id = ? and status = ?
        """,
        (cancelled.model_dump_json(), now, now, current.turn_id, current.status),
    ).rowcount
    if changed != 1:
        raise RuntimeError("conversation turn recovery compare-and-set failed")


def _cancel_tool_calls(
    conn,
    *,
    instance: RuntimeInstance,
    error_code: str,
    persist_results: bool,
    now: str,
) -> None:
    rows = conn.execute(
        """
        select payload_json from tool_calls
        where runtime_instance_id = ?
          and status in ('proposed','waiting_approval','running')
        """,
        (instance.runtime_instance_id,),
    ).fetchall()
    for row in rows:
        current = ToolCallRecord.model_validate_json(str(row["payload_json"]))
        cancelled = current.model_copy(
            update={
                "status": "cancelled",
                "error_code": error_code,
                "updated_at": now,
                "completed_at": now,
            }
        )
        changed = conn.execute(
            """
            update tool_calls set status = 'cancelled', payload_json = ?, updated_at = ?
            where tool_call_id = ? and status = ?
            """,
            (cancelled.model_dump_json(), now, current.tool_call_id, current.status),
        ).rowcount
        if changed != 1:
            raise RuntimeError("tool call recovery compare-and-set failed")
        if not persist_results:
            continue
        insert_message(
            conn,
            ConversationMessage(
                message_id=uuid4().hex,
                session_id=instance.request.session_id,
                turn_id=instance.request.turn_id,
                role="tool",
                status="committed",
                parts=(
                    ToolResultPart(
                        tool_call_id=current.tool_call_id,
                        status="cancelled",
                        error_code=error_code,
                    ),
                ),
                source_runtime_instance_id=instance.runtime_instance_id,
                source_request_id=instance.request.request_id,
                source_task_revision=instance.request.task_revision,
                created_at=now,
                committed_at=now,
            ),
        )


def _reject_unattached_command(conn, *, receipt: CommandReceipt, now: str) -> None:
    row = conn.execute(
        """
        select payload_json from conversation_turns
        where json_extract(payload_json, '$.source_command_id') = ?
        """,
        (receipt.command_id,),
    ).fetchone()
    if row is not None:
        turn = ConversationTurn.model_validate_json(str(row["payload_json"]))
        if turn.status == "queued":
            failed_turn = turn.model_copy(
                update={"status": "failed", "updated_at": now, "terminal_at": now}
            )
            changed = conn.execute(
                """
                update conversation_turns
                set status = 'failed', payload_json = ?, updated_at = ?, terminal_at = ?
                where turn_id = ? and status = 'queued'
                """,
                (failed_turn.model_dump_json(), now, now, turn.turn_id),
            ).rowcount
            if changed != 1:
                raise RuntimeError("pre-runtime turn recovery compare-and-set failed")
            advance_conversation_revision(conn, turn.session_id, updated_at=now)
    terminal = receipt.model_copy(
        update={
            "status": "rejected",
            "receipt_revision": receipt.receipt_revision + 1,
            "rejection_code": "application_restarted_before_runtime_start",
            "updated_at": now,
            "terminal_at": now,
        }
    )
    _replace_command_receipt(conn, current=receipt, terminal=terminal)


def _finalize_attached_command(conn, *, receipt: CommandReceipt, now: str) -> None:
    row = conn.execute(
        "select payload_json from runtime_instances where runtime_instance_id = ?",
        (receipt.runtime_instance_id,),
    ).fetchone()
    if row is None:
        raise LookupError(
            f"attached runtime instance not found during recovery: {receipt.runtime_instance_id}"
        )
    instance = RuntimeInstance.model_validate_json(str(row["payload_json"]))
    if instance.status in {"completed", "waiting_approval", "waiting_external"}:
        status = "completed"
        error = None
    elif instance.status in {"failed", "cancelled"}:
        status = instance.status
        error = instance.error
    else:
        raise RuntimeError("recovered command still references a nonterminal runtime")
    terminal = receipt.model_copy(
        update={
            "status": status,
            "receipt_revision": receipt.receipt_revision + 1,
            "request_id": instance.request.request_id,
            "runtime_instance_id": instance.runtime_instance_id,
            "error": error,
            "updated_at": now,
            "terminal_at": now,
        }
    )
    _replace_command_receipt(conn, current=receipt, terminal=terminal)


def _replace_command_receipt(
    conn,
    *,
    current: CommandReceipt,
    terminal: CommandReceipt,
) -> None:
    changed = conn.execute(
        """
        update command_inbox
        set status = ?, receipt_revision = ?, receipt_json = ?,
            updated_at = ?, terminal_at = ?
        where command_id = ? and status = 'running' and receipt_revision = ?
        """,
        (
            terminal.status,
            terminal.receipt_revision,
            terminal.model_dump_json(),
            terminal.updated_at,
            terminal.terminal_at,
            terminal.command_id,
            current.receipt_revision,
        ),
    ).rowcount
    if changed != 1:
        raise RuntimeError("command recovery compare-and-set failed")
    insert_outbox(
        conn,
        OutboxRecord(
            aggregate_kind="command",
            aggregate_id=terminal.command_id,
            aggregate_revision=terminal.receipt_revision,
            event_id=f"command:{terminal.command_id}:{terminal.receipt_revision}",
            event_kind=f"command_{terminal.status}",
            payload=terminal.model_dump(mode="json"),
            created_at=terminal.updated_at,
            updated_at=terminal.updated_at,
        ),
    )
