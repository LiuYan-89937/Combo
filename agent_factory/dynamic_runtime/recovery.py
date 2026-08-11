from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from agent_factory.dynamic_runtime.database import DynamicRuntimeDatabase
from agent_factory.dynamic_runtime.event_persistence import (
    insert_runtime_event_and_outbox,
    next_session_event_sequence,
    runtime_event_for_instance,
)
from agent_factory.dynamic_runtime.persistence_helpers import (
    advance_conversation_revision,
    insert_message,
    insert_outbox,
)
from agent_factory.dynamic_runtime.repositories import utc_now_text
from agent_factory.runtime_protocol import (
    ApplicationGeneration,
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
    stale_generations: int = 0
    adopted_waiting_runtimes: int = 0
    cancelled_incomplete_runtimes: int = 0
    finalized_commands: int = 0
    rejected_unattached_commands: int = 0


class RuntimeRecoveryService:
    """Reconcile durable state left by expired application generations."""

    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def reconcile(self, *, current_generation: int) -> RuntimeRecoveryReport:
        if current_generation < 1:
            raise ValueError("current_generation must be positive")
        now = utc_now_text()
        counts = {
            "stale_generations": 0,
            "adopted_waiting_runtimes": 0,
            "cancelled_incomplete_runtimes": 0,
            "finalized_commands": 0,
            "rejected_unattached_commands": 0,
        }
        with self._database.transaction() as conn:
            stale_generations = _stale_generation_numbers(
                conn,
                current_generation=current_generation,
                now=now,
            )
            for generation in stale_generations:
                _mark_generation_crashed(conn, generation=generation, now=now)
                counts["stale_generations"] += 1

            rows = conn.execute(
                """
                select payload_json from runtime_instances
                where generation < ?
                  and status in ('queued','running','waiting_approval','waiting_external','cancelling')
                order by created_at, runtime_instance_id
                """,
                (current_generation,),
            ).fetchall()
            for row in rows:
                instance = RuntimeInstance.model_validate_json(str(row["payload_json"]))
                if instance.generation not in stale_generations:
                    raise RuntimeError(
                        "cannot recover a runtime whose application generation is still live"
                    )
                if instance.status in {"waiting_approval", "waiting_external"}:
                    _adopt_waiting_runtime(
                        conn,
                        instance=instance,
                        current_generation=current_generation,
                        now=now,
                    )
                    counts["adopted_waiting_runtimes"] += 1
                    continue
                _cancel_incomplete_runtime(conn, instance=instance, now=now)
                counts["cancelled_incomplete_runtimes"] += 1

            command_rows = conn.execute(
                """
                select receipt_json from command_inbox
                where status = 'running'
                  and (claimed_generation is null or claimed_generation <> ?)
                order by queue_sequence
                """,
                (current_generation,),
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


def _stale_generation_numbers(conn, *, current_generation: int, now: str) -> set[int]:
    rows = conn.execute(
        """
        select generation from application_generations
        where generation < ?
          and (
            status in ('closed','crashed')
            or (status in ('starting','active','quiescing') and lease_expires_at <= ?)
          )
        """,
        (current_generation, now),
    ).fetchall()
    return {int(row["generation"]) for row in rows}


def _mark_generation_crashed(conn, *, generation: int, now: str) -> None:
    row = conn.execute(
        "select status, payload_json from application_generations where generation = ?",
        (generation,),
    ).fetchone()
    if row is None or str(row["status"]) in {"closed", "crashed"}:
        return
    current = ApplicationGeneration.model_validate_json(str(row["payload_json"]))
    crashed = current.model_copy(
        update={"status": "crashed", "updated_at": now, "closed_at": now}
    )
    changed = conn.execute(
        """
        update application_generations
        set status = 'crashed', payload_json = ?, updated_at = ?, closed_at = ?
        where generation = ? and status = ? and lease_expires_at <= ?
        """,
        (crashed.model_dump_json(), now, now, generation, current.status, now),
    ).rowcount
    if changed != 1:
        raise RuntimeError("stale application generation recovery compare-and-set failed")


def _adopt_waiting_runtime(
    conn,
    *,
    instance: RuntimeInstance,
    current_generation: int,
    now: str,
) -> None:
    adopted = instance.model_copy(
        update={
            "generation": current_generation,
            "last_event_sequence": instance.last_event_sequence + 1,
            "updated_at": now,
        }
    )
    changed = conn.execute(
        """
        update runtime_instances
        set generation = ?, last_event_sequence = ?, payload_json = ?, updated_at = ?
        where runtime_instance_id = ? and generation = ? and status = ?
        """,
        (
            current_generation,
            adopted.last_event_sequence,
            adopted.model_dump_json(),
            now,
            instance.runtime_instance_id,
            instance.generation,
            instance.status,
        ),
    ).rowcount
    if changed != 1:
        raise RuntimeError("waiting runtime recovery compare-and-set failed")
    event = runtime_event_for_instance(
        adopted,
        payload={"kind": "runtime_recovered", "status": adopted.status},
        sequence=adopted.last_event_sequence,
        session_sequence=next_session_event_sequence(conn, instance.request.session_id),
        created_at=now,
    )
    insert_runtime_event_and_outbox(conn, event)
    advance_conversation_revision(conn, instance.request.session_id, updated_at=now)


def _cancel_incomplete_runtime(conn, *, instance: RuntimeInstance, now: str) -> None:
    error = RuntimeErrorEnvelope(
        code="application_generation_replaced",
        category="cancelled",
        terminal_status="cancelled",
        retryable=True,
        user_message_key="runtime.cancelled.application_restarted",
        request_id=instance.request.request_id,
        runtime_instance_id=instance.runtime_instance_id,
        operation=instance.request.policy_snapshot.model.operation,
        details={"replaced_generation": instance.generation},
    )
    cancelled = instance.model_copy(
        update={
            "status": "cancelled",
            "last_event_sequence": instance.last_event_sequence + 1,
            "updated_at": now,
            "terminal_at": now,
            "error": error,
            "cancel_requested_at": now,
            "cancel_reason": "application_generation_replaced",
        }
    )
    changed = conn.execute(
        """
        update runtime_instances
        set status = 'cancelled', last_event_sequence = ?, payload_json = ?,
            updated_at = ?, terminal_at = ?, cancel_requested_at = ?
        where runtime_instance_id = ? and generation = ? and status = ?
        """,
        (
            cancelled.last_event_sequence,
            cancelled.model_dump_json(),
            now,
            now,
            now,
            instance.runtime_instance_id,
            instance.generation,
            instance.status,
        ),
    ).rowcount
    if changed != 1:
        raise RuntimeError("incomplete runtime recovery compare-and-set failed")
    _cancel_turn(conn, instance=cancelled, now=now)
    _cancel_tool_calls(conn, instance=cancelled, now=now)
    event = runtime_event_for_instance(
        cancelled,
        payload={"kind": "cancelled", "error": error.model_dump(mode="json")},
        sequence=cancelled.last_event_sequence,
        session_sequence=next_session_event_sequence(conn, instance.request.session_id),
        created_at=now,
    )
    insert_runtime_event_and_outbox(conn, event)
    advance_conversation_revision(conn, instance.request.session_id, updated_at=now)


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


def _cancel_tool_calls(conn, *, instance: RuntimeInstance, now: str) -> None:
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
                "error_code": "application_generation_replaced",
                "updated_at": now,
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
                        error_code="application_generation_replaced",
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
