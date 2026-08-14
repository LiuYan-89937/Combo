from __future__ import annotations

from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.dynamic_runtime.persistence_helpers import insert_outbox
from combo.runtime_protocol import (
    DeletePlan,
    DeliveryCommit,
    OutboxRecord,
    RevocationRecord,
)
from combo.runtime_protocol.state_machines import (
    DELETE_TRANSITIONS,
    DELIVERY_TRANSITIONS,
    require_transition,
)


class RevocationStore:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def add(self, record: RevocationRecord, *, outbox: OutboxRecord) -> None:
        with self._database.transaction() as conn:
            conn.execute(
                """
                insert into revocations(
                  revocation_id, kind, subject_id, subject_revision, payload_json, revoked_at
                ) values (?, ?, ?, ?, ?, ?)
                """,
                (
                    record.revocation_id,
                    record.kind,
                    record.subject_id,
                    record.subject_revision,
                    record.model_dump_json(),
                    record.revoked_at,
                ),
            )
            insert_outbox(conn, outbox)

    def contains(self, *, kind: str, subject_id: str, subject_revision: int) -> bool:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                """
                select 1 from revocations
                where kind = ? and subject_id = ? and subject_revision = ?
                """,
                (kind, subject_id, subject_revision),
            ).fetchone()
        return row is not None


class DeliveryCommitStore:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def create(self, record: DeliveryCommit, *, outbox: OutboxRecord) -> None:
        if record.status != "prepared":
            raise ValueError("new delivery commit must start in prepared state")
        with self._database.transaction() as conn:
            conn.execute(
                """
                insert into delivery_commits(
                  delivery_id, runtime_instance_id, request_id, status,
                  payload_json, created_at, updated_at, terminal_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.delivery_id,
                    record.runtime_instance_id,
                    record.request_id,
                    record.status,
                    record.model_dump_json(),
                    record.created_at,
                    record.updated_at,
                    record.terminal_at,
                ),
            )
            insert_outbox(conn, outbox)

    def replace(self, record: DeliveryCommit, *, expected_status: str, outbox: OutboxRecord) -> None:
        require_transition(expected_status, record.status, DELIVERY_TRANSITIONS, machine="delivery")
        with self._database.transaction() as conn:
            changed = conn.execute(
                """
                update delivery_commits
                set status = ?, payload_json = ?, updated_at = ?, terminal_at = ?
                where delivery_id = ? and status = ?
                """,
                (
                    record.status,
                    record.model_dump_json(),
                    record.updated_at,
                    record.terminal_at,
                    record.delivery_id,
                    expected_status,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("delivery commit compare-and-set failed")
            insert_outbox(conn, outbox)


class DeletePlanStore:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def create(self, record: DeletePlan, *, outbox: OutboxRecord) -> None:
        if record.status != "planned":
            raise ValueError("new delete plan must start in planned state")
        with self._database.transaction() as conn:
            conn.execute(
                """
                insert into delete_plans(
                  delete_plan_id, principal_id, root_kind, root_id, status,
                  payload_json, created_at, updated_at, terminal_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.delete_plan_id,
                    record.principal_id,
                    record.root_kind,
                    record.root_id,
                    record.status,
                    record.model_dump_json(),
                    record.created_at,
                    record.updated_at,
                    record.terminal_at,
                ),
            )
            insert_outbox(conn, outbox)

    def replace(self, record: DeletePlan, *, expected_status: str, outbox: OutboxRecord) -> None:
        require_transition(expected_status, record.status, DELETE_TRANSITIONS, machine="delete")
        with self._database.transaction() as conn:
            changed = conn.execute(
                """
                update delete_plans
                set status = ?, payload_json = ?, updated_at = ?, terminal_at = ?
                where delete_plan_id = ? and status = ?
                """,
                (
                    record.status,
                    record.model_dump_json(),
                    record.updated_at,
                    record.terminal_at,
                    record.delete_plan_id,
                    expected_status,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("delete plan compare-and-set failed")
            insert_outbox(conn, outbox)
