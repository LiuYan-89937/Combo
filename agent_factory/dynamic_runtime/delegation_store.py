from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
from typing import Any
from uuid import uuid4

from agent_factory.dynamic_runtime.database import DynamicRuntimeDatabase
from agent_factory.dynamic_runtime.event_persistence import (
    insert_runtime_event_and_outbox,
    next_session_event_sequence,
    runtime_event_for_instance,
)
from agent_factory.dynamic_runtime.persistence_helpers import (
    insert_outbox,
    insert_runtime_instance,
    upsert_capability_snapshot,
)
from agent_factory.runtime_protocol import (
    CapabilitySnapshot,
    DelegatedTaskEvent,
    DelegationGrant,
    OutboxRecord,
    RuntimeInstance,
    TaskEnvelope,
)
from agent_factory.runtime_protocol.contracts import utc_now_text


@dataclass(frozen=True, slots=True)
class DelegatedTaskRecord:
    envelope: TaskEnvelope
    grant: DelegationGrant
    child_runtime: RuntimeInstance
    status: str


@dataclass(frozen=True, slots=True)
class DelegatedTaskClaim:
    claim_id: str
    task_id: str
    task_revision: int
    child_runtime_instance_id: str
    generation: int
    expires_at: str


class DelegationStore:
    """Atomically create one attenuated grant, task envelope, and child runtime."""

    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def create(
        self,
        *,
        envelope: TaskEnvelope,
        grant: DelegationGrant,
        capability_snapshot: CapabilitySnapshot,
        child_runtime: RuntimeInstance,
        max_parallel_children: int,
    ) -> DelegatedTaskRecord:
        if max_parallel_children < 1:
            raise ValueError("delegation parallel child limit must be positive")
        _validate_objects(
            envelope=envelope,
            grant=grant,
            capability_snapshot=capability_snapshot,
            child_runtime=child_runtime,
        )
        now = utc_now_text()
        if datetime.fromisoformat(grant.expires_at) <= datetime.now(UTC):
            raise ValueError("delegation grant is already expired")
        with self._database.transaction() as conn:
            parent_row = conn.execute(
                "select payload_json from runtime_instances where runtime_instance_id = ?",
                (grant.parent_runtime_instance_id,),
            ).fetchone()
            if parent_row is None:
                raise LookupError("delegation parent runtime does not exist")
            parent = RuntimeInstance.model_validate_json(str(parent_row["payload_json"]))
            _validate_parent(parent=parent, envelope=envelope, grant=grant, child=child_runtime)
            _validate_parent_grant_attenuation(conn, parent=parent, grant=grant)
            active_children = int(
                conn.execute(
                    """
                    select count(*) from delegated_task_revisions
                    where parent_runtime_instance_id = ? and status in ('queued','running','waiting')
                    """,
                    (grant.parent_runtime_instance_id,),
                ).fetchone()[0]
            )
            if active_children >= max_parallel_children:
                raise RuntimeError("delegation parent has reached its parallel child limit")
            generation = conn.execute(
                """
                select 1 from application_generations
                where generation = ? and status = 'active' and lease_expires_at > ?
                """,
                (child_runtime.generation, now),
            ).fetchone()
            if generation is None:
                raise RuntimeError("delegated runtime generation is not active")

            upsert_capability_snapshot(conn, capability_snapshot)
            insert_runtime_instance(conn, child_runtime)
            conn.execute(
                """
                insert into delegation_grants(
                  grant_id, principal_id, parent_runtime_instance_id,
                  child_runtime_instance_id, task_id, task_revision,
                  parent_task_revision,
                  parent_capability_snapshot_id, child_capability_snapshot_id,
                  workspace_id, status, state_revision, content_digest,
                  payload_json, expires_at, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 1, ?, ?, ?, ?, ?)
                """,
                (
                    grant.grant_id,
                    grant.principal_id,
                    grant.parent_runtime_instance_id,
                    grant.child_runtime_instance_id,
                    grant.task_id,
                    grant.task_revision,
                    grant.parent_task_revision,
                    grant.parent_capability_snapshot_id,
                    grant.child_capability_snapshot_id,
                    grant.workspace_id,
                    grant.content_digest,
                    grant.model_dump_json(),
                    grant.expires_at,
                    grant.created_at,
                    now,
                ),
            )
            conn.execute(
                """
                insert into delegated_task_revisions(
                  task_id, task_revision, principal_id, parent_runtime_instance_id,
                  parent_task_revision,
                  child_runtime_instance_id, delegation_grant_id,
                  capability_snapshot_id, workspace_id, status, payload_json,
                  created_at, updated_at, terminal_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?, null)
                """,
                (
                    envelope.task_id,
                    envelope.task_revision,
                    envelope.principal_id,
                    envelope.parent_runtime_instance_id,
                    envelope.parent_task_revision,
                    child_runtime.runtime_instance_id,
                    envelope.delegation_grant_id,
                    envelope.capability_snapshot_id,
                    envelope.workspace_id,
                    envelope.model_dump_json(),
                    envelope.created_at,
                    now,
                ),
            )
            event = runtime_event_for_instance(
                child_runtime,
                payload={
                    "kind": "runtime_queued",
                    "status": "queued",
                },
                sequence=child_runtime.last_event_sequence,
                session_sequence=next_session_event_sequence(conn, child_runtime.request.session_id),
                created_at=now,
            )
            insert_runtime_event_and_outbox(conn, event)
            insert_outbox(
                conn,
                OutboxRecord(
                    aggregate_kind="delegated_task",
                    aggregate_id=envelope.task_id,
                    aggregate_revision=envelope.task_revision,
                    event_id=f"delegated_task:{envelope.task_id}:{envelope.task_revision}:queued",
                    event_kind="delegated_task_queued",
                    payload={
                        "task": envelope.model_dump(mode="json"),
                        "session_id": child_runtime.request.session_id,
                        "status": "queued",
                        "child_runtime_instance_id": child_runtime.runtime_instance_id,
                    },
                    created_at=now,
                    updated_at=now,
                ),
            )
        return DelegatedTaskRecord(
            envelope=envelope,
            grant=grant,
            child_runtime=child_runtime,
            status="queued",
        )

    def get(self, *, principal_id: str, task_id: str, task_revision: int) -> DelegatedTaskRecord:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                """
                select task.payload_json as task_json, task.status,
                       grant.payload_json as grant_json,
                       runtime.payload_json as runtime_json
                from delegated_task_revisions as task
                join delegation_grants as grant on grant.grant_id = task.delegation_grant_id
                join runtime_instances as runtime
                  on runtime.runtime_instance_id = task.child_runtime_instance_id
                where task.principal_id = ? and task.task_id = ? and task.task_revision = ?
                """,
                (principal_id, task_id, task_revision),
            ).fetchone()
        if row is None:
            raise LookupError("delegated task not found")
        return DelegatedTaskRecord(
            envelope=TaskEnvelope.model_validate_json(str(row["task_json"])),
            grant=DelegationGrant.model_validate_json(str(row["grant_json"])),
            child_runtime=RuntimeInstance.model_validate_json(str(row["runtime_json"])),
            status=str(row["status"]),
        )

    def for_runtime(self, runtime_instance_id: str) -> DelegatedTaskRecord:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                """
                select task.payload_json as task_json, task.status,
                       grant.status as grant_status, grant.expires_at,
                       grant.payload_json as grant_json,
                       runtime.payload_json as runtime_json
                from delegated_task_revisions as task
                join delegation_grants as grant on grant.grant_id = task.delegation_grant_id
                join runtime_instances as runtime
                  on runtime.runtime_instance_id = task.child_runtime_instance_id
                where task.child_runtime_instance_id = ?
                """,
                (runtime_instance_id,),
            ).fetchone()
        if row is None:
            raise LookupError("delegated task runtime not found")
        if str(row["grant_status"]) != "active":
            raise PermissionError("delegated task grant is not active")
        if datetime.fromisoformat(str(row["expires_at"])) <= datetime.now(UTC):
            raise PermissionError("delegated task grant has expired")
        return DelegatedTaskRecord(
            envelope=TaskEnvelope.model_validate_json(str(row["task_json"])),
            grant=DelegationGrant.model_validate_json(str(row["grant_json"])),
            child_runtime=RuntimeInstance.model_validate_json(str(row["runtime_json"])),
            status=str(row["status"]),
        )

    def latest_event(
        self,
        *,
        principal_id: str,
        task_id: str,
        task_revision: int,
    ) -> DelegatedTaskEvent | None:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                """
                select payload_json from delegated_task_events
                where principal_id = ? and task_id = ? and task_revision = ?
                order by sequence desc limit 1
                """,
                (principal_id, task_id, task_revision),
            ).fetchone()
        return (
            DelegatedTaskEvent.model_validate_json(str(row["payload_json"]))
            if row is not None
            else None
        )

    def record_runtime_observation(self, instance: RuntimeInstance, chunk: Any) -> None:
        if instance.request.runtime_role != "temporary" or instance.request.task_id is None:
            return
        activities = _delegated_observation_activities(chunk)
        if not activities or instance.attempt_id is None:
            return
        now = utc_now_text()
        with self._database.transaction() as conn:
            task_row = conn.execute(
                """
                select parent_runtime_instance_id, parent_task_revision
                from delegated_task_revisions
                where task_id = ? and task_revision = ? and principal_id = ?
                """,
                (
                    instance.request.task_id,
                    instance.request.task_revision,
                    instance.request.principal_id,
                ),
            ).fetchone()
            if task_row is None:
                raise LookupError("delegated task observation owner not found")
            for activity in activities:
                source_event_id = str(activity.get("source_event_id") or uuid4().hex)
                event_id = f"delegated_task_activity:{instance.request.task_id}:{source_event_id}"
                if conn.execute(
                    "select 1 from delegated_task_events where event_id = ?",
                    (event_id,),
                ).fetchone() is not None:
                    continue
                sequence = int(conn.execute(
                    """
                    select coalesce(max(sequence), 0) + 1 from delegated_task_events
                    where task_id = ? and task_revision = ?
                    """,
                    (instance.request.task_id, instance.request.task_revision),
                ).fetchone()[0])
                event = DelegatedTaskEvent(
                    event_id=event_id,
                    task_id=instance.request.task_id,
                    task_revision=instance.request.task_revision,
                    parent_task_revision=int(task_row["parent_task_revision"]),
                    sequence=sequence,
                    event_type="progress",
                    principal_id=instance.request.principal_id,
                    parent_runtime_instance_id=str(task_row["parent_runtime_instance_id"]),
                    child_runtime_instance_id=instance.runtime_instance_id,
                    child_attempt_id=instance.attempt_id,
                    payload=activity,
                    created_at=str(activity.get("created_at") or now),
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
                        event_kind="delegated_task_progress",
                        payload=event.model_dump(mode="json"),
                        created_at=event.created_at,
                        updated_at=event.created_at,
                    ),
                )

    def list_for_parent(
        self,
        *,
        principal_id: str,
        parent_runtime_instance_id: str,
        task_id: str | None = None,
    ) -> tuple[DelegatedTaskRecord, ...]:
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                """
                select task.payload_json as task_json, task.status,
                       grant.payload_json as grant_json,
                       runtime.payload_json as runtime_json
                from delegated_task_revisions as task
                join delegation_grants as grant on grant.grant_id = task.delegation_grant_id
                join runtime_instances as runtime
                  on runtime.runtime_instance_id = task.child_runtime_instance_id
                where task.principal_id = ? and task.parent_runtime_instance_id = ?
                  and (? is null or task.task_id = ?)
                order by task.created_at, task.task_revision
                """,
                (principal_id, parent_runtime_instance_id, task_id, task_id),
            ).fetchall()
        return tuple(
            DelegatedTaskRecord(
                envelope=TaskEnvelope.model_validate_json(str(row["task_json"])),
                grant=DelegationGrant.model_validate_json(str(row["grant_json"])),
                child_runtime=RuntimeInstance.model_validate_json(str(row["runtime_json"])),
                status=str(row["status"]),
            )
            for row in rows
        )

    def list_for_session(
        self,
        *,
        principal_id: str,
        session_id: str,
        task_id: str | None = None,
    ) -> tuple[DelegatedTaskRecord, ...]:
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                """
                select task.payload_json as task_json, task.status,
                       grant.payload_json as grant_json,
                       runtime.payload_json as runtime_json
                from delegated_task_revisions as task
                join delegation_grants as grant on grant.grant_id = task.delegation_grant_id
                join runtime_instances as runtime
                  on runtime.runtime_instance_id = task.child_runtime_instance_id
                where task.principal_id = ? and runtime.session_id = ?
                  and (? is null or task.task_id = ?)
                order by task.created_at, task.task_revision
                """,
                (principal_id, session_id, task_id, task_id),
            ).fetchall()
        return tuple(
            DelegatedTaskRecord(
                envelope=TaskEnvelope.model_validate_json(str(row["task_json"])),
                grant=DelegationGrant.model_validate_json(str(row["grant_json"])),
                child_runtime=RuntimeInstance.model_validate_json(str(row["runtime_json"])),
                status=str(row["status"]),
            )
            for row in rows
        )

    def claim_completion_notifications(
        self,
        instance: RuntimeInstance,
    ) -> tuple[DelegatedTaskEvent, ...]:
        if instance.request.runtime_role != "main":
            return ()
        now = utc_now_text()
        with self._database.transaction() as conn:
            rows = conn.execute(
                """
                select event_id, payload_json from delegated_task_notifications
                where principal_id = ? and session_id = ?
                  and (delivered_runtime_instance_id is null or delivered_runtime_instance_id = ?)
                order by created_at, event_id
                """,
                (
                    instance.request.principal_id,
                    instance.request.session_id,
                    instance.runtime_instance_id,
                ),
            ).fetchall()
            for row in rows:
                conn.execute(
                    """
                    update delegated_task_notifications
                    set delivered_runtime_instance_id = ?, delivered_at = ?
                    where event_id = ? and delivered_runtime_instance_id is null
                    """,
                    (instance.runtime_instance_id, now, str(row["event_id"])),
                )
        return tuple(
            DelegatedTaskEvent.model_validate_json(str(row["payload_json"]))
            for row in rows
        )

    def claim_next(self, *, generation: int, lease_seconds: int) -> DelegatedTaskClaim | None:
        if generation < 1:
            raise ValueError("delegated task claim generation must be positive")
        if lease_seconds < 1:
            raise ValueError("delegated task claim lease must be positive")
        now_value = datetime.now(UTC)
        now = now_value.isoformat()
        expires_at = (now_value + timedelta(seconds=lease_seconds)).isoformat()
        claim_id = uuid4().hex
        with self._database.transaction() as conn:
            conn.execute(
                """
                update delegated_task_revisions
                set claim_id = null, claimed_generation = null, claim_expires_at = null,
                    updated_at = ?
                where status = 'queued' and claim_id is not null and claim_expires_at <= ?
                """,
                (now, now),
            )
            row = conn.execute(
                """
                select task.task_id, task.task_revision, task.child_runtime_instance_id
                from delegated_task_revisions as task
                join delegation_grants as grant on grant.grant_id = task.delegation_grant_id
                join runtime_instances as runtime
                  on runtime.runtime_instance_id = task.child_runtime_instance_id
                where task.status = 'queued' and task.claim_id is null
                  and grant.status = 'active' and grant.expires_at > ?
                  and runtime.status = 'queued' and runtime.generation = ?
                order by task.created_at, task.task_id, task.task_revision
                limit 1
                """,
                (now, generation),
            ).fetchone()
            if row is None:
                return None
            changed = conn.execute(
                """
                update delegated_task_revisions
                set claim_id = ?, claimed_generation = ?, claim_expires_at = ?, updated_at = ?
                where task_id = ? and task_revision = ? and status = 'queued' and claim_id is null
                """,
                (
                    claim_id,
                    generation,
                    expires_at,
                    now,
                    str(row["task_id"]),
                    int(row["task_revision"]),
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("delegated task claim compare-and-set failed")
        return DelegatedTaskClaim(
            claim_id=claim_id,
            task_id=str(row["task_id"]),
            task_revision=int(row["task_revision"]),
            child_runtime_instance_id=str(row["child_runtime_instance_id"]),
            generation=generation,
            expires_at=expires_at,
        )


def _validate_objects(
    *,
    envelope: TaskEnvelope,
    grant: DelegationGrant,
    capability_snapshot: CapabilitySnapshot,
    child_runtime: RuntimeInstance,
) -> None:
    request = child_runtime.request
    if envelope.strategy is None or envelope.system_prompt is None:
        raise ValueError("new delegated tasks require a strategy and system prompt")
    if child_runtime.status != "queued" or child_runtime.attempt_id is not None:
        raise ValueError("delegated child runtime must be queued and unclaimed")
    if child_runtime.last_event_sequence != 1:
        raise ValueError("delegated child runtime must reserve event sequence 1")
    if request.runtime_role != "temporary":
        raise ValueError("delegated runtime must use the temporary role")
    if request.strategy != envelope.strategy:
        raise ValueError("delegated runtime strategy differs from the task envelope")
    if capability_snapshot.snapshot_id != child_runtime.capability_snapshot_id:
        raise ValueError("delegated runtime references a different capability snapshot")
    expected = (
        envelope.task_id,
        envelope.task_revision,
        envelope.parent_task_revision,
        envelope.principal_id,
        envelope.parent_runtime_instance_id,
        envelope.delegation_grant_id,
        envelope.capability_snapshot_id,
        envelope.workspace_id,
        envelope.approval_mode,
    )
    actual = (
        grant.task_id,
        grant.task_revision,
        grant.parent_task_revision,
        grant.principal_id,
        grant.parent_runtime_instance_id,
        grant.grant_id,
        grant.child_capability_snapshot_id,
        grant.workspace_id,
        grant.approval_mode,
    )
    if expected != actual:
        raise ValueError("task envelope and delegation grant identities differ")
    runtime_expected = (
        grant.child_runtime_instance_id,
        grant.principal_id,
        grant.parent_runtime_instance_id,
        grant.task_id,
        grant.grant_id,
        grant.child_capability_snapshot_id,
        grant.workspace_id,
        grant.approval_mode,
    )
    runtime_actual = (
        child_runtime.runtime_instance_id,
        request.principal_id,
        request.parent_runtime_instance_id,
        request.task_id,
        request.delegation_grant_id,
        request.capability_snapshot_id,
        request.workspace_id,
        request.approval_mode,
    )
    if runtime_actual != runtime_expected:
        raise ValueError("delegation grant and child runtime identities differ")
    if tuple(capability_snapshot.tool_ids) != grant.allowed_tool_aliases:
        raise ValueError("delegation tool scope must exactly match the frozen child snapshot")
    if envelope.allowed_write_roots != grant.allowed_write_roots:
        raise ValueError("task workspace scope differs from delegation grant")


def _validate_parent(
    *,
    parent: RuntimeInstance,
    envelope: TaskEnvelope,
    grant: DelegationGrant,
    child: RuntimeInstance,
) -> None:
    if parent.status != "running":
        raise RuntimeError("delegation parent runtime must be running")
    if parent.capability_snapshot_id != grant.parent_capability_snapshot_id:
        raise PermissionError("delegation parent snapshot differs from the grant authority")
    request = parent.request
    if (
        request.principal_id != grant.principal_id
        or request.workspace_id != grant.workspace_id
        or request.session_id != child.request.session_id
        or request.turn_id != child.request.turn_id
        or request.task_revision != envelope.parent_task_revision
        or child.request.task_revision != envelope.task_revision
        or envelope.principal_id != request.principal_id
        or grant.approval_mode != request.approval_mode
    ):
        raise PermissionError("delegation parent, task, and child ownership differ")


def _validate_parent_grant_attenuation(conn, *, parent: RuntimeInstance, grant: DelegationGrant) -> None:
    if parent.request.runtime_role == "main":
        return
    parent_grant_id = parent.request.delegation_grant_id
    row = conn.execute(
        "select status, expires_at, payload_json from delegation_grants where grant_id = ?",
        (parent_grant_id,),
    ).fetchone()
    if row is None or str(row["status"]) != "active":
        raise PermissionError("parent delegation grant is not active")
    if datetime.fromisoformat(str(row["expires_at"])) <= datetime.now(UTC):
        raise PermissionError("parent delegation grant has expired")
    authority = DelegationGrant.model_validate_json(str(row["payload_json"]))
    if authority.remaining_delegation_depth < 1:
        raise PermissionError("parent delegation grant cannot be delegated further")
    if grant.maximum_delegation_depth != authority.maximum_delegation_depth:
        raise PermissionError("child grant cannot change the delegation depth ceiling")
    if grant.remaining_delegation_depth != authority.remaining_delegation_depth - 1:
        raise PermissionError("child grant must attenuate remaining delegation depth")
    if not set(grant.allowed_write_roots).issubset(authority.allowed_write_roots):
        raise PermissionError("child grant expands the parent workspace scope")
    if not set(grant.allowed_artifact_ids).issubset(authority.allowed_artifact_ids):
        raise PermissionError("child grant expands the parent artifact scope")
    if not set(grant.allowed_tool_aliases).issubset(authority.allowed_tool_aliases):
        raise PermissionError("child grant expands the parent tool scope")
    if grant.approval_mode != authority.approval_mode:
        raise PermissionError("child grant cannot change the inherited approval mode")
    if datetime.fromisoformat(grant.expires_at) > datetime.fromisoformat(authority.expires_at):
        raise PermissionError("child grant cannot outlive its parent grant")


def _delegated_observation_activities(chunk: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(chunk, dict):
        return ()
    chunk_type = str(chunk.get("type") or "")
    payload = chunk.get("payload")
    candidates: list[dict[str, Any]] = []
    if chunk_type == "node_event" and isinstance(payload, dict):
        candidates.append(payload)
    elif chunk_type == "tool_activity" and isinstance(payload, dict):
        raw_events = payload.get("events")
        if isinstance(raw_events, list):
            candidates.extend(item for item in raw_events if isinstance(item, dict))
    activities = []
    for candidate in candidates:
        event_type = str(candidate.get("event_type") or "").strip()
        if not event_type or event_type.endswith("_delta"):
            continue
        body = candidate.get("payload")
        activities.append(
            {
                "activity_type": event_type,
                "node_id": str(candidate.get("node_id") or "") or None,
                "source_event_id": str(candidate.get("event_id") or "") or None,
                "created_at": str(candidate.get("created_at") or "") or utc_now_text(),
                "details": _json_record(body if isinstance(body, dict) else {}),
            }
        )
    return tuple(activities)


def _json_record(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))
