from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from agent_factory.dynamic_runtime.database import DynamicRuntimeDatabase
from agent_factory.runtime_protocol import (
    CapabilityActivation,
    CapabilityDraft,
    CapabilityIndexRevision,
    CapabilityKind,
    CapabilityRevision,
    CapabilityTombstone,
    CapabilityValidationReceipt,
)


class CapabilityStoreError(RuntimeError):
    pass


class CapabilityConflictError(CapabilityStoreError):
    pass


class CapabilityNotFoundError(CapabilityStoreError):
    pass


@dataclass(frozen=True, slots=True)
class ActiveCapability:
    activation: CapabilityActivation
    revision: CapabilityRevision
    index_revision: CapabilityIndexRevision


class CapabilityStore:
    """Authoritative store shared by every capability kind.

    Drafts are CAS-ed mutable records. Published revisions, validation receipts,
    index revisions, and tombstones are immutable. Activation is a separate CAS
    pointer so enabling or disabling a capability never mutates its content.
    """

    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def create_draft(self, draft: CapabilityDraft) -> CapabilityDraft:
        if draft.draft_revision != 1:
            raise ValueError("new capability draft must start at revision 1")
        with self._database.transaction() as conn:
            self._require_capability_id_available(conn, draft.capability_id)
            self._require_namespace_available(
                conn,
                kind=draft.kind,
                namespace=draft.namespace,
                capability_id=draft.capability_id,
            )
            conn.execute(
                """
                insert into capability_drafts(
                  capability_id, kind, draft_revision, namespace, content_digest,
                  payload_json, updated_by_principal_id, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    draft.capability_id,
                    draft.kind,
                    draft.draft_revision,
                    draft.namespace,
                    draft.content_digest,
                    draft.model_dump_json(),
                    draft.updated_by_principal_id,
                    draft.created_at,
                    draft.updated_at,
                ),
            )
        return draft

    def replace_draft(
        self,
        draft: CapabilityDraft,
        *,
        expected_draft_revision: int,
    ) -> CapabilityDraft:
        if expected_draft_revision < 1:
            raise ValueError("expected_draft_revision must be positive")
        if draft.draft_revision != expected_draft_revision + 1:
            raise ValueError("replacement draft revision must increment expected revision by one")
        with self._database.transaction() as conn:
            row = conn.execute(
                "select kind, namespace, draft_revision from capability_drafts where capability_id = ?",
                (draft.capability_id,),
            ).fetchone()
            if row is None:
                raise CapabilityNotFoundError(f"capability draft not found: {draft.capability_id}")
            if int(row["draft_revision"]) != expected_draft_revision:
                raise CapabilityConflictError("capability draft revision changed")
            if str(row["kind"]) != draft.kind or str(row["namespace"]) != draft.namespace:
                raise CapabilityConflictError("capability kind and namespace are immutable")
            updated = conn.execute(
                """
                update capability_drafts
                set draft_revision = ?, content_digest = ?, payload_json = ?,
                    updated_by_principal_id = ?, updated_at = ?
                where capability_id = ? and draft_revision = ?
                """,
                (
                    draft.draft_revision,
                    draft.content_digest,
                    draft.model_dump_json(),
                    draft.updated_by_principal_id,
                    draft.updated_at,
                    draft.capability_id,
                    expected_draft_revision,
                ),
            )
            if updated.rowcount != 1:
                raise CapabilityConflictError("capability draft revision changed")
        return draft

    def draft(self, capability_id: str) -> CapabilityDraft:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                "select payload_json from capability_drafts where capability_id = ?",
                (_required_text(capability_id, "capability_id"),),
            ).fetchone()
        if row is None:
            raise CapabilityNotFoundError(f"capability draft not found: {capability_id}")
        return CapabilityDraft.model_validate_json(str(row["payload_json"]))

    def record_validation(
        self,
        receipt: CapabilityValidationReceipt,
    ) -> CapabilityValidationReceipt:
        with self._database.transaction() as conn:
            draft = self._draft_row(conn, receipt.capability_id)
            if (
                str(draft["kind"]) != receipt.kind
                or int(draft["draft_revision"]) != receipt.draft_revision
                or str(draft["content_digest"]) != receipt.content_digest
            ):
                raise CapabilityConflictError("validation receipt does not match current draft")
            payload = receipt.model_dump_json()
            existing = conn.execute(
                "select payload_json from capability_validation_receipts where receipt_id = ?",
                (receipt.receipt_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload:
                    raise CapabilityConflictError("validation receipt ID already contains different data")
                return receipt
            conn.execute(
                """
                insert into capability_validation_receipts(
                  receipt_id, capability_id, kind, draft_revision, content_digest,
                  status, payload_json, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.receipt_id,
                    receipt.capability_id,
                    receipt.kind,
                    receipt.draft_revision,
                    receipt.content_digest,
                    receipt.status,
                    payload,
                    receipt.created_at,
                ),
            )
        return receipt

    def publish(
        self,
        revision: CapabilityRevision,
        *,
        expected_draft_revision: int,
    ) -> CapabilityRevision:
        with self._database.transaction() as conn:
            draft_row = self._draft_row(conn, revision.capability_id)
            draft = CapabilityDraft.model_validate_json(str(draft_row["payload_json"]))
            if draft.draft_revision != expected_draft_revision:
                raise CapabilityConflictError("capability draft revision changed before publish")
            self._require_revision_matches_draft(revision, draft)
            receipt_row = conn.execute(
                """
                select payload_json from capability_validation_receipts
                where receipt_id = ? and capability_id = ? and draft_revision = ?
                  and content_digest = ? and status = 'passed'
                """,
                (
                    revision.validation_receipt_id,
                    revision.capability_id,
                    expected_draft_revision,
                    revision.content_digest,
                ),
            ).fetchone()
            if receipt_row is None:
                raise CapabilityConflictError("published revision requires a matching passed validation receipt")
            expected_revision = int(
                conn.execute(
                    "select coalesce(max(revision), 0) + 1 from capability_revisions where capability_id = ?",
                    (revision.capability_id,),
                ).fetchone()[0]
            )
            if revision.revision != expected_revision:
                raise CapabilityConflictError(
                    f"capability revision must be {expected_revision}, got {revision.revision}"
                )
            conn.execute(
                """
                insert into capability_revisions(
                  capability_id, kind, revision, namespace, content_digest,
                  validation_receipt_id, payload_json, published_by_principal_id, published_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    revision.capability_id,
                    revision.kind,
                    revision.revision,
                    revision.namespace,
                    revision.content_digest,
                    revision.validation_receipt_id,
                    revision.model_dump_json(),
                    revision.published_by_principal_id,
                    revision.published_at,
                ),
            )
        return revision

    def revision(self, capability_id: str, revision: int) -> CapabilityRevision:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                "select payload_json from capability_revisions where capability_id = ? and revision = ?",
                (_required_text(capability_id, "capability_id"), revision),
            ).fetchone()
        if row is None:
            raise CapabilityNotFoundError(f"capability revision not found: {capability_id}@{revision}")
        return CapabilityRevision.model_validate_json(str(row["payload_json"]))

    def add_index_revision(self, index: CapabilityIndexRevision) -> CapabilityIndexRevision:
        with self._database.transaction() as conn:
            source = self._revision_row(conn, index.source_capability_id, index.source_revision)
            if str(source["content_digest"]) != index.source_digest:
                raise CapabilityConflictError("index source digest does not match capability revision")
            revision = CapabilityRevision.model_validate_json(str(source["payload_json"]))
            expected_document = {
                "display_name": revision.content.display_name,
                "description": revision.content.description,
                "keywords": revision.content.keywords,
            }
            actual_document = {
                "display_name": index.document.display_name,
                "description": index.document.description,
                "keywords": index.document.keywords,
            }
            if actual_document != expected_document:
                raise CapabilityConflictError("index search document differs from capability revision content")
            payload = index.model_dump_json()
            existing = conn.execute(
                "select payload_json from capability_index_revisions where index_revision_id = ?",
                (index.index_revision_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload:
                    raise CapabilityConflictError("index revision ID already contains different data")
                return index
            conn.execute(
                """
                insert into capability_index_revisions(
                  index_revision_id, capability_id, source_revision, source_digest,
                  index_digest, payload_json, created_at
                ) values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    index.index_revision_id,
                    index.source_capability_id,
                    index.source_revision,
                    index.source_digest,
                    index.index_digest,
                    payload,
                    index.created_at,
                ),
            )
        return index

    def set_activation(
        self,
        activation: CapabilityActivation,
        *,
        expected_activation_revision: int | None,
    ) -> CapabilityActivation:
        with self._database.transaction() as conn:
            existing = conn.execute(
                "select * from capability_activations where capability_id = ?",
                (activation.capability_id,),
            ).fetchone()
            if existing is None:
                if expected_activation_revision is not None or activation.activation_revision != 1:
                    raise CapabilityConflictError("new activation must start at revision 1 without an expectation")
                if activation.status != "active":
                    raise CapabilityConflictError("a capability cannot start with an inactive activation")
                namespace = self._validate_active_pointer(conn, activation)
                conn.execute(
                    """
                    insert into capability_activations(
                      capability_id, kind, namespace, activation_revision, status,
                      revision, content_digest, index_revision_id, payload_json,
                      changed_by_principal_id, changed_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    self._activation_values(activation, namespace),
                )
                return activation
            current_revision = int(existing["activation_revision"])
            if expected_activation_revision != current_revision:
                raise CapabilityConflictError("capability activation revision changed")
            if activation.activation_revision != current_revision + 1:
                raise ValueError("activation revision must increment expected revision by one")
            if str(existing["kind"]) != activation.kind:
                raise CapabilityConflictError("capability kind is immutable")
            namespace = (
                self._validate_active_pointer(conn, activation)
                if activation.status == "active"
                else str(existing["namespace"])
            )
            updated = conn.execute(
                """
                update capability_activations
                set namespace = ?, activation_revision = ?, status = ?, revision = ?,
                    content_digest = ?, index_revision_id = ?, payload_json = ?,
                    changed_by_principal_id = ?, changed_at = ?
                where capability_id = ? and activation_revision = ?
                """,
                (
                    namespace,
                    activation.activation_revision,
                    activation.status,
                    activation.revision,
                    activation.content_digest,
                    activation.index_revision_id,
                    activation.model_dump_json(),
                    activation.changed_by_principal_id,
                    activation.changed_at,
                    activation.capability_id,
                    current_revision,
                ),
            )
            if updated.rowcount != 1:
                raise CapabilityConflictError("capability activation revision changed")
        return activation

    def activation(self, capability_id: str) -> CapabilityActivation:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                "select payload_json from capability_activations where capability_id = ?",
                (_required_text(capability_id, "capability_id"),),
            ).fetchone()
        if row is None:
            raise CapabilityNotFoundError(f"capability activation not found: {capability_id}")
        return CapabilityActivation.model_validate_json(str(row["payload_json"]))

    def active_capabilities(self, *, kind: CapabilityKind | None = None) -> tuple[ActiveCapability, ...]:
        parameters: tuple[str, ...] = ()
        where = "where activation.status = 'active'"
        if kind is not None:
            where += " and activation.kind = ?"
            parameters = (kind,)
        with self._database.connection(query_only=True) as conn:
            rows = conn.execute(
                f"""
                select activation.payload_json as activation_json,
                       revision.payload_json as revision_json,
                       index_revision.payload_json as index_json
                from capability_activations as activation
                join capability_revisions as revision
                  on revision.capability_id = activation.capability_id
                 and revision.revision = activation.revision
                join capability_index_revisions as index_revision
                  on index_revision.index_revision_id = activation.index_revision_id
                {where}
                order by activation.kind, activation.namespace, activation.capability_id
                """,
                parameters,
            ).fetchall()
        return tuple(
            ActiveCapability(
                activation=CapabilityActivation.model_validate_json(str(row["activation_json"])),
                revision=CapabilityRevision.model_validate_json(str(row["revision_json"])),
                index_revision=CapabilityIndexRevision.model_validate_json(str(row["index_json"])),
            )
            for row in rows
        )

    def tombstone(
        self,
        tombstone: CapabilityTombstone,
        *,
        expected_activation_revision: int | None,
    ) -> CapabilityTombstone:
        with self._database.transaction() as conn:
            if conn.execute(
                "select 1 from capability_tombstones where capability_id = ?",
                (tombstone.capability_id,),
            ).fetchone() is not None:
                raise CapabilityConflictError("capability is already tombstoned")
            revision = self._revision_row(conn, tombstone.capability_id, tombstone.last_revision)
            if (
                str(revision["kind"]) != tombstone.kind
                or str(revision["content_digest"]) != tombstone.content_digest
            ):
                raise CapabilityConflictError("tombstone does not match the last published revision")
            latest = int(
                conn.execute(
                    "select max(revision) from capability_revisions where capability_id = ?",
                    (tombstone.capability_id,),
                ).fetchone()[0]
            )
            if tombstone.last_revision != latest:
                raise CapabilityConflictError("tombstone must reference the latest published revision")
            activation = conn.execute(
                "select activation_revision, status from capability_activations where capability_id = ?",
                (tombstone.capability_id,),
            ).fetchone()
            if activation is not None:
                if expected_activation_revision != int(activation["activation_revision"]):
                    raise CapabilityConflictError("capability activation revision changed")
                if str(activation["status"]) != "inactive":
                    raise CapabilityConflictError("active capability must be deactivated before deletion")
            elif expected_activation_revision is not None:
                raise CapabilityConflictError("capability has no activation revision")
            conn.execute("delete from capability_drafts where capability_id = ?", (tombstone.capability_id,))
            conn.execute(
                """
                insert into capability_tombstones(
                  capability_id, kind, last_revision, content_digest, payload_json,
                  deleted_by_principal_id, reason, deleted_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tombstone.capability_id,
                    tombstone.kind,
                    tombstone.last_revision,
                    tombstone.content_digest,
                    tombstone.model_dump_json(),
                    tombstone.deleted_by_principal_id,
                    tombstone.reason,
                    tombstone.deleted_at,
                ),
            )
        return tombstone

    def _require_capability_id_available(self, conn: sqlite3.Connection, capability_id: str) -> None:
        value = _required_text(capability_id, "capability_id")
        if conn.execute(
            "select 1 from capability_tombstones where capability_id = ?",
            (value,),
        ).fetchone() is not None:
            raise CapabilityConflictError("tombstoned capability IDs cannot be reused")
        if conn.execute(
            "select 1 from capability_drafts where capability_id = ?",
            (value,),
        ).fetchone() is not None:
            raise CapabilityConflictError("capability draft already exists")
        if conn.execute(
            "select 1 from capability_revisions where capability_id = ? limit 1",
            (value,),
        ).fetchone() is not None:
            raise CapabilityConflictError("published capability ID cannot be recreated")

    @staticmethod
    def _require_namespace_available(
        conn: sqlite3.Connection,
        *,
        kind: CapabilityKind,
        namespace: str,
        capability_id: str,
    ) -> None:
        row = conn.execute(
            """
            select capability_id from capability_drafts where kind = ? and namespace = ?
            union
            select capability_id from capability_revisions where kind = ? and namespace = ?
            limit 1
            """,
            (kind, namespace, kind, namespace),
        ).fetchone()
        if row is not None and str(row["capability_id"]) != capability_id:
            raise CapabilityConflictError(f"capability namespace is already owned: {kind}:{namespace}")

    @staticmethod
    def _draft_row(conn: sqlite3.Connection, capability_id: str) -> sqlite3.Row:
        row = conn.execute(
            "select * from capability_drafts where capability_id = ?",
            (_required_text(capability_id, "capability_id"),),
        ).fetchone()
        if row is None:
            raise CapabilityNotFoundError(f"capability draft not found: {capability_id}")
        return row

    @staticmethod
    def _revision_row(conn: sqlite3.Connection, capability_id: str, revision: int) -> sqlite3.Row:
        row = conn.execute(
            "select * from capability_revisions where capability_id = ? and revision = ?",
            (_required_text(capability_id, "capability_id"), revision),
        ).fetchone()
        if row is None:
            raise CapabilityNotFoundError(f"capability revision not found: {capability_id}@{revision}")
        return row

    @staticmethod
    def _require_revision_matches_draft(
        revision: CapabilityRevision,
        draft: CapabilityDraft,
    ) -> None:
        fields_match = (
            revision.capability_id == draft.capability_id
            and revision.kind == draft.kind
            and revision.namespace == draft.namespace
            and revision.resolved_version == draft.resolved_version
            and revision.source_uri == draft.source_uri
            and revision.trust_level == draft.trust_level
            and revision.content == draft.content
            and revision.content_digest == draft.content_digest
        )
        if not fields_match:
            raise CapabilityConflictError("published revision content does not match validated draft")

    @staticmethod
    def _activation_values(
        activation: CapabilityActivation,
        namespace: str,
    ) -> tuple[object, ...]:
        return (
            activation.capability_id,
            activation.kind,
            namespace,
            activation.activation_revision,
            activation.status,
            activation.revision,
            activation.content_digest,
            activation.index_revision_id,
            activation.model_dump_json(),
            activation.changed_by_principal_id,
            activation.changed_at,
        )

    @staticmethod
    def _validate_active_pointer(conn: sqlite3.Connection, activation: CapabilityActivation) -> str:
        if activation.revision is None or activation.index_revision_id is None:
            raise CapabilityConflictError("active capability is missing its revision or index pointer")
        revision = CapabilityStore._revision_row(conn, activation.capability_id, activation.revision)
        if (
            str(revision["kind"]) != activation.kind
            or str(revision["content_digest"]) != activation.content_digest
        ):
            raise CapabilityConflictError("activation does not match published capability revision")
        index = conn.execute(
            """
            select capability_id, source_revision, source_digest
            from capability_index_revisions where index_revision_id = ?
            """,
            (activation.index_revision_id,),
        ).fetchone()
        if index is None:
            raise CapabilityNotFoundError(
                f"capability index revision not found: {activation.index_revision_id}"
            )
        if (
            str(index["capability_id"]) != activation.capability_id
            or int(index["source_revision"]) != activation.revision
            or str(index["source_digest"]) != activation.content_digest
        ):
            raise CapabilityConflictError("activation index does not match capability revision")
        return str(revision["namespace"])


def _required_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text
