from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field

from agent_factory.core import FactoryEvent, sanitize_requirement_text
from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory_runtime import FactoryRunContext
from agent_factory.factory_runtime.production import (
    FACTORY_STAGE_SEQUENCE,
    FactoryProductionRuntime,
    FactoryProductionState,
)


class CreateAgentRequest(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    prompt: str
    start_path: Path | None = None
    stop_after_stage: str | None = "capture_requirement"


class CreateAgentResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    requirement: str
    status: str
    runtime_type: str = "factory_production_langgraph"
    events: list[FactoryEvent] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    workspace_path: Path
    trace_path: Path
    breakpoint_details: dict[str, Any] | None = None
    production_summary: dict[str, Any] | None = None
    stage_history: list[str] = Field(default_factory=list)
    error: dict[str, Any] | None = None


class CreateAgentService:
    def __init__(self, runtime: FactoryProductionRuntime | None = None) -> None:
        self.runtime = runtime or FactoryProductionRuntime()

    def create_agent(self, request: CreateAgentRequest) -> CreateAgentResult:
        requirement = sanitize_requirement_text(request.prompt)
        context = FactoryRunContext.create(start_path=request.start_path)
        state = self.runtime.run(
            requirement=requirement,
            context=context,
            stop_after_stage=request.stop_after_stage,
        )
        return self._result(context, state)

    def stream_create_agent(self, request: CreateAgentRequest) -> Iterator[FactoryEvent]:
        requirement = sanitize_requirement_text(request.prompt)
        context = FactoryRunContext.create(start_path=request.start_path)
        yield from self.runtime.stream(
            requirement=requirement,
            context=context,
            stop_after_stage=request.stop_after_stage,
        )

    @staticmethod
    def available_stages() -> list[str]:
        return list(FACTORY_STAGE_SEQUENCE)

    def _result(self, context: FactoryRunContext, state: FactoryProductionState) -> CreateAgentResult:
        return CreateAgentResult(
            run_id=context.run_id,
            requirement=state.requirement,
            status=state.status,
            events=state.events,
            next_steps=self._next_steps(state),
            workspace_path=context.workspace_path,
            trace_path=context.trace_path,
            breakpoint_details=state.breakpoint_details,
            production_summary=state.production_summary,
            stage_history=state.stage_history,
            error=state.error.model_dump(mode="json") if state.error else None,
        )

    @staticmethod
    def _next_steps(state: FactoryProductionState) -> list[str]:
        if state.status == "paused":
            current = str((state.breakpoint_details or {}).get("breakpoint_stage") or state.current_stage or "-")
            next_stage = (state.breakpoint_details or {}).get("next_stage")
            steps = [f"当前已停在阶段：{current}"]
            if next_stage:
                steps.append(f"下一阶段将进入：{next_stage}")
            steps.append("继续按下一个阶段重写内部逻辑。")
            return steps
        if state.status == "completed":
            return [
                "14 个阶段骨架已完整跑通。",
                "现在可以开始逐阶段填充真实实现。",
            ]
        if state.status == "failed":
            return ["查看 trace，修正当前阶段骨架。"]
        return []
