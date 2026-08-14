from __future__ import annotations

from combo.dynamic_runtime.database import DynamicRuntimeDatabase
from combo.runtime_protocol import (
    CapabilityHealthReceipt,
    CapabilityRevision,
    DependencyEnvironmentReceipt,
)


class CapabilityResolutionReceiptConflict(RuntimeError):
    pass


class CapabilityResolutionReceiptStore:
    """Immutable health and prepared-environment evidence for resolution.

    This store never probes, installs, or refreshes external state. Producers
    publish receipts after their separately managed validation/build jobs reach
    a terminal state; main-turn resolution only reads those receipts.
    """

    def __init__(self, database: DynamicRuntimeDatabase) -> None:
        self._database = database

    def record_health(self, receipt: CapabilityHealthReceipt) -> CapabilityHealthReceipt:
        with self._database.transaction() as conn:
            revision = conn.execute(
                """
                select payload_json from capability_revisions
                where capability_id = ? and revision = ?
                """,
                (receipt.capability_id, receipt.revision),
            ).fetchone()
            if revision is None:
                raise LookupError(
                    f"capability revision not found for health receipt: "
                    f"{receipt.capability_id}@{receipt.revision}"
                )
            published = CapabilityRevision.model_validate_json(str(revision["payload_json"]))
            if (
                published.kind != receipt.kind
                or published.content_digest != receipt.content_digest
            ):
                raise CapabilityResolutionReceiptConflict(
                    "health receipt identity differs from published capability revision"
                )
            payload = receipt.model_dump_json()
            existing = conn.execute(
                "select payload_json from capability_health_receipts where receipt_id = ?",
                (receipt.receipt_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload:
                    raise CapabilityResolutionReceiptConflict(
                        "health receipt ID already contains different data"
                    )
                return receipt
            conn.execute(
                """
                insert into capability_health_receipts(
                  receipt_id, capability_id, kind, revision, content_digest,
                  status, payload_json, checked_at, valid_until
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.receipt_id,
                    receipt.capability_id,
                    receipt.kind,
                    receipt.revision,
                    receipt.content_digest,
                    receipt.status,
                    payload,
                    receipt.checked_at,
                    receipt.valid_until,
                ),
            )
        return receipt

    def latest_health(
        self,
        *,
        capability_id: str,
        revision: int,
        content_digest: str,
    ) -> CapabilityHealthReceipt | None:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                """
                select payload_json from capability_health_receipts
                where capability_id = ? and revision = ? and content_digest = ?
                order by checked_at desc, receipt_id desc
                limit 1
                """,
                (
                    _required_text(capability_id, "capability_id"),
                    revision,
                    _required_text(content_digest, "content_digest"),
                ),
            ).fetchone()
        return (
            CapabilityHealthReceipt.model_validate_json(str(row["payload_json"]))
            if row is not None
            else None
        )

    def record_environment(
        self,
        receipt: DependencyEnvironmentReceipt,
    ) -> DependencyEnvironmentReceipt:
        with self._database.transaction() as conn:
            for reference in receipt.environment.capability_refs:
                row = conn.execute(
                    """
                    select payload_json from capability_revisions
                    where capability_id = ? and revision = ?
                    """,
                    (reference.capability_id, reference.revision),
                ).fetchone()
                if row is None:
                    raise LookupError(
                        f"dependency capability revision not found for environment receipt: "
                        f"{reference.capability_id}@{reference.revision}"
                    )
                revision = CapabilityRevision.model_validate_json(str(row["payload_json"]))
                if (
                    revision.kind != "dependency"
                    or revision.content_digest != reference.content_digest
                    or revision.resolved_version != reference.resolved_version
                ):
                    raise CapabilityResolutionReceiptConflict(
                        "dependency environment reference differs from published revision"
                    )
            payload = receipt.model_dump_json()
            existing = conn.execute(
                "select payload_json from dependency_environment_receipts where receipt_id = ?",
                (receipt.receipt_id,),
            ).fetchone()
            if existing is not None:
                if str(existing["payload_json"]) != payload:
                    raise CapabilityResolutionReceiptConflict(
                        "dependency environment receipt ID already contains different data"
                    )
                return receipt
            conn.execute(
                """
                insert into dependency_environment_receipts(
                  receipt_id, dependency_closure_digest, projection_digest, status,
                  environment_id, environment_revision, environment_content_digest,
                  payload_json, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.receipt_id,
                    receipt.dependency_closure_digest,
                    receipt.projection_digest,
                    receipt.status,
                    receipt.environment.environment_id,
                    receipt.environment.revision,
                    receipt.environment.content_digest,
                    payload,
                    receipt.created_at,
                ),
            )
        return receipt

    def latest_environment(
        self,
        *,
        dependency_closure_digest: str,
        projection_digest: str,
    ) -> DependencyEnvironmentReceipt | None:
        with self._database.connection(query_only=True) as conn:
            row = conn.execute(
                """
                select payload_json from dependency_environment_receipts
                where dependency_closure_digest = ? and projection_digest = ?
                order by created_at desc, receipt_id desc
                limit 1
                """,
                (
                    _required_text(dependency_closure_digest, "dependency_closure_digest"),
                    _required_text(projection_digest, "projection_digest"),
                ),
            ).fetchone()
        return (
            DependencyEnvironmentReceipt.model_validate_json(str(row["payload_json"]))
            if row is not None
            else None
        )


def _required_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text
