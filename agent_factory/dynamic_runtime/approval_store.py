from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json

from agent_factory.dynamic_runtime.database import DynamicRuntimeDatabase
from agent_factory.dynamic_runtime.snapshot_tool_execution import (
    SnapshotToolApprovalResolver,
    ToolApprovalRuntimeLease,
)
from agent_factory.runtime_protocol import (
    CapabilityApprovalGrant,
    CapabilityProjectionSnapshot,
    CapabilitySnapshot,
    RuntimeInstance,
)


class CapabilityApprovalGrantStore:
    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def is_active(
        self,
        *,
        principal_id: str,
        capability_id: str,
        capability_revision: int,
        capability_content_digest: str,
        model_alias: str,
        resource_scope_digest: str,
        policy_id: str,
        policy_revision: int,
        now: str,
    ) -> bool:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                """
                select 1
                from capability_approval_grants
                where principal_id = ?
                  and capability_id = ?
                  and capability_revision = ?
                  and capability_content_digest = ?
                  and model_alias = ?
                  and resource_scope_digest = ?
                  and policy_id = ?
                  and policy_revision = ?
                  and status = 'active'
                  and (expires_at is null or expires_at > ?)
                limit 1
                """,
                (
                    principal_id,
                    capability_id,
                    capability_revision,
                    capability_content_digest,
                    model_alias,
                    resource_scope_digest,
                    policy_id,
                    policy_revision,
                    now,
                ),
            ).fetchone()
        return row is not None

    def trust(self, grant: CapabilityApprovalGrant) -> CapabilityApprovalGrant:
        if grant.status != "active":
            raise ValueError("new capability approval grant must be active")
        payload = json.dumps(grant.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        with self._database.transaction() as conn:
            _expire_stale_grants(conn, now=grant.created_at)
            existing = conn.execute(
                """
                select payload_json
                from capability_approval_grants
                where principal_id = ?
                  and capability_id = ?
                  and capability_revision = ?
                  and capability_content_digest = ?
                  and model_alias = ?
                  and resource_scope_digest = ?
                  and policy_id = ?
                  and policy_revision = ?
                  and status = 'active'
                  and (expires_at is null or expires_at > ?)
                """,
                (
                    grant.principal_id,
                    grant.capability_id,
                    grant.capability_revision,
                    grant.capability_content_digest,
                    grant.model_alias,
                    grant.resource_scope_digest,
                    grant.policy_id,
                    grant.policy_revision,
                    grant.created_at,
                ),
            ).fetchone()
            if existing is not None:
                return CapabilityApprovalGrant.model_validate(json.loads(existing["payload_json"]))
            conn.execute(
                """
                insert into capability_approval_grants(
                  grant_id, principal_id, capability_id, capability_revision,
                  capability_content_digest, model_alias, resource_scope_digest,
                  policy_id, policy_revision, status, payload_json,
                  created_at, expires_at, revoked_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    grant.grant_id,
                    grant.principal_id,
                    grant.capability_id,
                    grant.capability_revision,
                    grant.capability_content_digest,
                    grant.model_alias,
                    grant.resource_scope_digest,
                    grant.policy_id,
                    grant.policy_revision,
                    grant.status,
                    payload,
                    grant.created_at,
                    grant.expires_at,
                    grant.revoked_at,
                ),
            )
        return grant

    def revoke(self, grant_id: str, *, revoked_at: str) -> CapabilityApprovalGrant:
        with self._database.transaction() as conn:
            row = conn.execute(
                "select payload_json from capability_approval_grants where grant_id = ?",
                (grant_id,),
            ).fetchone()
            if row is None:
                raise LookupError(f"capability approval grant not found: {grant_id}")
            current = CapabilityApprovalGrant.model_validate(json.loads(row["payload_json"]))
            if current.status == "revoked":
                return current
            revoked = current.model_copy(
                update={"status": "revoked", "revoked_at": revoked_at},
            )
            payload = json.dumps(revoked.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            cursor = conn.execute(
                """
                update capability_approval_grants
                set status = 'revoked', payload_json = ?, revoked_at = ?
                where grant_id = ? and status = 'active'
                """,
                (payload, revoked_at, grant_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("capability approval grant changed during revocation")
        return revoked


class BoundCapabilityApprovalTrust:
    def __init__(
        self,
        *,
        store: CapabilityApprovalGrantStore,
        principal_id: str,
        capability_id: str,
        capability_revision: int,
        capability_content_digest: str,
        model_alias: str,
        resource_scope_digest: str,
        policy_id: str,
        policy_revision: int,
    ) -> None:
        self._store = store
        self._principal_id = principal_id
        self._capability_id = capability_id
        self._capability_revision = capability_revision
        self._capability_content_digest = capability_content_digest
        self._model_alias = model_alias
        self._resource_scope_digest = resource_scope_digest
        self._policy_id = policy_id
        self._policy_revision = policy_revision

    def is_trusted(self, tool_id: str) -> bool:
        self._require_alias(tool_id)
        return self._store.is_active(
            principal_id=self._principal_id,
            capability_id=self._capability_id,
            capability_revision=self._capability_revision,
            capability_content_digest=self._capability_content_digest,
            model_alias=self._model_alias,
            resource_scope_digest=self._resource_scope_digest,
            policy_id=self._policy_id,
            policy_revision=self._policy_revision,
            now=_utc_now_text(),
        )

    def trust_tool(self, tool_id: str) -> None:
        self._require_alias(tool_id)
        self._store.trust(
            CapabilityApprovalGrant(
                principal_id=self._principal_id,
                capability_id=self._capability_id,
                capability_revision=self._capability_revision,
                capability_content_digest=self._capability_content_digest,
                model_alias=self._model_alias,
                resource_scope_digest=self._resource_scope_digest,
                policy_id=self._policy_id,
                policy_revision=self._policy_revision,
            )
        )

    def _require_alias(self, tool_id: str) -> None:
        if tool_id != self._model_alias:
            raise ValueError("approval trust binding cannot be used for another tool alias")


class DatabaseSnapshotToolApprovalResolver(SnapshotToolApprovalResolver):
    def __init__(self, store: CapabilityApprovalGrantStore) -> None:
        self._store = store

    def acquire(
        self,
        *,
        projection: CapabilityProjectionSnapshot,
        capability_snapshot: CapabilitySnapshot,
        runtime_instance: RuntimeInstance,
    ) -> ToolApprovalRuntimeLease:
        aliases = tuple(
            binding.model_alias
            for binding in capability_snapshot.tool_aliases
            if binding.capability_id == projection.capability_id
        )
        if len(aliases) != 1:
            raise ValueError("approval resolver requires exactly one alias for a tool projection")
        policy = runtime_instance.request.policy_snapshot
        return ToolApprovalRuntimeLease(
            trust=BoundCapabilityApprovalTrust(
                store=self._store,
                principal_id=runtime_instance.request.principal_id,
                capability_id=projection.capability_id,
                capability_revision=projection.revision,
                capability_content_digest=projection.content_digest,
                model_alias=aliases[0],
                resource_scope_digest=_resource_scope_digest(
                    projection=projection,
                    capability_snapshot=capability_snapshot,
                    workspace_id=runtime_instance.request.workspace_id,
                ),
                policy_id=policy.source_policy_id,
                policy_revision=policy.source_policy_revision,
            ),
            release_callback=_release_borrowed_approval_store,
        )


def _resource_scope_digest(
    *,
    projection: CapabilityProjectionSnapshot,
    capability_snapshot: CapabilitySnapshot,
    workspace_id: str,
) -> str:
    definitions: list[dict[str, object]] = [projection.runtime_definition]
    if projection.kind == "mcp_tool":
        server_id = str(projection.runtime_definition.get("server_capability_id") or "").strip()
        servers = [
            item.runtime_definition
            for item in capability_snapshot.projections
            if item.kind == "mcp_server" and item.capability_id == server_id
        ]
        if len(servers) != 1:
            raise ValueError("MCP approval scope requires its immutable server projection")
        definitions.extend(servers)
    payload = {
        "workspace_id": workspace_id,
        "capability_id": projection.capability_id,
        "revision": projection.revision,
        "content_digest": projection.content_digest,
        "resource_bindings": [
            definition.get("resource_bindings", [])
            for definition in definitions
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _expire_stale_grants(conn, *, now: str) -> None:
    rows = conn.execute(
        """
        select grant_id, payload_json
        from capability_approval_grants
        where status = 'active' and expires_at is not null and expires_at <= ?
        """,
        (now,),
    ).fetchall()
    for row in rows:
        current = CapabilityApprovalGrant.model_validate(json.loads(row["payload_json"]))
        expired = current.model_copy(update={"status": "expired"})
        payload = json.dumps(expired.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        conn.execute(
            """
            update capability_approval_grants
            set status = 'expired', payload_json = ?
            where grant_id = ? and status = 'active'
            """,
            (payload, row["grant_id"]),
        )


def _release_borrowed_approval_store() -> None:
    return None


def _utc_now_text() -> str:
    return datetime.now(UTC).isoformat()
