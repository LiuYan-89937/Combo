from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from agent_factory.dynamic_runtime.database import DynamicRuntimeDatabase
from agent_factory.dynamic_runtime.delegated_task_transitions import (
    commit_delegated_task_transition,
)
from agent_factory.dynamic_runtime.dispatcher import CommandOutcome
from agent_factory.dynamic_runtime.event_persistence import (
    insert_runtime_event_and_outbox,
    next_session_event_sequence,
    runtime_event_for_instance,
)
from agent_factory.dynamic_runtime.persistence_helpers import (
    advance_conversation_revision,
    insert_message,
)
from agent_factory.dynamic_runtime.repositories import utc_now_text
from agent_factory.dynamic_runtime.run_control import RuntimeRunControlRegistry
from agent_factory.runtime_protocol import (
    CancelRuntimeRequestPayload,
    CommandEnvelope,
    CommandReceipt,
    ConversationMessage,
    ConversationTurn,
    RuntimeErrorEnvelope,
    RuntimeInstance,
    ToolCallRecord,
    ToolResultPart,
)


@dataclass(frozen=True, slots=True)
class RuntimeCancellationResult:
    runtime_instance: RuntimeInstance
    active_execution: bool


class RuntimeCancellationStore:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def request(
        self,
        *,
        envelope: CommandEnvelope,
        payload: CancelRuntimeRequestPayload,
        generation: int,
    ) -> RuntimeCancellationResult:
        now = utc_now_text()
        with self._database.transaction() as conn:
            row = conn.execute(
                "select payload_json from runtime_instances where runtime_instance_id = ?",
                (payload.runtime_instance_id,),
            ).fetchone()
            if row is None:
                raise LookupError(f"runtime instance not found: {payload.runtime_instance_id}")
            current = RuntimeInstance.model_validate_json(str(row["payload_json"]))
            if current.request.request_id != payload.request_id:
                raise ValueError("cancel command request_id does not match runtime instance")
            if current.request.session_id != envelope.session_id:
                raise ValueError("cancel command session does not match runtime instance")
            if current.request.principal_id != envelope.principal_id:
                raise PermissionError("cancel command principal does not own runtime instance")
            if current.status in {"completed", "failed", "cancelled"}:
                return RuntimeCancellationResult(runtime_instance=current, active_execution=False)
            _require_active_generation(conn, generation, now=now)

            requested = current.model_copy(
                update={
                    "cancel_requested_at": now,
                    "cancel_reason": payload.reason,
                    "cancel_command_id": envelope.command_id,
                    "updated_at": now,
                }
            )
            if current.status == "running":
                requested = requested.model_copy(
                    update={"last_event_sequence": current.last_event_sequence + 1}
                )
                _replace_instance(conn, requested, expected_status="running")
                event = runtime_event_for_instance(
                    requested,
                    payload={"kind": "runtime_cancelling", "status": "cancelling"},
                    sequence=requested.last_event_sequence,
                    session_sequence=next_session_event_sequence(conn, current.request.session_id),
                    created_at=now,
                )
                insert_runtime_event_and_outbox(conn, event)
                advance_conversation_revision(conn, current.request.session_id, updated_at=now)
                return RuntimeCancellationResult(runtime_instance=requested, active_execution=True)

            cancelled = _cancelled_instance(requested, now=now)
            _replace_instance(conn, cancelled, expected_status=current.status)
            if cancelled.request.runtime_role == "temporary":
                commit_delegated_task_transition(
                    conn,
                    instance=cancelled,
                    status="cancelled",
                    event_payload={
                        "kind": "cancelled",
                        "error": cancelled.error.model_dump(mode="json"),
                    },
                    now=now,
                    terminal_at=now,
                    expected_task_status=(
                        "waiting"
                        if current.status in {"waiting_approval", "waiting_external"}
                        else "queued"
                    ),
                )
            else:
                _cancel_turn(conn, cancelled, now=now)
            _cancel_tool_calls(
                conn,
                cancelled,
                now=now,
                commit_conversation_result=cancelled.request.runtime_role == "main",
            )
            event = runtime_event_for_instance(
                cancelled,
                payload={"kind": "cancelled", "error": cancelled.error.model_dump(mode="json")},
                sequence=cancelled.last_event_sequence,
                session_sequence=next_session_event_sequence(conn, current.request.session_id),
                created_at=now,
            )
            insert_runtime_event_and_outbox(conn, event)
            advance_conversation_revision(conn, current.request.session_id, updated_at=now)
            return RuntimeCancellationResult(runtime_instance=cancelled, active_execution=False)


class CancelRuntimeCommandHandler:
    def __init__(
        self,
        *,
        cancellations: RuntimeCancellationStore,
        run_controls: RuntimeRunControlRegistry,
    ) -> None:
        self._cancellations = cancellations
        self._run_controls = run_controls

    async def handle(
        self,
        envelope: CommandEnvelope,
        receipt: CommandReceipt,
        *,
        generation: int,
    ) -> CommandOutcome:
        del receipt
        payload = envelope.payload
        if not isinstance(payload, CancelRuntimeRequestPayload):
            raise ValueError("cancel runtime handler received a different command kind")
        result = self._cancellations.request(
            envelope=envelope,
            payload=payload,
            generation=generation,
        )
        if result.active_execution:
            self._run_controls.request_drain(
                runtime_instance_id=payload.runtime_instance_id,
                reason=payload.reason,
            )
        return CommandOutcome(
            status="completed",
            request_id=payload.request_id,
            runtime_instance_id=payload.runtime_instance_id,
        )


def _cancelled_instance(instance: RuntimeInstance, *, now: str) -> RuntimeInstance:
    error = RuntimeErrorEnvelope(
        code="runtime_cancelled",
        category="cancelled",
        terminal_status="cancelled",
        retryable=False,
        user_message_key="runtime.cancelled",
        request_id=instance.request.request_id,
        runtime_instance_id=instance.runtime_instance_id,
        operation=instance.request.policy_snapshot.model.operation,
        details={"reason": instance.cancel_reason or "user_cancelled"},
    )
    return instance.model_copy(
        update={
            "status": "cancelled",
            "last_event_sequence": instance.last_event_sequence + 1,
            "updated_at": now,
            "terminal_at": now,
            "error": error,
        }
    )


def _replace_instance(conn, instance: RuntimeInstance, *, expected_status: str) -> None:
    changed = conn.execute(
        """
        update runtime_instances
        set status = ?, last_event_sequence = ?, payload_json = ?,
            updated_at = ?, terminal_at = ?, cancel_requested_at = ?, cancel_command_id = ?
        where runtime_instance_id = ? and status = ? and generation = ?
        """,
        (
            instance.status,
            instance.last_event_sequence,
            instance.model_dump_json(),
            instance.updated_at,
            instance.terminal_at,
            instance.cancel_requested_at,
            instance.cancel_command_id,
            instance.runtime_instance_id,
            expected_status,
            instance.generation,
        ),
    ).rowcount
    if changed != 1:
        raise RuntimeError("runtime cancellation compare-and-set failed")


def _cancel_turn(conn, instance: RuntimeInstance, *, now: str) -> None:
    row = conn.execute(
        "select payload_json from conversation_turns where turn_id = ?",
        (instance.request.turn_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"conversation turn not found: {instance.request.turn_id}")
    current = ConversationTurn.model_validate_json(str(row["payload_json"]))
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
        raise RuntimeError("conversation turn cancellation compare-and-set failed")


def _cancel_tool_calls(
    conn,
    instance: RuntimeInstance,
    *,
    now: str,
    commit_conversation_result: bool,
) -> None:
    rows = conn.execute(
        """
        select payload_json from tool_calls
        where runtime_instance_id = ? and status in ('proposed', 'waiting_approval', 'running')
        """,
        (instance.runtime_instance_id,),
    ).fetchall()
    for row in rows:
        current = ToolCallRecord.model_validate_json(str(row["payload_json"]))
        cancelled = current.model_copy(
            update={
                "status": "cancelled",
                "error_code": "runtime_cancelled",
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
            raise RuntimeError("tool call cancellation compare-and-set failed")
        if commit_conversation_result:
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
                            error_code="runtime_cancelled",
                        ),
                    ),
                    source_runtime_instance_id=instance.runtime_instance_id,
                    source_request_id=instance.request.request_id,
                    source_task_revision=instance.request.task_revision,
                    created_at=now,
                    committed_at=now,
                ),
            )


def _require_active_generation(conn, generation: int, *, now: str) -> None:
    row = conn.execute(
        """
        select 1 from application_generations
        where generation = ? and status = 'active' and lease_expires_at > ?
        """,
        (generation, now),
    ).fetchone()
    if row is None:
        raise RuntimeError("runtime cancellation generation is not active")
