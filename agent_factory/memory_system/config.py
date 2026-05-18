from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MemoryStoreRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend: Literal["sqlite", "memory"] = "sqlite"
    path: str = ".agent_runtime/memory/agent.sqlite"


class MemoryRankingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_items_total: int = Field(default=8, ge=1, le=32)
    max_tokens_total: int = Field(default=1200, ge=100, le=8000)
    min_score: float = Field(default=0.55, ge=0.0, le=1.0)
    per_kind_limits: dict[str, int] = Field(
        default_factory=lambda: {
            "constraint": 3,
            "preference": 3,
            "decision": 2,
            "fact": 2,
            "artifact": 1,
        }
    )


class MemoryBackgroundConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    journal_root: str = ".agent_runtime/memory/jobs"
    max_pending_jobs: int = Field(default=32, ge=1, le=256)
    concurrency: int = Field(default=1, ge=1, le=1)
    queue_full_policy: Literal["reject_new_when_full"] = "reject_new_when_full"


class MemorySystemConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["memory_system.v0"] = "memory_system.v0"
    enabled: bool = True
    write_enabled: bool = True
    injection_enabled: bool = True
    store: MemoryStoreRuntimeConfig = Field(default_factory=MemoryStoreRuntimeConfig)
    ranking: MemoryRankingConfig = Field(default_factory=MemoryRankingConfig)
    background: MemoryBackgroundConfig = Field(default_factory=MemoryBackgroundConfig)


def default_agent_memory_config() -> MemorySystemConfig:
    return MemorySystemConfig()


def default_factory_memory_config(project_root: str | Path = ".") -> MemorySystemConfig:
    root = Path(project_root)
    return MemorySystemConfig(
        store=MemoryStoreRuntimeConfig(
            backend="sqlite",
            path=str(root / ".agentfactory/memory/factory.sqlite"),
        ),
        background=MemoryBackgroundConfig(
            journal_root=str(root / ".agentfactory/memory/jobs"),
        ),
    )
