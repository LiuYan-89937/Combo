from __future__ import annotations

from typing import Mapping
from uuid import uuid4

from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.dynamic_runtime.persistence_helpers import insert_outbox
from combo.dynamic_runtime.repositories.shared import utc_now_text
from combo.runtime_protocol import OutboxRecord, UserRuntimePolicy


class UserRuntimePolicyStore:
    """Versioned backend authority for one principal's runtime choices."""

    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

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

    def write(
        self,
        *,
        principal_id: str,
        expected_revision: int | None,
        changes: Mapping[str, object],
    ) -> UserRuntimePolicy:
        """Apply a validated policy change through one revision and outbox boundary."""
        owner = _required_text(principal_id, "principal_id")
        protected = {"principal_id", "policy_id", "revision", "updated_at"}
        unknown = changes.keys() - (UserRuntimePolicy.model_fields.keys() - protected)
        if unknown:
            raise ValueError(f"unsupported runtime policy fields: {', '.join(sorted(unknown))}")
        with self._database.transaction() as conn:
            row = conn.execute(
                "select payload_json from user_runtime_policies where principal_id = ?",
                (owner,),
            ).fetchone()
            if row is None:
                if expected_revision not in {None, 0}:
                    raise RuntimeError("runtime_policy_revision_conflict")
                now = utc_now_text()
                policy = UserRuntimePolicy.model_validate({
                    **changes,
                    "principal_id": owner,
                    "policy_id": uuid4().hex,
                    "revision": 1,
                    "updated_at": now,
                })
                conn.execute(
                    "insert or ignore into principals(principal_id, created_at) values (?, ?)",
                    (owner, now),
                )
                conn.execute(
                    """
                    insert into user_runtime_policies(
                      policy_id, principal_id, revision, payload_json, created_at, updated_at
                    ) values (?, ?, ?, ?, ?, ?)
                    """,
                    (policy.policy_id, owner, 1, policy.model_dump_json(), now, now),
                )
                insert_outbox(conn, _policy_outbox(policy, event_kind="runtime_policy_created"))
                return policy
            current = UserRuntimePolicy.model_validate_json(str(row["payload_json"]))
            if expected_revision != current.revision:
                raise RuntimeError("runtime_policy_revision_conflict")
            policy = UserRuntimePolicy.model_validate({
                **current.model_dump(mode="python"),
                **changes,
                "revision": current.revision + 1,
                "updated_at": utc_now_text(),
            })
            if policy.model_dump(exclude={"revision", "updated_at"}) == current.model_dump(exclude={"revision", "updated_at"}):
                return current
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
                    owner,
                    current.revision,
                ),
            ).rowcount
            if changed != 1:
                raise RuntimeError("runtime_policy_revision_conflict")
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
