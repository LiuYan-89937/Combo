from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from combo.dynamic_runtime.capability_adapters import CapabilityAdapterRegistry
from combo.dynamic_runtime.capability_resolution_store import CapabilityResolutionReceiptStore
from combo.dynamic_runtime.capability_store import (
    CapabilityConflictError,
    CapabilityNotFoundError,
    CapabilityStore,
)
from combo.runtime_protocol import (
    CapabilityActivation,
    CapabilityDraft,
    CapabilityHealthReceipt,
    CapabilityIndexRevision,
    CapabilityRevision,
    CapabilitySearchDocument,
)
from combo.runtime_protocol.contracts import utc_now_text


@dataclass(frozen=True, slots=True)
class CapabilityBootstrapConfig:
    publisher_principal_id: str
    managed_source_prefix: str

    def __post_init__(self) -> None:
        if not self.publisher_principal_id.strip():
            raise ValueError("capability bootstrap publisher principal must not be empty")
        if not self.managed_source_prefix.strip():
            raise ValueError("capability bootstrap source prefix must not be empty")


class CapabilityBootstrapPublisher:
    """Synchronize build-owned sources through the normal immutable publication protocol."""

    def __init__(
        self,
        *,
        config: CapabilityBootstrapConfig,
        store: CapabilityStore,
        resolution_receipts: CapabilityResolutionReceiptStore,
        adapters: CapabilityAdapterRegistry,
    ) -> None:
        self._config = config
        self._store = store
        self._resolution_receipts = resolution_receipts
        self._adapters = adapters

    def synchronize(
        self,
        drafts: tuple[CapabilityDraft, ...],
        *,
        deactivate_removed_sources: bool = True,
    ) -> tuple[CapabilityRevision, ...]:
        self._validate_source_set(drafts)
        published = tuple(self._synchronize_draft(draft) for draft in drafts)
        if deactivate_removed_sources:
            self._deactivate_removed_sources(frozenset(draft.capability_id for draft in drafts))
        return published

    def _synchronize_draft(self, desired: CapabilityDraft) -> CapabilityRevision:
        draft = self._upsert_draft(desired)
        current_activation = self._activation_or_none(draft.capability_id)
        active = self._active_or_none(draft.capability_id)
        if (
            active is not None
            and active.revision.content_digest == draft.content_digest
            and active.revision.source_uri == draft.source_uri
            and active.revision.resolved_version == draft.resolved_version
            and active.revision.trust_level == draft.trust_level
        ):
            self._ensure_health(active.revision, evidence_digest=active.revision.validation_receipt_id)
            return active.revision

        reusable = self._store.revision_by_content_digest(
            draft.capability_id,
            draft.content_digest,
        )
        if reusable is not None:
            if (
                reusable.source_uri != draft.source_uri
                or reusable.resolved_version != draft.resolved_version
                or reusable.trust_level != draft.trust_level
            ):
                raise CapabilityConflictError(
                    "published capability content digest belongs to different immutable source metadata"
                )
            return self._reactivate_revision(reusable, current_activation)

        validation = self._adapters.validate(draft)
        self._store.record_validation(validation)
        if validation.status != "passed":
            diagnostics = "; ".join(str(item.get("message") or item) for item in validation.diagnostics)
            raise RuntimeError(f"build capability validation failed for {draft.capability_id}: {diagnostics}")

        latest = self._store.latest_revision(draft.capability_id)
        revision_number = 1 if latest is None else latest.revision + 1
        revision = CapabilityRevision(
            capability_id=draft.capability_id,
            kind=draft.kind,
            revision=revision_number,
            namespace=draft.namespace,
            resolved_version=draft.resolved_version,
            content_digest=draft.content_digest,
            source_uri=draft.source_uri,
            trust_level=draft.trust_level,
            dependency_digest=_digest(
                [item.model_dump(mode="json") for item in draft.content.dependencies]
            ),
            validation_receipt_id=validation.receipt_id,
            content=draft.content,
            published_by_principal_id=self._config.publisher_principal_id,
        )
        index = CapabilityIndexRevision(
            schema_version="capability_search_document.v1",
            source_capability_id=revision.capability_id,
            source_revision=revision.revision,
            source_digest=revision.content_digest,
            document=CapabilitySearchDocument(
                display_name=revision.content.display_name,
                description=revision.content.description,
                keywords=revision.content.keywords,
            ),
        )
        activation_revision = (
            1 if current_activation is None else current_activation.activation_revision + 1
        )
        activation = CapabilityActivation(
            capability_id=revision.capability_id,
            kind=revision.kind,
            activation_revision=activation_revision,
            status="active",
            revision=revision.revision,
            content_digest=revision.content_digest,
            index_revision_id=index.index_revision_id,
            changed_by_principal_id=self._config.publisher_principal_id,
        )
        health = CapabilityHealthReceipt(
            capability_id=revision.capability_id,
            kind=revision.kind,
            revision=revision.revision,
            content_digest=revision.content_digest,
            status="healthy",
            check_kind="static_validation",
            evidence_digest=_digest(validation.model_dump(mode="json")),
        )
        self._store.publish_active_revision(
            revision=revision,
            index=index,
            activation=activation,
            health=health,
            expected_draft_revision=draft.draft_revision,
            expected_activation_revision=(
                None if current_activation is None else current_activation.activation_revision
            ),
        )
        return revision

    def _reactivate_revision(
        self,
        revision: CapabilityRevision,
        current_activation: CapabilityActivation | None,
    ) -> CapabilityRevision:
        index = self._store.index_revision_for_source(
            revision.capability_id,
            revision.revision,
            revision.content_digest,
        )
        if index is None:
            index = CapabilityIndexRevision(
                schema_version="capability_search_document.v1",
                source_capability_id=revision.capability_id,
                source_revision=revision.revision,
                source_digest=revision.content_digest,
                document=CapabilitySearchDocument(
                    display_name=revision.content.display_name,
                    description=revision.content.description,
                    keywords=revision.content.keywords,
                ),
            )
            self._store.add_index_revision(index)
        activation_revision = 1 if current_activation is None else current_activation.activation_revision + 1
        self._store.set_activation(
            CapabilityActivation(
                capability_id=revision.capability_id,
                kind=revision.kind,
                activation_revision=activation_revision,
                status="active",
                revision=revision.revision,
                content_digest=revision.content_digest,
                index_revision_id=index.index_revision_id,
                changed_by_principal_id=self._config.publisher_principal_id,
            ),
            expected_activation_revision=(
                None if current_activation is None else current_activation.activation_revision
            ),
        )
        self._ensure_health(revision, evidence_digest=revision.validation_receipt_id)
        return revision

    def _upsert_draft(self, desired: CapabilityDraft) -> CapabilityDraft:
        if desired.updated_by_principal_id != self._config.publisher_principal_id:
            raise ValueError("build capability draft publisher differs from bootstrap configuration")
        if not desired.source_uri.startswith(self._config.managed_source_prefix):
            raise ValueError("build capability draft is outside the managed source namespace")
        try:
            current = self._store.draft(desired.capability_id)
        except CapabilityNotFoundError:
            return self._store.create_draft(desired)
        if (
            current.kind == desired.kind
            and current.namespace == desired.namespace
            and current.resolved_version == desired.resolved_version
            and current.source_uri == desired.source_uri
            and current.trust_level == desired.trust_level
            and current.content_digest == desired.content_digest
        ):
            return current
        replacement = CapabilityDraft.model_validate(
            {
                **desired.model_dump(mode="json"),
                "draft_revision": current.draft_revision + 1,
                "created_at": current.created_at,
                "updated_at": utc_now_text(),
            }
        )
        return self._store.replace_draft(
            replacement,
            expected_draft_revision=current.draft_revision,
        )

    def _active_or_none(self, capability_id: str):
        activation = self._activation_or_none(capability_id)
        if activation is None:
            return None
        if activation.status != "active":
            return None
        active = next(
            (
                item
                for item in self._store.active_capabilities()
                if item.revision.capability_id == capability_id
            ),
            None,
        )
        if active is None:
            raise CapabilityConflictError(
                "active capability pointer has no matching revision and index projection"
            )
        return active

    def _activation_or_none(self, capability_id: str) -> CapabilityActivation | None:
        try:
            return self._store.activation(capability_id)
        except CapabilityNotFoundError:
            return None

    def _ensure_health(self, revision: CapabilityRevision, *, evidence_digest: str) -> None:
        existing = self._resolution_receipts.latest_health(
            capability_id=revision.capability_id,
            revision=revision.revision,
            content_digest=revision.content_digest,
        )
        if existing is not None and existing.status == "healthy":
            return
        self._resolution_receipts.record_health(
            CapabilityHealthReceipt(
                capability_id=revision.capability_id,
                kind=revision.kind,
                revision=revision.revision,
                content_digest=revision.content_digest,
                status="healthy",
                check_kind="static_validation",
                evidence_digest=_digest(evidence_digest),
            )
        )

    def _deactivate_removed_sources(self, retained_ids: frozenset[str]) -> None:
        for item in self._store.active_capabilities():
            revision = item.revision
            if (
                revision.capability_id in retained_ids
                or not revision.source_uri.startswith(self._config.managed_source_prefix)
            ):
                continue
            current = item.activation
            self._store.set_activation(
                CapabilityActivation(
                    capability_id=revision.capability_id,
                    kind=revision.kind,
                    activation_revision=current.activation_revision + 1,
                    status="inactive",
                    changed_by_principal_id=self._config.publisher_principal_id,
                ),
                expected_activation_revision=current.activation_revision,
            )

    @staticmethod
    def _validate_source_set(drafts: tuple[CapabilityDraft, ...]) -> None:
        ids = tuple(item.capability_id for item in drafts)
        namespaces = tuple((item.kind, item.namespace) for item in drafts)
        if len(ids) != len(set(ids)):
            raise ValueError("build capability source contains duplicate capability IDs")
        if len(namespaces) != len(set(namespaces)):
            raise ValueError("build capability source contains duplicate namespaces")


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()
