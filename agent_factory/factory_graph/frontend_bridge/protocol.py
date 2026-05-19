from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


FACTORY_FRONTEND_EVENT_PROTOCOL_VERSION = "factory_frontend.v1"


FactoryFrontendCommandType = Literal[
    "start_session",
    "list_sessions",
    "switch_session",
    "new_session",
    "set_mode",
    "send_message",
    "rerun_from_stage",
    "list_agent_packages",
    "select_agent_package",
    "delete_agent_package",
    "list_agent_package_sessions",
    "run_agent_package",
    "resume_interrupt",
    "set_options",
    "shutdown",
]

FactoryFrontendEventType = Literal[
    "runtime_ready",
    "runtime_options_changed",
    "session_started",
    "session_switched",
    "sessions_listed",
    "agent_packages_listed",
    "agent_package_selected",
    "agent_package_deleted",
    "agent_package_sessions_listed",
    "mode_changed",
    "run_started",
    "run_completed",
    "run_failed",
    "stage_started",
    "stage_completed",
    "stage_failed",
    "node_started",
    "node_progress",
    "node_completed",
    "node_failed",
    "model_call_started",
    "model_stream_delta",
    "model_message_completed",
    "model_call_completed",
    "model_call_failed",
    "tool_call_proposed",
    "tool_approval_requested",
    "tool_approval_resolved",
    "tool_call_started",
    "tool_call_completed",
    "tool_call_failed",
    "tool_observation_available",
    "memory_write_queued",
    "memory_write_queued_failed",
    "memory_segment_prepared",
    "memory_extraction_completed",
    "memory_write_completed",
    "memory_write_failed",
    "memory_retrieval_completed",
    "memory_injection_completed",
    "interrupt_requested",
    "runtime_paused",
    "runtime_resumed",
    "trace_snapshot",
    "debug_patch",
    "error",
]

FactoryMode = Literal["chat", "create_agent", "agent_package"]


class FactoryFrontendCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: FactoryFrontendCommandType
    request_id: str | None = None
    session_id: str | None = None
    resume_latest: bool = False
    mode: FactoryMode | None = None
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)


class FactoryFrontendEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    protocol_version: str = FACTORY_FRONTEND_EVENT_PROTOCOL_VERSION
    event_type: FactoryFrontendEventType
    producer_type: str = "factory_runtime"
    request_id: str | None = None
    run_id: str | None = None
    session_id: str | None = None
    thread_id: str | None = None
    mode: FactoryMode | None = None
    graph_id: str | None = None
    node_id: str | None = None
    node_label: str | None = None
    node_kind: str | None = None
    stage_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    sequence: int = 0
    timestamp: str
    severity: str | None = None
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


def event(
    event_type: FactoryFrontendEventType,
    *,
    request_id: str | None = None,
    protocol_version: str | None = None,
    producer_type: str | None = None,
    session_id: str | None = None,
    thread_id: str | None = None,
    mode: FactoryMode | None = None,
    node_id: str | None = None,
    node_label: str | None = None,
    node_kind: str | None = None,
    stage_id: str | None = None,
    run_id: str | None = None,
    graph_id: str | None = None,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    sequence: int = 0,
    timestamp: str | None = None,
    severity: str | None = None,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> FactoryFrontendEvent:
    from datetime import UTC, datetime
    import uuid

    return FactoryFrontendEvent(
        event_id=uuid.uuid4().hex,
        protocol_version=protocol_version or FACTORY_FRONTEND_EVENT_PROTOCOL_VERSION,
        event_type=event_type,
        producer_type=producer_type or "factory_runtime",
        request_id=request_id,
        run_id=run_id,
        session_id=session_id,
        thread_id=thread_id,
        mode=mode,
        graph_id=graph_id,
        node_id=node_id,
        node_label=node_label,
        node_kind=node_kind,
        stage_id=stage_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        sequence=sequence,
        timestamp=timestamp or datetime.now(UTC).isoformat(),
        severity=severity,
        message=message,
        payload=payload or {},
    )
