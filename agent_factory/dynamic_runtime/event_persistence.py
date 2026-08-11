from __future__ import annotations

from typing import Any

from agent_factory.dynamic_runtime.persistence_helpers import insert_outbox
from agent_factory.runtime_protocol import OutboxRecord, RuntimeEvent, RuntimeInstance
from agent_factory.runtime_protocol.events import RuntimeEventPayload


def runtime_event_for_instance(
    instance: RuntimeInstance,
    *,
    payload: RuntimeEventPayload | dict[str, Any],
    sequence: int,
    session_sequence: int,
    created_at: str,
) -> RuntimeEvent:
    return RuntimeEvent.model_validate(
        {
            "stream_id": instance.stream_id,
            "sequence": sequence,
            "session_sequence": session_sequence,
            "runtime_instance_id": instance.runtime_instance_id,
            "request_id": instance.request.request_id,
            "session_id": instance.request.session_id,
            "turn_id": instance.request.turn_id,
            "workspace_id": instance.request.workspace_id,
            "task_revision": instance.request.task_revision,
            "runtime_role": instance.request.runtime_role,
            "task_id": instance.request.task_id,
            "attempt_id": instance.attempt_id,
            "payload": payload,
            "created_at": created_at,
        }
    )


def insert_runtime_event_and_outbox(conn: Any, event: RuntimeEvent) -> None:
    event_kind = event.payload.kind
    conn.execute(
        """
        insert into runtime_events(
          event_id, stream_id, sequence, session_sequence, runtime_instance_id, request_id,
          session_id, turn_id, event_kind, payload_json, created_at
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event.event_id,
            event.stream_id,
            event.sequence,
            event.session_sequence,
            event.runtime_instance_id,
            event.request_id,
            event.session_id,
            event.turn_id,
            event_kind,
            event.model_dump_json(),
            event.created_at,
        ),
    )
    insert_outbox(
        conn,
        OutboxRecord(
            aggregate_kind="runtime_instance",
            aggregate_id=event.runtime_instance_id,
            aggregate_revision=event.sequence,
            event_id=event.event_id,
            event_kind=event_kind,
            payload=event.model_dump(mode="json"),
            created_at=event.created_at,
            updated_at=event.created_at,
        ),
    )


def next_session_event_sequence(conn: Any, session_id: str) -> int:
    value = str(session_id or "").strip()
    if not value:
        raise ValueError("runtime event session_id must not be empty")
    row = conn.execute(
        "select coalesce(max(session_sequence), 0) + 1 from runtime_events where session_id = ?",
        (value,),
    ).fetchone()
    return int(row[0])
