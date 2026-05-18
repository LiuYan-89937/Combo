from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


MemoryScope = Literal["factory", "agent", "user"]
MemoryKind = Literal["fact", "preference", "decision", "constraint", "artifact"]
MemoryIntent = Literal["explicit_remember", "explicit_forget", "explicit_update", "none"]
MemoryExtractionActionType = Literal["add", "update", "delete", "noop"]
MemoryWriteStatus = Literal["queued", "queued_failed", "completed", "failed", "noop"]


class MemoryIntentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: MemoryIntent
    confidence: float = Field(ge=0.0, le=1.0)
    target_text: str = ""
    reason: str = ""


class MemoryExtractionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: MemoryExtractionActionType
    kind: MemoryKind | None = None
    content: str = ""
    reason: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    merge_target_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryExtractionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["complete", "noop", "failed"]
    actions: list[MemoryExtractionAction] = Field(default_factory=list, max_length=8)
    notes: list[str] = Field(default_factory=list, max_length=8)


class MemoryContextItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_id: str
    kind: MemoryKind
    content: str
    score: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    namespace: tuple[str, ...] = Field(default_factory=tuple)
    updated_at: str | None = None


class MemoryContextPack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["memory_context.v0"] = "memory_context.v0"
    namespace: tuple[str, ...]
    query: str
    items: list[MemoryContextItem] = Field(default_factory=list)
    token_estimate: int = 0
    report: dict[str, Any] = Field(default_factory=dict)


class MemoryWriteJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(default_factory=lambda: uuid4().hex)
    scope: MemoryScope
    namespace: tuple[str, ...]
    source: dict[str, Any] = Field(default_factory=dict)
    message_range: dict[str, int] = Field(default_factory=dict)
    messages_delta: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    def journal_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload.pop("messages_delta", None)
        return payload


class MemoryWriteReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: MemoryWriteStatus
    namespace: tuple[str, ...]
    action_counts: dict[str, int] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class MemoryInjectionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["injected", "skipped", "failed"]
    namespace: tuple[str, ...] = Field(default_factory=tuple)
    item_count: int = 0
    token_estimate: int = 0
    min_score: float = 0.0
    error: str | None = None
    duration_ms: int = 0
