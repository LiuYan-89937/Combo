from __future__ import annotations

from typing import Any, Iterable
from uuid import uuid4

from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.dynamic_runtime.delegated_task_transitions import (
    commit_delegated_task_transition,
)
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
from combo.model_pool.usage import insert_runtime_model_usage
from combo.runtime_protocol import (
    ConversationMessage,
    ConversationTurn,
    RuntimeErrorEnvelope,
    RuntimeInstance,
    RuntimeModelUsage,
    ToolCallRecord,
    OutboxRecord,
)
from combo.runtime_protocol.events import RuntimeEventPayload
from combo.runtime_protocol.state_machines import (
    CONVERSATION_TURN_TRANSITIONS,
    RUNTIME_INSTANCE_TRANSITIONS,
    TOOL_CALL_TRANSITIONS,
    require_transition,
)


class RuntimeCancellationRequested(RuntimeError):
    pass


class RuntimeExecutionCommitStore:
    """Own the atomic execution-state, conversation, event, and outbox boundary."""

    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def begin(
        self,
        runtime_instance_id: str,
        *,
        resuming: bool,
        delegation_claim_id: str | None = None,
    ) -> RuntimeInstance:
        now = utc_now_text()
        with self._database.transaction() as conn:
            instance = _load_instance(conn, runtime_instance_id)
            expected = {"waiting_approval", "waiting_external"} if resuming else {"queued"}
            if instance.status not in expected:
                raise RuntimeError(
                    f"cannot begin runtime execution in status {instance.status!r}; "
                    f"expected one of {sorted(expected)}"
                )
            if not resuming and instance.attempt_id is not None:
                raise RuntimeError("queued runtime instance cannot already have an attempt identity")
            require_transition(instance.status, "running", RUNTIME_INSTANCE_TRANSITIONS, machine="runtime instance")

            attempt_id = uuid4().hex
            sequence = instance.last_event_sequence + 1
            updated_instance = instance.model_copy(
                update={
                    "status": "running",
                    "attempt_id": attempt_id,
                    "last_event_sequence": sequence,
                    "updated_at": now,
                    "terminal_at": None,
                    "error": None,
                }
            )
            turn: ConversationTurn | None = None
            if instance.request.runtime_role == "main":
                if delegation_claim_id is not None:
                    raise ValueError("main runtime execution cannot use a delegation claim")
                turn = _load_turn(conn, instance.request.turn_id)
                if turn.session_id != instance.request.session_id:
                    raise RuntimeError("runtime instance and conversation turn sessions differ")
                require_transition(
                    turn.status,
                    "running",
                    CONVERSATION_TURN_TRANSITIONS,
                    machine="conversation turn",
                )
                updated_turn = turn.model_copy(
                    update={
                        "status": "running",
                        "active_runtime_instance_id": instance.runtime_instance_id,
                        "updated_at": now,
                        "terminal_at": None,
                    }
                )
            else:
                _begin_delegated_task(
                    conn,
                    instance=instance,
                    delegation_claim_id=delegation_claim_id,
                    resuming=resuming,
                    now=now,
                )

            _replace_instance_row(conn, updated_instance, expected_status=instance.status, expected_attempt=instance.attempt_id)
            if turn is not None:
                _replace_turn_row(conn, updated_turn, expected_status=turn.status)
            if resuming:
                _resume_waiting_tool_calls(conn, instance.runtime_instance_id, now=now)
            event = runtime_event_for_instance(
                updated_instance,
                payload={"kind": "runtime_started", "status": "running"},
                sequence=sequence,
                session_sequence=next_session_event_sequence(conn, instance.request.session_id),
                created_at=now,
            )
            insert_runtime_event_and_outbox(conn, event)
            advance_conversation_revision(conn, instance.request.session_id, updated_at=now)
        return updated_instance

    def commit(
        self,
        *,
        claimed_instance: RuntimeInstance,
        status: str,
        event_payload: RuntimeEventPayload | dict[str, Any],
        messages: Iterable[ConversationMessage] = (),
        tool_calls: Iterable[ToolCallRecord] = (),
        model_usage: Iterable[RuntimeModelUsage] = (),
        error: RuntimeErrorEnvelope | None = None,
    ) -> RuntimeInstance:
        if status not in {"waiting_approval", "waiting_external", "completed", "failed", "cancelled"}:
            raise ValueError(f"unsupported runtime execution commit status: {status}")
        now = utc_now_text()
        terminal_at = now if status in {"completed", "failed", "cancelled"} else None
        if status == "failed" and error is None:
            raise ValueError("failed runtime execution commit requires an error envelope")
        if error is not None and error.terminal_status != status:
            raise ValueError("runtime error terminal status does not match execution status")

        with self._database.transaction() as conn:
            current = _load_instance(conn, claimed_instance.runtime_instance_id)
            if current.status != "running" or current.attempt_id != claimed_instance.attempt_id:
                raise RuntimeError("runtime attempt fence rejected a late or duplicate execution result")
            if current.cancel_requested_at is not None and status != "cancelled":
                raise RuntimeCancellationRequested(
                    "runtime cancellation request won before execution commit"
                )
            require_transition(current.status, status, RUNTIME_INSTANCE_TRANSITIONS, machine="runtime instance")

            sequence = current.last_event_sequence + 1
            updated_instance = current.model_copy(
                update={
                    "status": status,
                    "last_event_sequence": sequence,
                    "updated_at": now,
                    "terminal_at": terminal_at,
                    "error": error,
                }
            )
            committed_messages = tuple(_committed_message(message, committed_at=now) for message in messages)
            turn: ConversationTurn | None = None
            if current.request.runtime_role == "main":
                turn = _load_turn(conn, current.request.turn_id)
                if turn.active_runtime_instance_id != current.runtime_instance_id:
                    raise RuntimeError("conversation turn is owned by a different runtime instance")
                require_transition(turn.status, status, CONVERSATION_TURN_TRANSITIONS, machine="conversation turn")
                updated_turn = turn.model_copy(
                    update={
                        "status": status,
                        "updated_at": now,
                        "terminal_at": terminal_at,
                    }
                )
                for message in committed_messages:
                    _validate_message_owner(message, current)
                    insert_message(conn, message)
            else:
                if committed_messages:
                    raise RuntimeError("temporary runtime cannot commit conversation messages")
                _commit_delegated_task(
                    conn,
                    instance=current,
                    status=status,
                    event_payload=event_payload,
                    now=now,
                    terminal_at=terminal_at,
                )
            for tool_call in tool_calls:
                _upsert_tool_call(conn, tool_call, current=current, now=now)
            for usage in model_usage:
                _validate_model_usage_owner(usage, current)
                insert_runtime_model_usage(conn, usage)

            _replace_instance_row(
                conn,
                updated_instance,
                expected_status=current.status,
                expected_attempt=current.attempt_id,
            )
            if turn is not None:
                _replace_turn_row(conn, updated_turn, expected_status=turn.status)
            event = runtime_event_for_instance(
                updated_instance,
                payload=event_payload,
                sequence=sequence,
                session_sequence=next_session_event_sequence(conn, current.request.session_id),
                created_at=now,
            )
            insert_runtime_event_and_outbox(conn, event)
            advance_conversation_revision(conn, current.request.session_id, updated_at=now)
        return updated_instance

    def fail_claimed(self, claimed_instance: RuntimeInstance, error: RuntimeErrorEnvelope) -> RuntimeInstance:
        return self.commit(
            claimed_instance=claimed_instance,
            status="failed",
            event_payload={"kind": "failed", "error": error.model_dump(mode="json")},
            error=error,
        )


def _begin_delegated_task(
    conn: Any,
    *,
    instance: RuntimeInstance,
    delegation_claim_id: str | None,
    resuming: bool,
    now: str,
) -> None:
    request = instance.request
    if request.task_id is None or request.delegation_grant_id is None:
        raise RuntimeError("temporary runtime is missing delegated task authority")
    row = conn.execute(
        """
        select task.status, task.claim_id, task.claim_expires_at,
               task.child_runtime_instance_id, grant.status as grant_status, grant.expires_at
        from delegated_task_revisions as task
        join delegation_grants as grant on grant.grant_id = task.delegation_grant_id
        where task.task_id = ? and task.task_revision = ?
          and task.delegation_grant_id = ?
        """,
        (request.task_id, request.task_revision, request.delegation_grant_id),
    ).fetchone()
    if row is None or str(row["child_runtime_instance_id"]) != instance.runtime_instance_id:
        raise PermissionError("temporary runtime has no matching delegated task")
    if str(row["grant_status"]) != "active" or str(row["expires_at"]) <= now:
        raise PermissionError("temporary runtime delegation grant is unavailable")
    expected_status = "waiting" if resuming else "queued"
    if str(row["status"]) != expected_status:
        raise RuntimeError("delegated task status differs from runtime execution state")
    if resuming:
        if delegation_claim_id is not None:
            raise ValueError("resumed delegated task cannot use a queue claim")
        claim_clause = "claim_id is null"
        parameters: tuple[Any, ...] = (now, request.task_id, request.task_revision)
    else:
        if not delegation_claim_id:
            raise ValueError("new temporary runtime execution requires a queue claim")
        if (
            str(row["claim_id"] or "") != delegation_claim_id
            or str(row["claim_expires_at"] or "") <= now
        ):
            raise RuntimeError("delegated task queue claim is invalid or expired")
        claim_clause = "claim_id = ? and claim_expires_at > ?"
        parameters = (
            now,
            request.task_id,
            request.task_revision,
            delegation_claim_id,
            now,
        )
    changed = conn.execute(
        f"""
        update delegated_task_revisions
        set status = 'running', claim_id = null, claim_expires_at = null,
            updated_at = ?
        where task_id = ? and task_revision = ? and status = '{expected_status}'
          and {claim_clause}
        """,
        parameters,
    ).rowcount
    if changed != 1:
        raise RuntimeError("delegated task execution claim compare-and-set failed")


def _commit_delegated_task(
    conn: Any,
    *,
    instance: RuntimeInstance,
    status: str,
    event_payload: RuntimeEventPayload | dict[str, Any],
    now: str,
    terminal_at: str | None,
) -> None:
    if instance.attempt_id is None:
        raise RuntimeError("temporary runtime commit has no execution attempt identity")
    commit_delegated_task_transition(
        conn,
        instance=instance,
        status=status,
        event_payload=event_payload,
        now=now,
        terminal_at=terminal_at,
        expected_task_status="running",
    )


def _load_instance(conn: Any, runtime_instance_id: str) -> RuntimeInstance:
    row = conn.execute(
        "select payload_json from runtime_instances where runtime_instance_id = ?",
        (str(runtime_instance_id or "").strip(),),
    ).fetchone()
    if row is None:
        raise LookupError(f"runtime instance not found: {runtime_instance_id}")
    return RuntimeInstance.model_validate_json(str(row["payload_json"]))


def _validate_model_usage_owner(usage: RuntimeModelUsage, instance: RuntimeInstance) -> None:
    request = instance.request
    if (
        usage.principal_id,
        usage.request_id,
        usage.runtime_instance_id,
        usage.attempt_id,
        usage.session_id,
        usage.turn_id,
        usage.workspace_id,
        usage.task_revision,
        usage.runtime_role,
        usage.strategy,
    ) != (
        request.principal_id,
        request.request_id,
        instance.runtime_instance_id,
        instance.attempt_id,
        request.session_id,
        request.turn_id,
        request.workspace_id,
        request.task_revision,
        request.runtime_role,
        request.strategy,
    ):
        raise RuntimeError("model usage ownership differs from the committing runtime attempt")


def _load_turn(conn: Any, turn_id: str) -> ConversationTurn:
    row = conn.execute(
        "select payload_json from conversation_turns where turn_id = ?",
        (turn_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"conversation turn not found: {turn_id}")
    return ConversationTurn.model_validate_json(str(row["payload_json"]))


def _replace_instance_row(
    conn: Any,
    instance: RuntimeInstance,
    *,
    expected_status: str,
    expected_attempt: str | None,
) -> None:
    changed = conn.execute(
        """
        update runtime_instances
        set status = ?, attempt_id = ?, last_event_sequence = ?,
            payload_json = ?, updated_at = ?, terminal_at = ?
        where runtime_instance_id = ? and status = ?
          and ((attempt_id is null and ? is null) or attempt_id = ?)
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
            expected_attempt,
            expected_attempt,
        ),
    ).rowcount
    if changed != 1:
        raise RuntimeError("runtime instance compare-and-set failed")


def _replace_turn_row(conn: Any, turn: ConversationTurn, *, expected_status: str) -> None:
    changed = conn.execute(
        """
        update conversation_turns
        set status = ?, active_runtime_instance_id = ?, payload_json = ?, updated_at = ?, terminal_at = ?
        where turn_id = ? and status = ?
        """,
        (
            turn.status,
            turn.active_runtime_instance_id,
            turn.model_dump_json(),
            turn.updated_at,
            turn.terminal_at,
            turn.turn_id,
            expected_status,
        ),
    ).rowcount
    if changed != 1:
        raise RuntimeError("conversation turn compare-and-set failed")


def _resume_waiting_tool_calls(conn: Any, runtime_instance_id: str, *, now: str) -> None:
    rows = conn.execute(
        "select payload_json from tool_calls where runtime_instance_id = ? and status = 'waiting_approval'",
        (runtime_instance_id,),
    ).fetchall()
    for row in rows:
        current = ToolCallRecord.model_validate_json(str(row["payload_json"]))
        updated = current.model_copy(update={"status": "running", "updated_at": now})
        require_transition(current.status, updated.status, TOOL_CALL_TRANSITIONS, machine="tool call")
        changed = conn.execute(
            """
            update tool_calls set status = ?, payload_json = ?, updated_at = ?
            where tool_call_id = ? and status = ?
            """,
            (updated.status, updated.model_dump_json(), now, updated.tool_call_id, current.status),
        ).rowcount
        if changed != 1:
            raise RuntimeError("tool call resume compare-and-set failed")


def _committed_message(message: ConversationMessage, *, committed_at: str) -> ConversationMessage:
    if message.status == "cancelled":
        raise ValueError("cancelled graph messages cannot be committed as runtime output")
    return message.model_copy(update={"status": "committed", "committed_at": committed_at})


def _validate_message_owner(message: ConversationMessage, instance: RuntimeInstance) -> None:
    request = instance.request
    expected = (
        request.session_id,
        request.turn_id,
        instance.runtime_instance_id,
        request.request_id,
        request.task_revision,
    )
    actual = (
        message.session_id,
        message.turn_id,
        message.source_runtime_instance_id,
        message.source_request_id,
        message.source_task_revision,
    )
    if actual != expected:
        raise ValueError("runtime output message ownership does not match the claimed instance")


def _upsert_tool_call(conn: Any, record: ToolCallRecord, *, current: RuntimeInstance, now: str) -> None:
    if (
        record.runtime_instance_id != current.runtime_instance_id
        or record.request_id != current.request.request_id
        or record.turn_id != current.request.turn_id
    ):
        raise ValueError("tool call ownership does not match runtime instance")
    row = conn.execute(
        "select payload_json from tool_calls where tool_call_id = ?",
        (record.tool_call_id,),
    ).fetchone()
    if row is None:
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
        return
    existing = ToolCallRecord.model_validate_json(str(row["payload_json"]))
    if (
        existing.runtime_instance_id,
        existing.request_id,
        existing.turn_id,
        existing.capability_id,
        existing.capability_revision,
        existing.model_alias,
        existing.arguments,
    ) != (
        record.runtime_instance_id,
        record.request_id,
        record.turn_id,
        record.capability_id,
        record.capability_revision,
        record.model_alias,
        record.arguments,
    ):
        raise RuntimeError("tool call identity was reused with different immutable content")
    if existing.status == record.status:
        return
    require_transition(existing.status, record.status, TOOL_CALL_TRANSITIONS, machine="tool call")
    updated = record.model_copy(update={"attempt_id": existing.attempt_id, "created_at": existing.created_at, "updated_at": now})
    changed = conn.execute(
        """
        update tool_calls set status = ?, payload_json = ?, updated_at = ?
        where tool_call_id = ? and status = ?
        """,
        (updated.status, updated.model_dump_json(), now, updated.tool_call_id, existing.status),
    ).rowcount
    if changed != 1:
        raise RuntimeError("tool call compare-and-set failed")
