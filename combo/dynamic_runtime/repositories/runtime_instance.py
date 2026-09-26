from __future__ import annotations

from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.dynamic_runtime.persistence_helpers import (
    insert_outbox,
    insert_runtime_instance,
    upsert_capability_snapshot,
)
from combo.dynamic_runtime.repositories.shared import _required_text
from combo.runtime_protocol import CapabilitySnapshot, OutboxRecord, RuntimeInstance
from combo.runtime_protocol.contracts import RuntimeInstanceStatus
from combo.runtime_protocol.state_machines import RUNTIME_INSTANCE_TRANSITIONS, require_transition


class RuntimeInstanceStore:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def create(
        self,
        *,
        snapshot: CapabilitySnapshot,
        instance: RuntimeInstance,
        outbox: OutboxRecord,
    ) -> None:
        if snapshot.snapshot_id != instance.capability_snapshot_id:
            raise ValueError("runtime instance references a different capability snapshot")
        with self._database.transaction() as conn:
            upsert_capability_snapshot(conn, snapshot)
            insert_runtime_instance(conn, instance)
            insert_outbox(conn, outbox)

    def get(self, runtime_instance_id: str) -> RuntimeInstance:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                "select payload_json from runtime_instances where runtime_instance_id = ?",
                (_required_text(runtime_instance_id, "runtime_instance_id"),),
            ).fetchone()
        if row is None:
            raise LookupError(f"runtime instance not found: {runtime_instance_id}")
        return RuntimeInstance.model_validate_json(str(row["payload_json"]))

    def active_main_for_session(self, *, session_id: str, principal_id: str) -> RuntimeInstance:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                """
                select payload_json from runtime_instances
                where session_id = ?
                  and json_extract(payload_json, '$.request.principal_id') = ?
                  and json_extract(payload_json, '$.request.runtime_role') = 'main'
                  and status in ('queued', 'running', 'waiting_approval', 'waiting_external', 'cancelling')
                order by updated_at desc, rowid desc limit 1
                """,
                (
                    _required_text(session_id, "session_id"),
                    _required_text(principal_id, "principal_id"),
                ),
            ).fetchone()
        if row is None:
            raise LookupError(f"active runtime not found for session: {session_id}")
        return RuntimeInstance.model_validate_json(str(row["payload_json"]))

    def latest_completed_main_before(
        self,
        *,
        session_id: str,
        principal_id: str,
        created_at: str,
    ) -> RuntimeInstance | None:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                """
                select payload_json from runtime_instances
                where session_id = ?
                  and json_extract(payload_json, '$.request.principal_id') = ?
                  and json_extract(payload_json, '$.request.runtime_role') = 'main'
                  and status = 'completed'
                  and created_at < ?
                order by created_at desc, rowid desc limit 1
                """,
                (
                    _required_text(session_id, "session_id"),
                    _required_text(principal_id, "principal_id"),
                    _required_text(created_at, "created_at"),
                ),
            ).fetchone()
        if row is None:
            return None
        return RuntimeInstance.model_validate_json(str(row["payload_json"]))

    def latest_completed_main(
        self,
        *,
        session_id: str,
        principal_id: str,
    ) -> RuntimeInstance | None:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                """
                select payload_json from runtime_instances
                where session_id = ?
                  and json_extract(payload_json, '$.request.principal_id') = ?
                  and json_extract(payload_json, '$.request.runtime_role') = 'main'
                  and status = 'completed'
                order by created_at desc, rowid desc limit 1
                """,
                (
                    _required_text(session_id, "session_id"),
                    _required_text(principal_id, "principal_id"),
                ),
            ).fetchone()
        if row is None:
            return None
        return RuntimeInstance.model_validate_json(str(row["payload_json"]))

    def capability_snapshot(self, snapshot_id: str) -> CapabilitySnapshot:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                "select payload_json from capability_snapshots where snapshot_id = ?",
                (_required_text(snapshot_id, "snapshot_id"),),
            ).fetchone()
        if row is None:
            raise LookupError(f"capability snapshot not found: {snapshot_id}")
        return CapabilitySnapshot.model_validate_json(str(row["payload_json"]))

    def retain_capability_snapshot(self, snapshot: CapabilitySnapshot) -> None:
        """Retain an immutable execution snapshot not associated with a new runtime instance."""
        with self._database.transaction() as conn:
            upsert_capability_snapshot(conn, snapshot)

    def replace(
        self,
        *,
        instance: RuntimeInstance,
        expected_status: RuntimeInstanceStatus,
        outbox: OutboxRecord,
    ) -> None:
        require_transition(expected_status, instance.status, RUNTIME_INSTANCE_TRANSITIONS, machine="runtime instance")
        with self._database.transaction() as conn:
            changed = conn.execute(
                """
                update runtime_instances
                set status = ?, attempt_id = ?, last_event_sequence = ?,
                    payload_json = ?, updated_at = ?, terminal_at = ?
                where runtime_instance_id = ? and status = ?
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
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("runtime instance compare-and-set failed")
            insert_outbox(conn, outbox)
