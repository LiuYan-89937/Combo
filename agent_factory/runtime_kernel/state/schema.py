from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.runtime_kernel.constants import RUNTIME_KERNEL_VERSION, RUNTIME_STATE_SCHEMA_VERSION
from agent_factory.runtime_kernel.state.messages import MessageRecord


class RunState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: uuid4().hex)
    agent_id: str = "unknown-agent"
    session_id: str = "default"
    pattern_id: str = "unknown-pattern"
    pattern_version: int = 1
    runtime_kernel_version: str = RUNTIME_KERNEL_VERSION
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ConversationState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[MessageRecord] = Field(default_factory=list)
    current_user_input: str | None = None
    current_user_input_id: str | None = None
    assistant_draft: str | None = None
    final_answer: str | None = None
    clarification_question: str | None = None
    turn_index: int = 0


class ContextState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_refs: list[str] = Field(default_factory=list)
    model_context: dict[str, Any] = Field(default_factory=dict)
    tool_context: dict[str, Any] = Field(default_factory=dict)
    hidden_context: dict[str, Any] = Field(default_factory=dict)
    compression_applied: bool = False
    token_budget: dict[str, Any] = Field(default_factory=dict)
    assembly_log: list[str] = Field(default_factory=list)


class ToolState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available_tools: list[str] = Field(default_factory=list)
    pending_tool_call: dict[str, Any] | None = None
    pending_tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    tool_failures: list[dict[str, Any]] = Field(default_factory=list)
    approval_queue: list[dict[str, Any]] = Field(default_factory=list)
    last_tool_result: dict[str, Any] | None = None


class MemoryState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    short_term_snapshot: dict[str, Any] = Field(default_factory=dict)
    summary_memory: str | None = None
    user_profile: dict[str, Any] = Field(default_factory=dict)
    recall_items: list[dict[str, Any]] = Field(default_factory=list)
    pending_write: list[dict[str, Any]] = Field(default_factory=list)
    write_applied: bool = False


class KnowledgeState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_query: str | None = None
    retrieved_items: list[dict[str, Any]] = Field(default_factory=list)
    ranked_items: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[dict[str, Any]] = Field(default_factory=list)
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_level: str = "normal"
    blocked: bool = False
    block_reason: str | None = None
    approval_required: bool = False
    interrupt_required: bool = False
    interrupted: bool = False
    interrupt_type: str | None = None
    refusal_reason: str | None = None
    checks: list[dict[str, Any]] = Field(default_factory=list)


class ExecutionState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_node: str | None = None
    current_subgraph: str | None = None
    subgraph_depth: int = 0
    route_decision: str | None = None
    turn_count: int = 0
    max_turns: int = 16
    retry_count: int = 0
    max_retries: int = 2
    max_subgraph_depth: int = 4
    timeout_seconds: int = 60
    interrupted: bool = False
    interrupt_payload: dict[str, Any] = Field(default_factory=dict)
    resume_payload: dict[str, Any] = Field(default_factory=dict)
    resume_token: str | None = None
    finished: bool = False
    finish_status: str | None = None
    last_error: str | None = None
    last_error_location: str | None = None


class RuntimeConfigState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_config: dict[str, Any] = Field(default_factory=dict)
    agent_config: dict[str, Any] = Field(default_factory=dict)
    session_config: dict[str, Any] = Field(default_factory=dict)


class ObservabilityState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(default_factory=lambda: uuid4().hex)
    span_stack: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    debug_refs: list[dict[str, Any]] = Field(default_factory=list)


class RuntimeState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = RUNTIME_STATE_SCHEMA_VERSION
    run: RunState = Field(default_factory=RunState)
    runtime_config: RuntimeConfigState = Field(default_factory=RuntimeConfigState)
    conversation: ConversationState = Field(default_factory=ConversationState)
    context: ContextState = Field(default_factory=ContextState)
    tools: ToolState = Field(default_factory=ToolState)
    memory: MemoryState = Field(default_factory=MemoryState)
    knowledge: KnowledgeState = Field(default_factory=KnowledgeState)
    policy: PolicyState = Field(default_factory=PolicyState)
    execution: ExecutionState = Field(default_factory=ExecutionState)
    observability: ObservabilityState = Field(default_factory=ObservabilityState)
