from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from pydantic import ConfigDict, Field

from agent_factory.core import FactoryEvent, sanitize_requirement_text
from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory import FactoryError
from agent_factory.factory.package_verification import FactoryVerificationReport
from agent_factory.factory_runtime import FactoryRunContext
from agent_factory.factory_runtime.production import FactoryProductionRuntime, FactoryProductionState
from agent_factory.model import ModelService
from agent_factory.specs import ValidationReport


class CreateAgentRequest(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    prompt: str
    draft: bool = True
    stream: bool = False
    show_thinking: bool = False
    start_path: Path | None = None


class CreateAgentResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    requirement: str
    status: str = "failed"
    runtime_type: str = "factory_production_langgraph"
    implemented: bool = False
    events: list[FactoryEvent] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    workspace_path: Path
    trace_path: Path
    memory_path: Path
    output_path: Path | None = None
    validation_report: ValidationReport | None = None
    generated_artifacts: list[Path] = Field(default_factory=list)
    generated_tool_count: int = 0
    generated_tool_test_count: int = 0
    mcp_binding_count: int = 0
    harness_scenario_count: int = 0
    verification_report: FactoryVerificationReport | None = None
    clarification_questions: list[str] = Field(default_factory=list)
    requirement_analysis: dict | None = None
    stage_history: list[str] = Field(default_factory=list)
    error: FactoryError | None = None


class CreateAgentService:
    """Create an AgentPackage draft from a natural language requirement."""

    def __init__(
        self,
        model_service: ModelService | None = None,
        runtime: FactoryProductionRuntime | None = None,
    ) -> None:
        self.model_service = model_service
        self.runtime = runtime

    def create_agent(self, request: CreateAgentRequest) -> CreateAgentResult:
        requirement = sanitize_requirement_text(request.prompt)
        context = FactoryRunContext.create(start_path=request.start_path)
        state = self._runtime().run(
            requirement=requirement,
            context=context,
            draft=request.draft,
        )
        return self._result(context, state)

    def stream_create_agent(self, request: CreateAgentRequest) -> Iterator[FactoryEvent]:
        requirement = sanitize_requirement_text(request.prompt)
        context = FactoryRunContext.create(start_path=request.start_path)
        yield from self._runtime().stream(
            requirement=requirement,
            context=context,
            draft=request.draft,
        )

    def _result(
        self,
        context: FactoryRunContext,
        state: FactoryProductionState,
    ) -> CreateAgentResult:
        output_path = state.package_path
        return CreateAgentResult(
            run_id=context.run_id,
            requirement=state.requirement,
            status=state.status,
            runtime_type=state.runtime_type,
            implemented=state.status == "completed",
            events=state.events,
            next_steps=self._next_steps(state),
            workspace_path=context.workspace_path,
            trace_path=context.trace_path,
            memory_path=context.memory_path,
            output_path=output_path,
            validation_report=state.validation_report,
            generated_artifacts=state.generated_artifacts,
            generated_tool_count=state.generated_tool_count,
            generated_tool_test_count=state.generated_tool_test_count,
            mcp_binding_count=state.mcp_binding_count,
            harness_scenario_count=state.harness_scenario_count,
            verification_report=state.verification_report,
            clarification_questions=state.clarification_questions,
            requirement_analysis=state.requirement_analysis,
            stage_history=state.stage_history,
            error=state.error,
        )

    def _runtime(self) -> FactoryProductionRuntime:
        if self.runtime is not None:
            return self.runtime
        return FactoryProductionRuntime(model_service=self.model_service)

    @staticmethod
    def _next_steps(state: FactoryProductionState) -> list[str]:
        if state.status == "completed" and state.package_path is not None:
            return [
                f"/validate {state.package_path}",
                f"/test {state.package_path}",
            ]
        if state.status == "needs_clarification":
            return [
                "Answer the clarification questions, then run /create-agent --draft again.",
            ]
        if state.error and state.error.code == "model_config_error":
            return [
                "Fill AGENTFACTORY_OPENAI_BASE_URL, AGENTFACTORY_OPENAI_API_KEY, and AGENTFACTORY_OPENAI_MODEL in .env.",
                "Run agentfactory create-agent --prompt \"...\" --draft again.",
            ]
        return [
            "Inspect the Factory trace, fix the reported issue, and retry create-agent.",
        ]
