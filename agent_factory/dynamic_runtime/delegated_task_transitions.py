from __future__ import annotations

from typing import Any

from agent_factory.dynamic_runtime.persistence_helpers import insert_outbox
from agent_factory.runtime_protocol import DelegatedTaskEvent, OutboxRecord, RuntimeInstance, TaskEnvelope
from agent_factory.runtime_protocol.events import RuntimeEventPayload


def commit_delegated_task_transition(
    conn: Any,
    *,
    instance: RuntimeInstance,
    status: str,
    event_payload: RuntimeEventPayload | dict[str, Any],
    now: str,
    terminal_at: str | None,
    expected_task_status: str,
) -> DelegatedTaskEvent:
    request = instance.request
    if request.task_id is None or request.delegation_grant_id is None:
        raise RuntimeError("temporary runtime transition is missing delegated task authority")
    task_status = "waiting" if status in {"waiting_approval", "waiting_external"} else status
    changed = conn.execute(
        """
        update delegated_task_revisions
        set status = ?, claim_id = null, claimed_generation = null,
            claim_expires_at = null, updated_at = ?, terminal_at = ?
        where task_id = ? and task_revision = ? and delegation_grant_id = ?
          and child_runtime_instance_id = ? and status = ?
        """,
        (
            task_status,
            now,
            terminal_at,
            request.task_id,
            request.task_revision,
            request.delegation_grant_id,
            instance.runtime_instance_id,
            expected_task_status,
        ),
    ).rowcount
    if changed != 1:
        raise RuntimeError("delegated task transition compare-and-set failed")
    sequence = int(
        conn.execute(
            """
            select coalesce(max(sequence), 0) + 1 from delegated_task_events
            where task_id = ? and task_revision = ?
            """,
            (request.task_id, request.task_revision),
        ).fetchone()[0]
    )
    event_type = {
        "waiting_approval": "approval_required",
        "waiting_external": "question",
        "completed": "result",
        "failed": "failed",
        "cancelled": "cancelled",
    }[status]
    payload = (
        event_payload.model_dump(mode="json")
        if hasattr(event_payload, "model_dump")
        else dict(event_payload)
    )
    task = _task_envelope(conn, request.task_id, request.task_revision)
    payload["agent_name"] = task.agent_name
    payload["objective"] = task.objective
    if event_type == "cancelled":
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        details = error.get("details") if isinstance(error.get("details"), dict) else {}
        payload["cancel_source"] = (
            "user"
            if str(details.get("reason") or "") == "user_cancelled"
            else "runtime"
        )
    payload["session_id"] = request.session_id
    attempt_id = str(instance.attempt_id or instance.cancel_command_id or "").strip()
    if not attempt_id:
        raise RuntimeError("temporary runtime transition has no execution or cancellation attempt identity")
    event = DelegatedTaskEvent(
        event_id=f"delegated_task_event:{request.task_id}:{request.task_revision}:{sequence}",
        task_id=request.task_id,
        task_revision=request.task_revision,
        parent_task_revision=_parent_task_revision(conn, request.parent_runtime_instance_id or ""),
        sequence=sequence,
        event_type=event_type,
        principal_id=request.principal_id,
        parent_runtime_instance_id=request.parent_runtime_instance_id or "",
        child_runtime_instance_id=instance.runtime_instance_id,
        child_attempt_id=attempt_id,
        payload=payload,
        created_at=now,
    )
    conn.execute(
        """
        insert into delegated_task_events(
          event_id, task_id, task_revision, sequence, event_type,
          principal_id, parent_runtime_instance_id, child_runtime_instance_id,
          child_attempt_id, payload_json, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.event_id,
            event.task_id,
            event.task_revision,
            event.sequence,
            event.event_type,
            event.principal_id,
            event.parent_runtime_instance_id,
            event.child_runtime_instance_id,
            event.child_attempt_id,
            event.model_dump_json(),
            event.created_at,
        ),
    )
    insert_outbox(
        conn,
        OutboxRecord(
            aggregate_kind="delegated_task",
            aggregate_id=event.task_id,
            aggregate_revision=event.task_revision,
            event_id=event.event_id,
            event_kind=f"delegated_task_{event.event_type}",
            payload=event.model_dump(mode="json"),
            created_at=now,
            updated_at=now,
        ),
    )
    if event.event_type in {"result", "failed", "cancelled"}:
        conn.execute(
            """
            insert into delegated_task_notifications(
              event_id, task_id, task_revision, principal_id, session_id,
              payload_json, delivered_runtime_instance_id, created_at, delivered_at
            ) values (?, ?, ?, ?, ?, ?, null, ?, null)
            """,
            (
                event.event_id,
                event.task_id,
                event.task_revision,
                event.principal_id,
                request.session_id,
                event.model_dump_json(),
                event.created_at,
            ),
        )
    return event


def _task_envelope(conn: Any, task_id: str, task_revision: int) -> TaskEnvelope:
    row = conn.execute(
        "select payload_json from delegated_task_revisions where task_id = ? and task_revision = ?",
        (task_id, task_revision),
    ).fetchone()
    if row is None:
        raise LookupError("delegated task envelope not found during transition")
    return TaskEnvelope.model_validate_json(str(row["payload_json"]))


def _parent_task_revision(conn: Any, runtime_instance_id: str) -> int:
    row = conn.execute(
        "select payload_json from runtime_instances where runtime_instance_id = ?",
        (runtime_instance_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"runtime instance not found: {runtime_instance_id}")
    return RuntimeInstance.model_validate_json(str(row["payload_json"])).request.task_revision
