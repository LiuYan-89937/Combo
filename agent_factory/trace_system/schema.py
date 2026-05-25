from __future__ import annotations

from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TraceContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str = "/runtime/trace"
    max_inline_payload_chars: int = Field(default=12000, ge=1000)

    @field_validator("root")
    @classmethod
    def _root_is_safe(cls, value: str) -> str:
        raw = str(value).strip()
        if not raw:
            raise ValueError("trace root must not be empty")
        path = PurePosixPath(raw)
        if path == PurePosixPath("/"):
            raise ValueError("trace root must not point at the container root")
        if any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError("trace root must not contain empty, current, or parent segments")
        return raw


class TraceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["trace_manifest.v0"] = "trace_manifest.v0"
    trace_id: str
    run_id: str | None = None
    agent_id: str | None = None
    session_id: str | None = None
    package_id: str | None = None
    producer_type: str | None = None
    status: Literal["started", "running", "completed", "failed"] = "started"
    started_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    finished_at: str | None = None
    counters: dict[str, int] = Field(default_factory=dict)


class TraceFactRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["trace_fact.v0"] = "trace_fact.v0"
    record_id: str = Field(default_factory=lambda: uuid4().hex)
    trace_id: str
    run_id: str
    record_type: Literal["event", "span_started", "span_finished", "diagnostic"]
    event_type: str
    span_id: str | None = None
    parent_span_id: str | None = None
    span_kind: str | None = None
    node_id: str | None = None
    tool_call_id: str | None = None
    model_role: str | None = None
    status: str | None = None
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)


class TraceReferenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["trace_reference.v0"] = "trace_reference.v0"
    reference_id: str = Field(default_factory=lambda: uuid4().hex)
    trace_id: str
    run_id: str
    span_id: str | None = None
    reference_type: str
    uri: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=utc_now)
