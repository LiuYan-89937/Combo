from __future__ import annotations

from agent_factory.dynamic_runtime.database import DynamicRuntimeDatabase
from agent_factory.dynamic_runtime.persistence_helpers import insert_outbox
from agent_factory.runtime_protocol import (
    ApplicationGeneration,
    CutoverManifest,
    DeletePlan,
    DeliveryCommit,
    OutboxRecord,
    RevocationRecord,
)
from agent_factory.runtime_protocol.state_machines import (
    APPLICATION_GENERATION_TRANSITIONS,
    CUTOVER_TRANSITIONS,
    DELETE_TRANSITIONS,
    DELIVERY_TRANSITIONS,
    require_transition,
)


class ApplicationGenerationStore:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def acquire(self, record: ApplicationGeneration) -> None:
        if record.status != "starting":
            raise ValueError("new application generation must start in starting state")
        with self._database.transaction() as conn:
            active = conn.execute(
                """
                select generation from application_generations
                where status in ('starting', 'active', 'quiescing')
                  and lease_expires_at > ?
                limit 1
                """,
                (record.started_at,),
            ).fetchone()
            if active is not None:
                raise RuntimeError(f"application generation is already owned: {int(active['generation'])}")
            latest = int(
                conn.execute("select coalesce(max(generation), 0) from application_generations").fetchone()[0]
            )
            if record.generation != latest + 1:
                raise ValueError("application generation must increase monotonically by one")
            conn.execute(
                """
                insert into application_generations(
                  generation_id, generation, status, payload_json, lease_expires_at,
                  started_at, updated_at, closed_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.generation_id,
                    record.generation,
                    record.status,
                    record.model_dump_json(),
                    record.lease_expires_at,
                    record.started_at,
                    record.updated_at,
                    record.closed_at,
                ),
            )

    def next_generation_number(self) -> int:
        with self._database.connection(query_only=True) as conn:
            latest = int(
                conn.execute("select coalesce(max(generation), 0) from application_generations").fetchone()[0]
            )
        return latest + 1

    def replace(self, record: ApplicationGeneration, *, expected_status: str) -> None:
        require_transition(
            expected_status,
            record.status,
            APPLICATION_GENERATION_TRANSITIONS,
            machine="application generation",
        )
        with self._database.transaction() as conn:
            changed = conn.execute(
                """
                update application_generations
                set status = ?, payload_json = ?, lease_expires_at = ?,
                    updated_at = ?, closed_at = ?
                where generation_id = ? and generation = ? and status = ?
                """,
                (
                    record.status,
                    record.model_dump_json(),
                    record.lease_expires_at,
                    record.updated_at,
                    record.closed_at,
                    record.generation_id,
                    record.generation,
                    expected_status,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("application generation compare-and-set failed")

    def renew(self, record: ApplicationGeneration, *, expected_lease_expires_at: str) -> None:
        if record.status not in {"starting", "active", "quiescing"}:
            raise ValueError("only a live application generation lease can be renewed")
        with self._database.transaction() as conn:
            changed = conn.execute(
                """
                update application_generations
                set payload_json = ?, lease_expires_at = ?, updated_at = ?
                where generation_id = ? and generation = ? and status = ?
                  and lease_expires_at = ?
                """,
                (
                    record.model_dump_json(),
                    record.lease_expires_at,
                    record.updated_at,
                    record.generation_id,
                    record.generation,
                    record.status,
                    expected_lease_expires_at,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("application generation lease renewal compare-and-set failed")

    def active(self) -> ApplicationGeneration | None:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                """
                select payload_json from application_generations
                where status in ('starting', 'active', 'quiescing')
                order by generation desc limit 1
                """
            ).fetchone()
        if row is None:
            return None
        return ApplicationGeneration.model_validate_json(str(row["payload_json"]))


class CutoverManifestStore:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def create(self, manifest: CutoverManifest) -> None:
        if manifest.status != "preparing":
            raise ValueError("new cutover manifest must start in preparing state")
        with self._database.transaction() as conn:
            conn.execute(
                """
                insert into cutover_manifests(
                  cutover_id, manifest_revision, source_generation, target_generation, status,
                  payload_json, created_at, updated_at, committed_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    manifest.cutover_id,
                    manifest.manifest_revision,
                    manifest.source_generation,
                    manifest.target_generation,
                    manifest.status,
                    manifest.model_dump_json(),
                    manifest.created_at,
                    manifest.updated_at,
                    manifest.committed_at,
                ),
            )

    def replace(
        self,
        manifest: CutoverManifest,
        *,
        expected_status: str,
        expected_revision: int,
    ) -> None:
        if manifest.status != expected_status:
            require_transition(expected_status, manifest.status, CUTOVER_TRANSITIONS, machine="cutover")
        if manifest.manifest_revision != expected_revision + 1:
            raise ValueError("cutover manifest revision must increase by one")
        with self._database.transaction() as conn:
            changed = conn.execute(
                """
                update cutover_manifests
                set manifest_revision = ?, status = ?, payload_json = ?, updated_at = ?, committed_at = ?
                where cutover_id = ? and status = ? and manifest_revision = ?
                """,
                (
                    manifest.manifest_revision,
                    manifest.status,
                    manifest.model_dump_json(),
                    manifest.updated_at,
                    manifest.committed_at,
                    manifest.cutover_id,
                    expected_status,
                    expected_revision,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("cutover manifest compare-and-set failed")


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
