from __future__ import annotations

from hashlib import sha256
from typing import Literal

from pydantic import Field, field_validator, model_validator

from combo.runtime_protocol.contracts import FrozenProtocolModel, utc_now_text


MemoryScope = Literal["user", "workspace"]
MemoryKind = Literal["constraint", "preference", "decision", "fact", "artifact"]
MemoryStatus = Literal["active", "deleted"]


class MemoryRevision(FrozenProtocolModel):
    memory_id: str
    revision: int = Field(ge=1)
    principal_id: str
    scope: MemoryScope
    workspace_id: str | None = None
    kind: MemoryKind
    status: MemoryStatus = "active"
    content: str
    content_digest: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_session_id: str | None
    source_turn_id: str | None
    created_by_runtime_instance_id: str | None
    created_at: str = Field(default_factory=utc_now_text)

    @field_validator(
        "memory_id",
        "principal_id",
        "content",
    )
    @classmethod
    def _required_text(cls, value: str, info: object) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError(f"{getattr(info, 'field_name', 'value')} must not be empty")
        return text

    @field_validator("workspace_id")
    @classmethod
    def _optional_workspace(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @field_validator(
        "source_session_id",
        "source_turn_id",
        "created_by_runtime_instance_id",
    )
    @classmethod
    def _optional_provenance(cls, value: str | None) -> str | None:
        text = str(value or "").strip()
        return text or None

    @model_validator(mode="after")
    def _scope_and_digest_match(self) -> "MemoryRevision":
        if self.scope == "workspace" and self.workspace_id is None:
            raise ValueError("workspace memory requires workspace_id")
        if self.scope == "user" and self.workspace_id is not None:
            raise ValueError("user memory cannot carry workspace_id")
        provenance = (
            self.source_session_id,
            self.source_turn_id,
            self.created_by_runtime_instance_id,
        )
        if any(value is None for value in provenance) and any(value is not None for value in provenance):
            raise ValueError("memory provenance must be either complete or detached")
        if self.status == "active" and self.created_by_runtime_instance_id is None:
            raise ValueError("active memory requires runtime provenance")
        expected = sha256(self.content.encode("utf-8")).hexdigest()
        if self.content_digest and self.content_digest != expected:
            raise ValueError("memory content_digest does not match content")
        object.__setattr__(self, "content_digest", expected)
        return self
