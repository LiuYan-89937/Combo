from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


FactoryFrontendCommandType = Literal[
    "start_session",
    "list_sessions",
    "switch_session",
    "new_session",
    "set_mode",
    "send_message",
    "resume_interrupt",
    "set_options",
    "shutdown",
]

FactoryFrontendEventType = Literal[
    "ready",
    "session_changed",
    "sessions_listed",
    "mode_changed",
    "run_started",
    "stage_started",
    "stage_delta",
    "model_token",
    "tool_call_requested",
    "tool_result",
    "interrupt_requested",
    "resource_input_requested",
    "stage_completed",
    "run_completed",
    "run_failed",
    "error",
]

FactoryMode = Literal["chat", "create_agent"]


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

    type: FactoryFrontendEventType
    request_id: str | None = None
    session_id: str | None = None
    mode: FactoryMode | None = None
    node_id: str | None = None
    stage_id: str | None = None
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


def event(
    event_type: FactoryFrontendEventType,
    *,
    request_id: str | None = None,
    session_id: str | None = None,
    mode: FactoryMode | None = None,
    node_id: str | None = None,
    stage_id: str | None = None,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> FactoryFrontendEvent:
    return FactoryFrontendEvent(
        type=event_type,
        request_id=request_id,
        session_id=session_id,
        mode=mode,
        node_id=node_id,
        stage_id=stage_id,
        message=message,
        payload=payload or {},
    )

