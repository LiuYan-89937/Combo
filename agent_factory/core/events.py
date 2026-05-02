from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import ConfigDict, Field

from agent_factory.core.types import JsonDumpMixin


class EventStatus(StrEnum):
    STARTED = "started"
    PROGRESS = "progress"
    COMPLETED = "completed"
    WARNING = "warning"
    FAILED = "failed"


class FactoryEvent(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    stage: str
    status: EventStatus
    title: str
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    artifact_path: str | None = None
