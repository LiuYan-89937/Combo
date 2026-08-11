from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from agent_factory.runtime_protocol.contracts import FrozenProtocolModel, ProtocolModel, utc_now_text


ApplicationGenerationStatus = Literal["starting", "active", "quiescing", "closed", "crashed"]
CutoverStatus = Literal["preparing", "verifying", "committed", "failed", "rolled_back"]
CutoverStoreStatus = Literal["pending", "prepared", "verified", "committed", "failed", "rolled_back"]
RevocationKind = Literal["capability", "credential", "dependency_environment"]
DeliveryStatus = Literal["prepared", "finalizing", "committed", "compensating", "compensated", "failed"]
DeleteStatus = Literal["planned", "frozen", "deleting", "completed", "failed"]


class ApplicationGeneration(ProtocolModel):
    generation_id: str = Field(default_factory=lambda: uuid4().hex)
    generation: int = Field(ge=1)
    build_revision: str
    protocol_version: str
    schema_version: str
    owner_process_id: int = Field(ge=1)
    lease_expires_at: str
    status: ApplicationGenerationStatus = "starting"
    started_at: str = Field(default_factory=utc_now_text)
    updated_at: str = Field(default_factory=utc_now_text)
    closed_at: str | None = None

    @field_validator(
        "generation_id",
        "build_revision",
        "protocol_version",
        "schema_version",
        "lease_expires_at",
    )
    @classmethod
    def _required_generation_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("closed_at")
    @classmethod
    def _optional_closed_at(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @model_validator(mode="after")
    def _closed_state_is_consistent(self) -> "ApplicationGeneration":
        closed = self.status in {"closed", "crashed"}
        if closed != bool(self.closed_at):
            raise ValueError("closed generation status and closed_at must be set together")
        return self


class CutoverStoreRecord(ProtocolModel):
    store_id: str
    source_schema_version: str
    target_schema_version: str
    status: CutoverStoreStatus = "pending"
    receipt_id: str | None = None
    prepared_digest: str | None = None
    error_code: str | None = None
    updated_at: str = Field(default_factory=utc_now_text)

    @field_validator("store_id", "source_schema_version", "target_schema_version")
    @classmethod
    def _required_store_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("receipt_id", "prepared_digest", "error_code")
    @classmethod
    def _optional_store_text(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @model_validator(mode="after")
    def _status_evidence_is_consistent(self) -> "CutoverStoreRecord":
        if self.status in {"prepared", "verified", "committed"} and not self.receipt_id:
            raise ValueError(f"{self.status} store record requires receipt_id")
        if self.status == "failed" and not self.error_code:
            raise ValueError("failed store record requires error_code")
        return self


class CutoverManifest(ProtocolModel):
    cutover_id: str = Field(default_factory=lambda: uuid4().hex)
    manifest_revision: int = Field(default=1, ge=1)
    source_build_revision: str
    target_build_revision: str
    source_generation: int = Field(ge=1)
    target_generation: int = Field(ge=1)
    status: CutoverStatus = "preparing"
    stores: tuple[CutoverStoreRecord, ...]
    active_generation: int | None = Field(default=None, ge=1)
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = Field(default_factory=utc_now_text)
    committed_at: str | None = None

    @field_validator("cutover_id", "source_build_revision", "target_build_revision")
    @classmethod
    def _required_cutover_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("committed_at")
    @classmethod
    def _optional_committed_at(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @model_validator(mode="after")
    def _manifest_is_consistent(self) -> "CutoverManifest":
        store_ids = [item.store_id for item in self.stores]
        if len(store_ids) != len(set(store_ids)):
            raise ValueError("cutover store ids must be unique")
        if self.target_generation == self.source_generation:
            raise ValueError("cutover target generation must differ from source generation")
        if self.status == "committed":
            if self.active_generation != self.target_generation or not self.committed_at:
                raise ValueError("committed cutover must activate target generation and set committed_at")
            if any(item.status != "committed" for item in self.stores):
                raise ValueError("committed cutover requires every store to be committed")
        elif self.committed_at is not None:
            raise ValueError("non-committed cutover cannot set committed_at")
        return self


class RevocationRecord(FrozenProtocolModel):
    revocation_id: str = Field(default_factory=lambda: uuid4().hex)
    kind: RevocationKind
    subject_id: str
    subject_revision: int = Field(ge=1)
    reason: str
    revoked_by_principal_id: str
    revoked_at: str = Field(default_factory=utc_now_text)

    @field_validator("revocation_id", "subject_id", "reason", "revoked_by_principal_id")
    @classmethod
    def _required_revocation_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text


class DeliveryCommit(ProtocolModel):
    delivery_id: str = Field(default_factory=lambda: uuid4().hex)
    runtime_instance_id: str
    request_id: str
    task_revision: int = Field(ge=1)
    workspace_transaction_id: str
    artifact_ids: tuple[str, ...] = ()
    status: DeliveryStatus = "prepared"
    intent_digest: str
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = Field(default_factory=utc_now_text)
    terminal_at: str | None = None

    @field_validator(
        "delivery_id",
        "runtime_instance_id",
        "request_id",
        "workspace_transaction_id",
        "intent_digest",
    )
    @classmethod
    def _required_delivery_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("artifact_ids")
    @classmethod
    def _unique_artifact_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(str(value or "").strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("artifact ids must not be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("artifact ids must be unique")
        return normalized

    @field_validator("terminal_at")
    @classmethod
    def _optional_delivery_terminal(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @model_validator(mode="after")
    def _delivery_terminal_is_consistent(self) -> "DeliveryCommit":
        terminal = self.status in {"committed", "compensated", "failed"}
        if terminal != bool(self.terminal_at):
            raise ValueError("terminal delivery status and terminal_at must be set together")
        return self


class DeletePlan(ProtocolModel):
    delete_plan_id: str = Field(default_factory=lambda: uuid4().hex)
    principal_id: str
    root_kind: Literal["conversation", "attachment", "memory", "knowledge", "capability", "credential"]
    root_id: str
    status: DeleteStatus = "planned"
    direct_object_ids: tuple[str, ...] = ()
    derived_object_ids: tuple[str, ...] = ()
    protected_external_paths: tuple[str, ...] = ()
    failure_details: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = Field(default_factory=utc_now_text)
    terminal_at: str | None = None

    @field_validator("delete_plan_id", "principal_id", "root_id")
    @classmethod
    def _required_delete_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("direct_object_ids", "derived_object_ids", "protected_external_paths")
    @classmethod
    def _unique_delete_targets(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(str(value or "").strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("delete targets must not be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("delete targets must be unique")
        return normalized

    @field_validator("terminal_at")
    @classmethod
    def _optional_delete_terminal(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @model_validator(mode="after")
    def _delete_terminal_is_consistent(self) -> "DeletePlan":
        terminal = self.status in {"completed", "failed"}
        if terminal != bool(self.terminal_at):
            raise ValueError("terminal delete status and terminal_at must be set together")
        if self.status == "failed" and not self.failure_details:
            raise ValueError("failed delete plan requires failure_details")
        return self
