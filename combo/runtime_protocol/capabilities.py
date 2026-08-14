from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json
from typing import Literal
from uuid import uuid4

from pydantic import Field, JsonValue, field_validator, model_validator

from combo.runtime_protocol.contracts import (
    CapabilityKind,
    DependencyEnvironmentRef,
    FrozenProtocolModel,
    ProtocolModel,
    utc_now_text,
)


CapabilityTrustLevel = Literal["builtin", "local_user", "verified_external", "untrusted_external"]
CapabilityValidationStatus = Literal["passed", "failed"]
CapabilityHealthStatus = Literal["healthy", "unhealthy"]
DependencyEnvironmentStatus = Literal["ready", "invalid"]


class CapabilityResourceRef(FrozenProtocolModel):
    resource_id: str
    revision: int = Field(ge=1)
    purpose: str

    @field_validator("resource_id", "purpose")
    @classmethod
    def _required_resource_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text


class CapabilityDependencyRef(FrozenProtocolModel):
    capability_id: str
    kind: CapabilityKind
    version_constraint: str
    required: bool = True

    @field_validator("capability_id", "version_constraint")
    @classmethod
    def _required_dependency_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text


class CapabilityContent(FrozenProtocolModel):
    display_name: str
    description: str
    keywords: tuple[str, ...] = ()
    definition_schema: str
    definition: dict[str, JsonValue]
    dependencies: tuple[CapabilityDependencyRef, ...] = ()
    resources: tuple[CapabilityResourceRef, ...] = ()

    @field_validator("display_name", "description", "definition_schema")
    @classmethod
    def _required_content_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("keywords")
    @classmethod
    def _unique_keywords(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "").strip()
            if not text:
                raise ValueError("capability keyword must not be empty")
            key = text.casefold()
            if key not in seen:
                seen.add(key)
                normalized.append(text)
        return tuple(normalized)

    @model_validator(mode="after")
    def _dependency_and_resource_ids_are_unique(self) -> "CapabilityContent":
        dependency_ids = [item.capability_id for item in self.dependencies]
        if len(dependency_ids) != len(set(dependency_ids)):
            raise ValueError("capability dependencies must have unique capability_id values")
        resource_ids = [(item.resource_id, item.revision, item.purpose) for item in self.resources]
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("capability resources must be unique")
        return self


class CapabilityDraft(ProtocolModel):
    capability_id: str
    kind: CapabilityKind
    draft_revision: int = Field(ge=1)
    namespace: str
    resolved_version: str
    source_uri: str
    trust_level: CapabilityTrustLevel
    content: CapabilityContent
    content_digest: str = ""
    updated_by_principal_id: str
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = Field(default_factory=utc_now_text)

    @field_validator(
        "capability_id",
        "namespace",
        "resolved_version",
        "source_uri",
        "updated_by_principal_id",
    )
    @classmethod
    def _required_draft_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @model_validator(mode="after")
    def _digest_matches_content(self) -> "CapabilityDraft":
        expected = _capability_content_digest(
            kind=self.kind,
            namespace=self.namespace,
            resolved_version=self.resolved_version,
            content=self.content,
        )
        if self.content_digest and self.content_digest != expected:
            raise ValueError("capability draft content_digest does not match content")
        self.content_digest = expected
        return self


class CapabilityRevision(FrozenProtocolModel):
    capability_id: str
    kind: CapabilityKind
    revision: int = Field(ge=1)
    namespace: str
    resolved_version: str
    content_digest: str
    source_uri: str
    trust_level: CapabilityTrustLevel
    dependency_digest: str
    license_id: str | None = None
    validation_receipt_id: str
    content: CapabilityContent
    published_by_principal_id: str
    created_at: str = Field(default_factory=utc_now_text)
    published_at: str = Field(default_factory=utc_now_text)

    @field_validator(
        "capability_id",
        "namespace",
        "resolved_version",
        "content_digest",
        "dependency_digest",
        "source_uri",
        "validation_receipt_id",
        "published_by_principal_id",
        "published_at",
    )
    @classmethod
    def _required_revision_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("license_id")
    @classmethod
    def _optional_revision_text(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @model_validator(mode="after")
    def _published_digest_matches_content(self) -> "CapabilityRevision":
        expected = _capability_content_digest(
            kind=self.kind,
            namespace=self.namespace,
            resolved_version=self.resolved_version,
            content=self.content,
        )
        if self.content_digest != expected:
            raise ValueError("capability revision content_digest does not match content")
        return self


class CapabilityValidationReceipt(FrozenProtocolModel):
    receipt_id: str = Field(default_factory=lambda: uuid4().hex)
    capability_id: str
    kind: CapabilityKind
    draft_revision: int = Field(ge=1)
    content_digest: str
    adapter_id: str
    adapter_revision: str
    status: CapabilityValidationStatus
    diagnostics: tuple[dict[str, JsonValue], ...] = ()
    created_at: str = Field(default_factory=utc_now_text)

    @field_validator(
        "receipt_id",
        "capability_id",
        "content_digest",
        "adapter_id",
        "adapter_revision",
        "created_at",
    )
    @classmethod
    def _required_validation_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text


class CapabilityActivation(FrozenProtocolModel):
    capability_id: str
    kind: CapabilityKind
    activation_revision: int = Field(ge=1)
    status: Literal["active", "inactive"]
    revision: int | None = Field(default=None, ge=1)
    content_digest: str | None = None
    index_revision_id: str | None = None
    changed_by_principal_id: str
    changed_at: str = Field(default_factory=utc_now_text)

    @field_validator(
        "capability_id",
        "changed_by_principal_id",
        "changed_at",
    )
    @classmethod
    def _required_activation_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("content_digest", "index_revision_id")
    @classmethod
    def _optional_activation_text(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @model_validator(mode="after")
    def _status_matches_pointer(self) -> "CapabilityActivation":
        pointer = (self.revision, self.content_digest, self.index_revision_id)
        if self.status == "active" and any(value is None for value in pointer):
            raise ValueError("active capability activation requires revision, digest, and index revision")
        if self.status == "inactive" and any(value is not None for value in pointer):
            raise ValueError("inactive capability activation cannot retain an active pointer")
        return self


class CapabilitySearchDocument(FrozenProtocolModel):
    schema_version: Literal["capability_search_document.v1"] = "capability_search_document.v1"
    display_name: str
    description: str
    keywords: tuple[str, ...] = ()

    @field_validator("display_name", "description")
    @classmethod
    def _required_document_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("keywords")
    @classmethod
    def _document_keywords_are_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(str(value or "").strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("capability search document keywords must not be empty")
        if len({value.casefold() for value in normalized}) != len(normalized):
            raise ValueError("capability search document keywords must be case-insensitively unique")
        return normalized


class CapabilityIndexRevision(FrozenProtocolModel):
    index_revision_id: str = Field(default_factory=lambda: uuid4().hex)
    schema_version: str
    source_capability_id: str
    source_revision: int = Field(ge=1)
    source_digest: str
    document: CapabilitySearchDocument
    index_digest: str = ""
    created_at: str = Field(default_factory=utc_now_text)

    @field_validator(
        "index_revision_id",
        "schema_version",
        "source_capability_id",
        "source_digest",
        "index_digest",
    )
    @classmethod
    def _required_index_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @model_validator(mode="after")
    def _index_digest_matches_document(self) -> "CapabilityIndexRevision":
        expected = _canonical_digest(self.document.model_dump(mode="json"))
        if self.index_digest and self.index_digest != expected:
            raise ValueError("capability index digest does not match search document")
        object.__setattr__(self, "index_digest", expected)
        return self


class CapabilityHealthReceipt(FrozenProtocolModel):
    receipt_id: str = Field(default_factory=lambda: uuid4().hex)
    capability_id: str
    kind: CapabilityKind
    revision: int = Field(ge=1)
    content_digest: str
    status: CapabilityHealthStatus
    check_kind: Literal["static_validation", "isolated_probe", "connection", "dependency_build"]
    evidence_digest: str
    checked_at: str = Field(default_factory=utc_now_text)
    valid_until: str | None = None

    @field_validator(
        "receipt_id",
        "capability_id",
        "content_digest",
        "evidence_digest",
    )
    @classmethod
    def _required_health_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("checked_at")
    @classmethod
    def _checked_at_is_utc(cls, value: str) -> str:
        return _utc_timestamp(value, "checked_at")

    @field_validator("valid_until")
    @classmethod
    def _optional_health_timestamp(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return _utc_timestamp(text, "valid_until") if text else None

    @model_validator(mode="after")
    def _validity_window_is_forward(self) -> "CapabilityHealthReceipt":
        if self.valid_until is not None and self.valid_until <= self.checked_at:
            raise ValueError("capability health valid_until must be later than checked_at")
        return self


class DependencyEnvironmentReceipt(FrozenProtocolModel):
    receipt_id: str = Field(default_factory=lambda: uuid4().hex)
    status: DependencyEnvironmentStatus
    environment: "DependencyEnvironmentRef"
    dependency_closure_digest: str = ""
    projection_digest: str
    created_at: str = Field(default_factory=utc_now_text)

    @field_validator("receipt_id", "projection_digest")
    @classmethod
    def _required_environment_receipt_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("created_at")
    @classmethod
    def _created_at_is_utc(cls, value: str) -> str:
        return _utc_timestamp(value, "created_at")

    @model_validator(mode="after")
    def _closure_digest_matches_environment(self) -> "DependencyEnvironmentReceipt":
        expected = _canonical_digest(
            [
                item.model_dump(mode="json")
                for item in sorted(
                    self.environment.capability_refs,
                    key=lambda item: (item.capability_id, item.revision, item.content_digest),
                )
            ]
        )
        if self.dependency_closure_digest and self.dependency_closure_digest != expected:
            raise ValueError("dependency environment receipt closure digest does not match references")
        object.__setattr__(self, "dependency_closure_digest", expected)
        return self


class CapabilityTombstone(FrozenProtocolModel):
    tombstone_id: str = Field(default_factory=lambda: uuid4().hex)
    capability_id: str
    kind: CapabilityKind
    last_revision: int = Field(ge=1)
    content_digest: str
    deleted_by_principal_id: str
    reason: str
    deleted_at: str = Field(default_factory=utc_now_text)

    @field_validator("tombstone_id", "capability_id", "content_digest", "deleted_by_principal_id", "reason")
    @classmethod
    def _required_tombstone_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text


def _capability_content_digest(
    *,
    kind: CapabilityKind,
    namespace: str,
    resolved_version: str,
    content: CapabilityContent,
) -> str:
    payload = {
        "kind": kind,
        "namespace": str(namespace).strip(),
        "resolved_version": str(resolved_version).strip(),
        "content": content.model_dump(mode="json"),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _utc_timestamp(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(UTC).isoformat()
