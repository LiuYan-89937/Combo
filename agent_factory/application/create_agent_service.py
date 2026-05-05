from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from pydantic import ConfigDict, Field
from ruamel.yaml import YAML

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
    pending_configuration_files: list[Path] = Field(default_factory=list)
    pending_configuration_keys: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    clarification_options: list[dict] = Field(default_factory=list)
    guidance_message: str | None = None
    factory_intent: dict | None = None
    requirement_analysis: dict | None = None
    research_brief_report: dict | None = None
    research_completeness_report: dict | None = None
    readiness_decision: dict | None = None
    production_summary: dict | None = None
    artifact_refs: list[dict] = Field(default_factory=list)
    context_envelopes: list[dict] = Field(default_factory=list)
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
            implemented=state.status in {"completed", "completed_with_warnings"},
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
            pending_configuration_files=self._pending_configuration_files(output_path),
            pending_configuration_keys=self._pending_configuration_keys(output_path),
            clarification_questions=state.clarification_questions,
            clarification_options=state.clarification_options,
            guidance_message=state.guidance_message,
            factory_intent=state.factory_intent,
            requirement_analysis=state.requirement_analysis,
            research_brief_report=state.research_brief_report,
            research_completeness_report=state.research_completeness_report,
            readiness_decision=state.readiness_decision.model_dump(mode="json")
            if state.readiness_decision
            else None,
            production_summary=state.production_summary.model_dump(mode="json")
            if state.production_summary
            else None,
            artifact_refs=[
                record
                for record in state.decision_records
            ],
            context_envelopes=[
                envelope.model_dump(mode="json")
                for envelope in state.context_envelopes
            ],
            stage_history=state.stage_history,
            error=state.error,
        )

    def _runtime(self) -> FactoryProductionRuntime:
        if self.runtime is not None:
            return self.runtime
        return FactoryProductionRuntime(model_service=self.model_service)

    @staticmethod
    def _next_steps(state: FactoryProductionState) -> list[str]:
        if state.status in {"completed", "completed_with_warnings"} and state.package_path is not None:
            steps = [
                f"/validate {state.package_path}",
                f"/test {state.package_path}",
            ]
            external_config = state.package_path / "external_config.yaml"
            if external_config.exists():
                keys = CreateAgentService._pending_configuration_keys(state.package_path)
                steps.insert(
                    0,
                    f"Fill runtime external configuration: {external_config}"
                    + (f" ({', '.join(keys[:8])})" if keys else ""),
                )
                steps.append(f"/test {state.package_path} --external-smoke")
            return steps
        if state.status == "needs_clarification":
            return [
                "Choose or answer the clarification questions, then run /create-agent --draft again with the completed requirement.",
            ]
        if state.status == "not_agent_request":
            return [
                "Try: 创建一个能读取指定资料并按规则回答问题的 Agent。",
                "Or type /help to see available Factory commands.",
            ]
        if state.error and state.error.code == "model_config_error":
            return [
                "Fill AGENTFACTORY_OPENAI_BASE_URL, AGENTFACTORY_OPENAI_API_KEY, and AGENTFACTORY_OPENAI_MODEL in .env.",
                "Run agentfactory create-agent --prompt \"...\" --draft again.",
            ]
        return [
            "Inspect the Factory trace, fix the reported issue, and retry create-agent.",
        ]

    @staticmethod
    def _pending_configuration_files(output_path: Path | None) -> list[Path]:
        if output_path is None:
            return []
        candidates = [output_path / "external_config.yaml"]
        return [path for path in candidates if path.exists()]

    @staticmethod
    def _pending_configuration_keys(output_path: Path | None) -> list[str]:
        if output_path is None:
            return []
        path = output_path / "external_config.yaml"
        if not path.exists():
            return []
        data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return []
        values = data.get("values") if isinstance(data.get("values"), dict) else {}
        required = data.get("required_keys") if isinstance(data.get("required_keys"), list) else []
        keys: list[str] = []
        for item in required:
            key = str(item)
            if not str(values.get(key) or "").strip():
                keys.append(key)
        return keys
