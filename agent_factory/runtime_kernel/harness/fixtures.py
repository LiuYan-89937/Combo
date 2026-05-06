from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FixtureBundle(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    model_service: object | None = None
    tool_registry: object | None = None
    policy_engine: object | None = None
    memory_engine: object | None = None
    knowledge_engine: object | None = None


class HarnessScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    input_text: str
    resume_after_interrupt: bool = False
    assertions: list[dict[str, Any]] = Field(default_factory=list)


class HarnessScenarioResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    status: str
    assertion_results: list[dict[str, Any]] = Field(default_factory=list)
    final_answer: str | None = None
    event_log: list[dict[str, Any]] = Field(default_factory=list)
    trace_summary: dict[str, Any] | None = None
