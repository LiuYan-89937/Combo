from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: uuid4().hex)
    trace_id: str
    run_id: str
    event_type: str
    node_id: str | None = None
    subgraph_id: str | None = None
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TraceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    span_id: str = Field(default_factory=lambda: uuid4().hex)
    parent_span_id: str | None = None
    span_type: str
    name: str
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    status: Literal["started", "completed", "failed"] = "started"
    metadata: dict[str, Any] = Field(default_factory=dict)


class TraceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str
    run_id: str
    agent_id: str
    pattern_id: str
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    status: str = "started"
    root_span_id: str = Field(default_factory=lambda: uuid4().hex)
    node_count: int = 0
    subgraph_count: int = 0
    tool_call_count: int = 0
    interrupt_count: int = 0
    resume_count: int = 0
    turn_count: int = 0
    total_latency_ms: int = 0
