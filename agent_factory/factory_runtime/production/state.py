from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import ConfigDict, Field

from agent_factory.core import FactoryEvent
from agent_factory.core.types import JsonDumpMixin

ProductionStatus = Literal["running", "paused", "completed", "failed"]


class StageError(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str


class FactoryProductionStateDict(TypedDict, total=False):
    run_id: str
    requirement: str
    status: ProductionStatus
    current_stage: str | None
    graph_node: str | None
    events: list[FactoryEvent]
    stage_history: list[str]
    stop_after_stage: str | None
    breakpoint_details: dict[str, Any] | None
    production_summary: dict[str, Any] | None
    error: dict[str, Any] | None


class FactoryProductionState(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    run_id: str
    requirement: str
    status: ProductionStatus = "running"
    current_stage: str | None = None
    graph_node: str | None = None
    events: list[FactoryEvent] = Field(default_factory=list)
    stage_history: list[str] = Field(default_factory=list)
    stop_after_stage: str | None = None
    breakpoint_details: dict[str, Any] | None = None
    production_summary: dict[str, Any] | None = None
    error: StageError | None = None
    runtime_type: str = "factory_production_langgraph"

    def as_graph_state(self) -> FactoryProductionStateDict:
        return self.model_dump(mode="python", by_alias=True)  # type: ignore[return-value]

    @classmethod
    def from_graph_state(cls, state: FactoryProductionStateDict | dict[str, Any]) -> "FactoryProductionState":
        return cls.model_validate(dict(state))
