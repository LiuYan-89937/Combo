from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.runtime_kernel.constants import CHECKPOINT_SCHEMA_VERSION, RUNTIME_KERNEL_VERSION


class CheckpointRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str = Field(default_factory=lambda: uuid4().hex)
    schema_version: str = CHECKPOINT_SCHEMA_VERSION
    runtime_kernel_version: str = RUNTIME_KERNEL_VERSION
    run_ref: dict[str, Any] = Field(default_factory=dict)
    execution_ref: dict[str, Any] = Field(default_factory=dict)
    state_snapshot: dict[str, Any] = Field(default_factory=dict)
    interrupt_snapshot: dict[str, Any] = Field(default_factory=dict)
    observability_ref: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(
        default_factory=lambda: {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "reason": "unspecified",
            "created_by": "runtime_kernel",
        }
    )
