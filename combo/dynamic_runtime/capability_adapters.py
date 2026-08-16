from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Protocol

from pydantic import Field, JsonValue, field_validator, model_validator

from combo.runtime_protocol import (
    CapabilityDependencyRef,
    CapabilityDraft,
    CapabilityKind,
    CapabilityResourceRef,
    CapabilityRevision,
    CapabilityValidationReceipt,
)
from combo.runtime_protocol.contracts import FrozenProtocolModel


DiagnosticSeverity = Literal["info", "warning", "error"]


class CapabilityValidationDiagnostic(FrozenProtocolModel):
    code: str
    severity: DiagnosticSeverity
    message: str
    path: tuple[str, ...] = ()
    details: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("code", "message")
    @classmethod
    def _required_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("path")
    @classmethod
    def _path_segments_are_present(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(str(value or "").strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("diagnostic path segments must not be empty")
        return normalized


class CapabilityAdapterValidation(FrozenProtocolModel):
    capability_id: str
    kind: CapabilityKind
    draft_revision: int = Field(ge=1)
    content_digest: str
    diagnostics: tuple[CapabilityValidationDiagnostic, ...] = ()

    @field_validator("capability_id", "content_digest")
    @classmethod
    def _required_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @property
    def passed(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)


class CapabilityRuntimeProjection(FrozenProtocolModel):
    capability_id: str
    kind: CapabilityKind
    revision: int = Field(ge=1)
    content_digest: str
    model_prompt_fragments: tuple[str, ...] = ()
    model_tool_ids: tuple[str, ...] = ()
    dependencies: tuple[CapabilityDependencyRef, ...] = ()
    resources: tuple[CapabilityResourceRef, ...] = ()
    runtime_definition_schema: str
    runtime_definition: dict[str, JsonValue]

    @field_validator(
        "capability_id",
        "content_digest",
        "runtime_definition_schema",
    )
    @classmethod
    def _required_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            field_name = getattr(info, "field_name", "value")
            raise ValueError(f"{field_name} must not be empty")
        return text

    @field_validator("model_prompt_fragments", "model_tool_ids")
    @classmethod
    def _projection_text_is_unique(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(str(value or "").strip() for value in values)
        if any(not value for value in normalized):
            raise ValueError("runtime projection values must not be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("runtime projection values must be unique")
        return normalized

    @model_validator(mode="after")
    def _tool_surface_matches_kind(self) -> "CapabilityRuntimeProjection":
        if self.kind not in {"tool", "mcp_tool"} and self.model_tool_ids:
            raise ValueError("only tool and mcp_tool projections may expose model tools")
        return self


class CapabilityAdapter(Protocol):
    @property
    def kind(self) -> CapabilityKind:
        ...

    @property
    def adapter_id(self) -> str:
        ...

    @property
    def adapter_revision(self) -> str:
        ...

    def validate(self, draft: CapabilityDraft) -> CapabilityAdapterValidation:
        ...

    def project(self, revision: CapabilityRevision) -> CapabilityRuntimeProjection:
        ...


@dataclass(frozen=True, slots=True)
class CapabilityAdapterRegistry:
    _adapters: Mapping[CapabilityKind, CapabilityAdapter]

    @classmethod
    def build(cls, adapters: Iterable[CapabilityAdapter]) -> "CapabilityAdapterRegistry":
        registered: dict[CapabilityKind, CapabilityAdapter] = {}
        for adapter in adapters:
            if adapter.kind in registered:
                raise ValueError(f"duplicate capability adapter for kind: {adapter.kind}")
            if not str(adapter.adapter_id or "").strip():
                raise ValueError(f"capability adapter for {adapter.kind} requires adapter_id")
            if not str(adapter.adapter_revision or "").strip():
                raise ValueError(f"capability adapter for {adapter.kind} requires adapter_revision")
            registered[adapter.kind] = adapter
        return cls(_adapters=MappingProxyType(registered))

    def require_complete(self) -> None:
        required: set[CapabilityKind] = {"skill", "tool", "dependency"}
        missing = required - set(self._adapters)
        if missing:
            raise RuntimeError("missing capability adapters: " + ", ".join(sorted(missing)))

    def validate(self, draft: CapabilityDraft) -> CapabilityValidationReceipt:
        adapter = self._adapter(draft.kind)
        result = adapter.validate(draft)
        if (
            result.capability_id != draft.capability_id
            or result.kind != draft.kind
            or result.draft_revision != draft.draft_revision
            or result.content_digest != draft.content_digest
        ):
            raise RuntimeError("capability adapter validation result does not match draft identity")
        return CapabilityValidationReceipt(
            capability_id=draft.capability_id,
            kind=draft.kind,
            draft_revision=draft.draft_revision,
            content_digest=draft.content_digest,
            adapter_id=adapter.adapter_id,
            adapter_revision=adapter.adapter_revision,
            status="passed" if result.passed else "failed",
            diagnostics=tuple(item.model_dump(mode="json") for item in result.diagnostics),
        )

    def project(self, revision: CapabilityRevision) -> CapabilityRuntimeProjection:
        projection = self._adapter(revision.kind).project(revision)
        if (
            projection.capability_id != revision.capability_id
            or projection.kind != revision.kind
            or projection.revision != revision.revision
            or projection.content_digest != revision.content_digest
        ):
            raise RuntimeError("capability adapter projection does not match revision identity")
        return projection

    def adapter(self, kind: CapabilityKind) -> CapabilityAdapter:
        return self._adapter(kind)

    def _adapter(self, kind: CapabilityKind) -> CapabilityAdapter:
        adapter = self._adapters.get(kind)
        if adapter is None:
            raise LookupError(f"capability adapter is not registered: {kind}")
        return adapter
