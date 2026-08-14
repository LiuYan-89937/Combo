from __future__ import annotations

from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.dynamic_runtime.persistence_helpers import insert_outbox
from combo.runtime_protocol import OutboxRecord, UserRuntimePolicy


class UserRuntimePolicyStore:
    """Versioned backend authority for one principal's runtime choices."""

    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def create(self, policy: UserRuntimePolicy, *, created_at: str) -> UserRuntimePolicy:
        if policy.revision != 1:
            raise ValueError("new runtime policy must start at revision 1")
        with self._database.transaction() as conn:
            conn.execute(
                """
                insert into user_runtime_policies(
                  policy_id, principal_id, revision, payload_json, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?)
                """,
                (
                    policy.policy_id,
                    policy.principal_id,
                    policy.revision,
                    policy.model_dump_json(),
                    created_at,
                    policy.updated_at,
                ),
            )
            insert_outbox(conn, _policy_outbox(policy, event_kind="runtime_policy_created"))
        return policy

    def require_for_principal(self, principal_id: str) -> UserRuntimePolicy:
        value = _required_text(principal_id, "principal_id")
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                "select payload_json from user_runtime_policies where principal_id = ?",
                (value,),
            ).fetchone()
        if row is None:
            raise LookupError(f"runtime policy not found for principal: {value}")
        return UserRuntimePolicy.model_validate_json(str(row["payload_json"]))

    def replace(
        self,
        policy: UserRuntimePolicy,
        *,
        expected_revision: int,
    ) -> UserRuntimePolicy:
        if policy.revision != expected_revision + 1:
            raise ValueError("runtime policy revision must increase by one")
        with self._database.transaction() as conn:
            row = conn.execute(
                """
                select principal_id from user_runtime_policies
                where policy_id = ? and revision = ?
                """,
                (policy.policy_id, expected_revision),
            ).fetchone()
            if row is None:
                raise RuntimeError("runtime policy compare-and-set precondition failed")
            if str(row["principal_id"]) != policy.principal_id:
                raise ValueError("runtime policy principal identity cannot change")
            changed = conn.execute(
                """
                update user_runtime_policies
                set revision = ?, payload_json = ?, updated_at = ?
                where policy_id = ? and principal_id = ? and revision = ?
                """,
                (
                    policy.revision,
                    policy.model_dump_json(),
                    policy.updated_at,
                    policy.policy_id,
                    policy.principal_id,
                    expected_revision,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("runtime policy compare-and-set failed")
            insert_outbox(conn, _policy_outbox(policy, event_kind="runtime_policy_updated"))
        return policy


def _policy_outbox(policy: UserRuntimePolicy, *, event_kind: str) -> OutboxRecord:
    return OutboxRecord(
        aggregate_kind="runtime_policy",
        aggregate_id=policy.policy_id,
        aggregate_revision=policy.revision,
        event_id=f"runtime_policy:{policy.policy_id}:{policy.revision}",
        event_kind=event_kind,
        payload=policy.model_dump(mode="json"),
        created_at=policy.updated_at,
        updated_at=policy.updated_at,
    )


def _required_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text
