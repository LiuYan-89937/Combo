from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ConfigDict, Field

from agent_factory.context import ContextBundle, ContextManager, tool_runtime_context
from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory.web_search import FactoryWebSearchService
from agent_factory.factory_runtime.redaction import redact_secrets
from agent_factory.memory import AgentMemoryRecord, AgentMemoryStore
from agent_factory.model import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    MessageBuilder,
    ModelConfigError,
    ModelService,
    OpenAIToolDefinition,
)
from agent_factory.model.runner import ModelCallRunner, ModelCallTraceSpan
from agent_factory.model.types import ModelError, TokenUsage, ToolCallProposal
from agent_factory.package import PackageLoader
from agent_factory.runtime.context_engineering import (
    ContextBudget,
    ContextPriority,
    MessageWindowPolicy,
    NodeStateReducer,
    SummaryPolicy,
    ToolObservationCompressor,
    VisibilityPolicy,
)
from agent_factory.tools import (
    ExternalHttpClient,
    ToolExecutor,
    ToolInvocation,
    ToolResultEnvelope,
    ToolRouter,
    load_external_config_context,
)

AgentRunStatus = Literal[
    "completed",
    "failed",
    "interrupted",
    "needs_configuration",
    "needs_upgrade",
]
RuntimeStatus = Literal[
    "running",
    "completed",
    "failed",
    "interrupted",
    "needs_configuration",
]


class RuntimeEvent(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    stage: str
    status: Literal["started", "completed", "failed", "interrupted", "needs_configuration"]
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentRunRequest(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    package_path: Path
    user_input: str
    session_id: str = "default"
    history: list[LLMMessage] = Field(default_factory=list)
    process_isolated: bool = False
    approved_tool_call_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class AgentRunResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    package_path: Path
    status: AgentRunStatus
    answer: str = ""
    runtime_type: str = "langgraph_react"
    session_id: str = "default"
    history_turn_count: int = 0
    tool_summary_fallback: bool = False
    intent: str | None = None
    trace_path: Path | None = None
    memory_path: Path | None = None
    checkpoint_path: Path | None = None
    events: list[RuntimeEvent] = Field(default_factory=list)
    context_bundle: ContextBundle | None = None
    context_compression_triggered: bool = False
    tool_proposals: list[ToolCallProposal] = Field(default_factory=list)
    tool_results: list[ToolResultEnvelope] = Field(default_factory=list)
    usage: TokenUsage | None = None
    error: ModelError | None = None
    upgrade_request_path: Path | None = None
    interrupt: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.status == "completed"


class AgentRuntimeCheckpoint(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    checkpoint_id: str
    session_id: str
    run_id: str
    turn_count: int
    messages_digest: str
    context_bundle_ref: str
    memory_summary_ref: str | None = None
    pending_interrupt: dict[str, Any] | None = None
    tool_call_pending: list[dict[str, str | None]] = Field(default_factory=list)
    visibility_policy_version: str = "visibility_policy.v1"
    state_hash: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentRuntimeStateDict(TypedDict, total=False):
    messages: list[LLMMessage]
    session_id: str
    run_id: str
    trace_id: str
    tool_calls: list[ToolCallProposal]
    pending_tool_calls: list[ToolCallProposal]
    tool_results: list[ToolResultEnvelope]
    interrupt: dict[str, Any] | None
    memory_summary: str | None
    context_bundle: ContextBundle | None
    runtime_status: RuntimeStatus
    turn_count: int
    max_turns: int
    answer: str
    error: ModelError | None
    usage: TokenUsage | None
    tool_summary_fallback: bool
    upgrade_request: dict[str, Any] | None
    context_compression_triggered: bool


class AgentRuntimeState(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    messages: list[LLMMessage] = Field(default_factory=list)
    session_id: str = "default"
    run_id: str
    trace_id: str
    tool_calls: list[ToolCallProposal] = Field(default_factory=list)
    pending_tool_calls: list[ToolCallProposal] = Field(default_factory=list)
    tool_results: list[ToolResultEnvelope] = Field(default_factory=list)
    interrupt: dict[str, Any] | None = None
    memory_summary: str | None = None
    context_bundle: ContextBundle | None = None
    runtime_status: RuntimeStatus = "running"
    turn_count: int = 0
    max_turns: int = 6
    answer: str = ""
    error: ModelError | None = None
    usage: TokenUsage | None = None
    tool_summary_fallback: bool = False
    upgrade_request: dict[str, Any] | None = None
    context_compression_triggered: bool = False

    def as_graph_state(self) -> AgentRuntimeStateDict:
        return self.model_dump(mode="python")  # type: ignore[return-value]

    @classmethod
    def from_graph_state(cls, state: AgentRuntimeStateDict | dict[str, Any]) -> "AgentRuntimeState":
        return cls.model_validate(dict(state))


class CompiledAgentRuntime(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    langgraph_app: Any
    langchain_tools: list[Any] = Field(default_factory=list)
    runtime_context_factory: Callable[[AgentRunRequest, ContextBundle], dict[str, Any]]
    policy_wrapped_tool_node: Any
    trace_adapter: Any
    memory_adapter: Any
    runtime_type: str = "langgraph_react"


class RuntimeContextCompiler:
    """Compile node-visible runtime context without exposing hidden values."""

    def __init__(
        self,
        *,
        message_window_policy: MessageWindowPolicy | None = None,
        summary_policy: SummaryPolicy | None = None,
        observation_compressor: ToolObservationCompressor | None = None,
        visibility_policy: VisibilityPolicy | None = None,
        budget: ContextBudget | None = None,
        priority: ContextPriority | None = None,
    ) -> None:
        self.message_window_policy = message_window_policy or MessageWindowPolicy()
        self.summary_policy = summary_policy or SummaryPolicy()
        self.observation_compressor = observation_compressor or ToolObservationCompressor()
        self.visibility_policy = visibility_policy or VisibilityPolicy()
        self.budget = budget or ContextBudget()
        self.priority = priority or ContextPriority()

    def compile_model_context(
        self,
        *,
        package: Any,
        state: AgentRuntimeState,
    ) -> list[LLMMessage]:
        context_bundle = self.visibility_policy.redact_bundle(state.context_bundle or ContextBundle())
        message_policy = MessageWindowPolicy(
            max_recent_turns=max(1, package.primitives.conversation.history_window)
        )
        window = message_policy.apply(state.messages)
        if window.compression_triggered:
            state.context_compression_triggered = True
            state.memory_summary = self.summary_policy.summarize(
                window.historical_messages,
                existing_summary=state.memory_summary,
            )
        instructions = package.primitives.instructions
        sections = [
            f"Persona: {instructions.persona}",
            f"Goal: {instructions.goal}",
            "The model may propose tools but must not claim it executed them directly.",
            (
                "When controlled resources are needed, return a tool call. "
                "All tool execution is mediated by ToolRouter and PolicyEngine."
            ),
        ]
        if instructions.boundaries:
            sections.append("Boundaries:\n" + "\n".join(f"- {item}" for item in instructions.boundaries))
        tool_text = _tool_manifest_text(package)
        if tool_text:
            sections.append(tool_text)
        if state.memory_summary:
            sections.append(f"Memory summary:\n{state.memory_summary}")
        if context_bundle.visible_to_model:
            sections.append(
                "Visible context:\n" + "\n".join(f"- {item}" for item in context_bundle.visible_to_model)
            )
        system = LLMMessage(role="system", content="\n\n".join(sections))
        return [system, *window.recent_messages]

    def compile_tool_context(
        self,
        *,
        package_path: Path,
        context_bundle: ContextBundle,
        env_file: str | Path | None,
    ) -> dict[str, Any]:
        runtime_context = tool_runtime_context(context_bundle)
        external_config = load_external_config_context(package_path, env_file=env_file or ".env")
        runtime_context["external_config"] = external_config.model_dump(mode="json")
        runtime_context["external_http_client"] = ExternalHttpClient(external_config)
        return runtime_context

    def compress_tool_observation(self, result: ToolResultEnvelope) -> str:
        return self.observation_compressor.compress(result)


class PolicyWrappedToolNode:
    def __init__(
        self,
        *,
        package_path: Path,
        loader: PackageLoader,
        env_file: str | Path | None,
        context_compiler: RuntimeContextCompiler,
        web_search_service: FactoryWebSearchService | None = None,
    ) -> None:
        self.package_path = package_path
        self.loader = loader
        self.env_file = env_file
        self.context_compiler = context_compiler
        self.web_search_service = web_search_service

    def invoke(
        self,
        proposal: ToolCallProposal,
        *,
        request: AgentRunRequest,
        context_bundle: ContextBundle,
    ) -> ToolResultEnvelope:
        router = ToolRouter(self.package_path, loader=self.loader)
        executor = ToolExecutor(web_search_service=self.web_search_service, env_file=self.env_file)
        approved_ref = request.approved_tool_call_id
        invocation = ToolInvocation(
            invocation_id=proposal.id,
            tool_call_id=proposal.id,
            tool_id=proposal.name,
            arguments=proposal.arguments,
            approved=approved_ref in {proposal.id, proposal.name},
        )
        route = router.route(invocation)
        if isinstance(route, ToolResultEnvelope):
            return route
        runtime_context = self.context_compiler.compile_tool_context(
            package_path=self.package_path,
            context_bundle=context_bundle,
            env_file=self.env_file,
        )
        return executor.execute(
            self.package_path,
            route,
            invocation,
            runtime_context=runtime_context,
        )


class AgentPackageCompiler:
    def __init__(
        self,
        *,
        loader: PackageLoader | None = None,
        context_manager: ContextManager | None = None,
        context_compiler: RuntimeContextCompiler | None = None,
    ) -> None:
        self.loader = loader or PackageLoader()
        self.context_manager = context_manager or ContextManager(loader=self.loader)
        self.context_compiler = context_compiler or RuntimeContextCompiler()
        self.reducer = NodeStateReducer()

    def compile(
        self,
        package_path: str | Path,
        *,
        model_service: ModelService | None,
        env_file: str | Path | None = None,
        web_search_service: FactoryWebSearchService | None = None,
        trace: Callable[[RuntimeEvent], None] | None = None,
        request: AgentRunRequest,
    ) -> CompiledAgentRuntime:
        package_root = Path(package_path)
        package = self.loader.load_full_package(package_root)
        model_runner = ModelCallRunner.from_service(model_service or ModelService.from_env(env_file or ".env"))
        policy_tool_node = PolicyWrappedToolNode(
            package_path=package_root,
            loader=self.loader,
            env_file=env_file,
            context_compiler=self.context_compiler,
            web_search_service=web_search_service,
        )
        langchain_tools = _langchain_tools_for_package(package)

        def model_node(raw_state: AgentRuntimeStateDict) -> AgentRuntimeStateDict:
            before = dict(raw_state)
            state = AgentRuntimeState.from_graph_state(raw_state)
            if state.turn_count >= state.max_turns:
                state.runtime_status = "failed"
                state.error = ModelError(
                    type="max_turns_exceeded",
                    message="package.runtime.max_turns was exceeded.",
                )
                return self.reducer.reduce(
                    "model_node",
                    before,
                    _record_and_dump(trace, state, "runtime.max_turns", "failed"),
                )

            messages = self.context_compiler.compile_model_context(package=package, state=state)
            request_payload = LLMRequest(
                messages=messages,
                tools=[tool.model_dump(mode="json") for tool in _openai_tools_for_package(package)],
                tool_choice="auto",
                metadata={"agent": package.manifest.agent_id, "runtime": "langgraph_react"},
            )
            response = asyncio.run(model_runner.generate(request_payload))
            _record_model_span(trace, state.run_id, model_runner.last_span)
            if response.error:
                state.runtime_status = "failed"
                state.error = response.error
                return self.reducer.reduce(
                    "model_node",
                    before,
                    _record_and_dump(trace, state, "model", "failed", response.error.message),
                )

            state.usage = response.usage
            if response.tool_call_proposals:
                state.pending_tool_calls = list(response.tool_call_proposals)
                state.tool_calls.extend(response.tool_call_proposals)
                if response.content:
                    state.messages.append(LLMMessage(role="assistant", content=response.content))
                return self.reducer.reduce(
                    "model_node",
                    before,
                    _record_and_dump(
                        trace,
                        state,
                        "model",
                        "completed",
                        payload={"tool_call_count": len(response.tool_call_proposals)},
                    ),
                )

            state.runtime_status = "completed"
            state.answer = response.content or _fallback_answer("", "in_scope", state.tool_results)
            state.messages.append(LLMMessage(role="assistant", content=state.answer))
            return self.reducer.reduce(
                "model_node",
                before,
                _record_and_dump(trace, state, "final_answer", "completed"),
            )

        def tool_node(raw_state: AgentRuntimeStateDict) -> AgentRuntimeStateDict:
            before = dict(raw_state)
            state = AgentRuntimeState.from_graph_state(raw_state)
            context_bundle = state.context_bundle or ContextBundle()
            for proposal in state.pending_tool_calls:
                result = policy_tool_node.invoke(proposal, request=request, context_bundle=context_bundle)
                state.tool_results.append(result)
                observation = self.context_compiler.compress_tool_observation(result)
                state.messages.append(
                    LLMMessage(role="tool", content=observation, tool_call_id=proposal.id)
                )
                _record_tool_event(trace, state.run_id, result)
                if result.status == "interrupted":
                    state.runtime_status = "interrupted"
                    state.interrupt = {
                        "tool_call_id": result.tool_call_id or result.invocation_id,
                        "tool_id": result.tool_id,
                        "type": result.interrupt_type or "human_confirm",
                        "approval_required": result.approval_required,
                    }
                    state.answer = _fallback_answer("", _intent_from_tool_proposals(state.tool_calls), state.tool_results)
                    state.pending_tool_calls = []
                    return self.reducer.reduce("tool_node", before, state.as_graph_state())
                if result.status == "needs_configuration":
                    state.runtime_status = "needs_configuration"
                    state.answer = _fallback_answer("", _intent_from_tool_proposals(state.tool_calls), state.tool_results)
                    state.pending_tool_calls = []
                    return self.reducer.reduce("tool_node", before, state.as_graph_state())
                if result.status == "blocked":
                    state.runtime_status = "failed"
                    state.error = ModelError(
                        type="tool_blocked",
                        message=result.error or f"Tool was blocked: {result.tool_id}",
                    )
                    state.pending_tool_calls = []
                    return self.reducer.reduce("tool_node", before, state.as_graph_state())

            state.turn_count += 1
            state.pending_tool_calls = []
            if state.turn_count >= state.max_turns and state.runtime_status == "running":
                state.runtime_status = "failed"
                state.error = ModelError(
                    type="max_turns_exceeded",
                    message="package.runtime.max_turns was exceeded.",
                )
            return self.reducer.reduce("tool_node", before, state.as_graph_state())

        def route_after_model(raw_state: AgentRuntimeStateDict) -> str:
            state = AgentRuntimeState.from_graph_state(raw_state)
            if state.runtime_status in {"completed", "failed", "interrupted", "needs_configuration"}:
                return "end"
            if state.pending_tool_calls:
                return "tools"
            return "end"

        def route_after_tools(raw_state: AgentRuntimeStateDict) -> str:
            state = AgentRuntimeState.from_graph_state(raw_state)
            if state.runtime_status in {"failed", "interrupted", "needs_configuration"}:
                return "end"
            if state.turn_count >= state.max_turns:
                return "end"
            return "model"

        graph = StateGraph(AgentRuntimeStateDict)
        graph.add_node("model", model_node)
        graph.add_node("tools", tool_node)
        graph.add_edge(START, "model")
        graph.add_conditional_edges("model", route_after_model, {"tools": "tools", "end": END})
        graph.add_conditional_edges("tools", route_after_tools, {"model": "model", "end": END})
        return CompiledAgentRuntime(
            langgraph_app=graph.compile(),
            langchain_tools=langchain_tools,
            runtime_context_factory=lambda req, bundle: self.context_compiler.compile_tool_context(
                package_path=package_root,
                context_bundle=bundle,
                env_file=env_file,
            ),
            policy_wrapped_tool_node=policy_tool_node,
            trace_adapter=trace,
            memory_adapter=AgentMemoryStore(package_root, loader=self.loader),
        )


class AgentInstanceRuntime:
    def __init__(
        self,
        *,
        model_service: ModelService | None = None,
        env_file: str | Path | None = None,
        loader: PackageLoader | None = None,
        context_manager: ContextManager | None = None,
        web_search_service: FactoryWebSearchService | None = None,
        compiler: AgentPackageCompiler | None = None,
    ) -> None:
        self.model_service = model_service
        self.env_file = Path(env_file) if env_file is not None else None
        self.loader = loader or PackageLoader()
        self.context_manager = context_manager or ContextManager(loader=self.loader)
        self.web_search_service = web_search_service
        self.compiler = compiler or AgentPackageCompiler(
            loader=self.loader,
            context_manager=self.context_manager,
        )

    def run(self, request: AgentRunRequest) -> AgentRunResult:
        run_id = uuid.uuid4().hex
        package_path = request.package_path
        trace_path = package_path / "traces" / f"agent_run_{run_id}.jsonl"
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        events: list[RuntimeEvent] = []

        def record(event: RuntimeEvent) -> None:
            event.payload = redact_secrets(event.payload)
            events.append(event)
            with trace_path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False) + "\n")

        try:
            package = self.loader.load_full_package(package_path)
            memory = AgentMemoryStore(package_path, loader=self.loader)
            context_bundle = self.context_manager.compile(
                package_path,
                session_context=request.context,
            )
            record(RuntimeEvent(run_id=run_id, stage="load_context", status="completed"))
            resume_checkpoint = _read_checkpoint(package_path, request.session_id)
            if request.approved_tool_call_id and resume_checkpoint is not None:
                record(
                    RuntimeEvent(
                        run_id=run_id,
                        stage="checkpoint_resume",
                        status="completed",
                        payload={
                            "checkpoint_id": resume_checkpoint.checkpoint_id,
                            "state_hash": resume_checkpoint.state_hash,
                            "session_id": request.session_id,
                        },
                    )
                )
            history = request.history or memory.recent_messages(
                session_id=request.session_id,
                limit_turns=package.primitives.conversation.history_window,
            )
            history_turn_count = _history_turn_count(history)
            memory_summary = _memory_summary(history)
            record(
                RuntimeEvent(
                    run_id=run_id,
                    stage="load_memory",
                    status="completed",
                    payload={
                        "session_id": request.session_id,
                        "history_turn_count": history_turn_count,
                        "source": "request" if request.history else "memory",
                    },
                )
            )
            initial_messages = [*history, LLMMessage(role="user", content=request.user_input)]
            compiled = self.compiler.compile(
                package_path,
                model_service=self.model_service,
                env_file=self.env_file,
                web_search_service=self.web_search_service,
                trace=record,
                request=request,
            )
            initial = AgentRuntimeState(
                run_id=run_id,
                trace_id=run_id,
                session_id=request.session_id,
                messages=initial_messages,
                context_bundle=context_bundle,
                memory_summary=memory_summary,
                max_turns=package.runtime.max_turns,
            )
            final_state = compiled.langgraph_app.invoke(
                initial.as_graph_state(),
                config={"recursion_limit": max(10, package.runtime.max_turns * 4 + 4)},
            )
            state = AgentRuntimeState.from_graph_state(final_state)
            status = _result_status(state)
            answer = state.answer or _fallback_answer(
                request.user_input,
                _intent_from_tool_proposals(state.tool_calls),
                state.tool_results,
            )
            checkpoint_path, checkpoint = _write_checkpoint(package_path, state)
            record(
                RuntimeEvent(
                    run_id=run_id,
                    stage="checkpoint",
                    status="completed",
                    payload={
                        "checkpoint_path": str(checkpoint_path),
                        "session_id": request.session_id,
                        "state_hash": checkpoint.state_hash,
                    },
                )
            )
            memory.append(
                AgentMemoryRecord(
                    run_id=run_id,
                    session_id=request.session_id,
                    type="agent_turn",
                    summary=f"Handled intent={_intent_from_tool_proposals(state.tool_calls)}",
                    payload={
                        "user_input": request.user_input,
                        "answer": answer,
                        "runtime_type": "langgraph_react",
                        "tool_results": [
                            result.model_dump(mode="json") for result in state.tool_results
                        ],
                    },
                )
            )
            record(
                RuntimeEvent(
                    run_id=run_id,
                    stage="complete" if status == "completed" else status,
                    status="completed" if status in {"completed", "needs_upgrade"} else status,
                    payload={
                        "intent": _intent_from_tool_proposals(state.tool_calls),
                        "tool_count": len(state.tool_results),
                        "session_id": request.session_id,
                        "history_turn_count": history_turn_count,
                        "runtime_type": "langgraph_react",
                        "context_compression_triggered": state.context_compression_triggered,
                    },
                )
            )
            return AgentRunResult(
                run_id=run_id,
                package_path=package_path,
                status=status,
                answer=answer,
                runtime_type="langgraph_react",
                session_id=request.session_id,
                history_turn_count=history_turn_count,
                intent=_intent_from_tool_proposals(state.tool_calls),
                trace_path=trace_path,
                memory_path=memory.path,
                checkpoint_path=checkpoint_path,
                events=events,
                context_bundle=context_bundle,
                context_compression_triggered=state.context_compression_triggered,
                tool_proposals=state.tool_calls,
                tool_results=state.tool_results,
                usage=state.usage,
                error=state.error,
                interrupt=state.interrupt,
            )
        except ModelConfigError as error:
            model_error = ModelError(type="model_config_error", message=str(error))
            record(RuntimeEvent(run_id=run_id, stage="model_config", status="failed", message=str(error)))
            return AgentRunResult(
                run_id=run_id,
                package_path=package_path,
                status="failed",
                session_id=request.session_id,
                trace_path=trace_path,
                events=events,
                error=model_error,
            )
        except Exception as error:
            model_error = ModelError(type="runtime_error", message=str(error))
            record(RuntimeEvent(run_id=run_id, stage="runtime", status="failed", message=str(error)))
            return AgentRunResult(
                run_id=run_id,
                package_path=package_path,
                status="failed",
                session_id=request.session_id,
                trace_path=trace_path,
                events=events,
                error=model_error,
            )


def _openai_tools_for_package(package: Any) -> list[OpenAIToolDefinition]:
    tools: list[OpenAIToolDefinition] = []
    for tool in package.generated_tools:
        if tool.exposure != "exposed":
            continue
        tools.append(
            OpenAIToolDefinition(
                function={
                    "name": tool.tool_id,
                    "description": _tool_description(tool),
                    "parameters": _tool_parameters_schema(tool.input_schema),
                }
            )
        )
    for capability in package.tools.builtin_capabilities:
        if capability.exposure != "exposed":
            continue
        tools.append(
            OpenAIToolDefinition(
                function={
                    "name": capability.id,
                    "description": _builtin_tool_description(capability),
                    "parameters": _builtin_tool_parameters_schema(capability),
                }
            )
        )
    return tools


def _langchain_tools_for_package(package: Any) -> list[Any]:
    try:
        from langchain_core.tools import StructuredTool
    except Exception:
        return []

    compiled = []
    for definition in _openai_tools_for_package(package):
        name = str(definition.function.get("name") or "tool")
        description = str(definition.function.get("description") or name)

        def _placeholder(**kwargs: Any) -> dict[str, Any]:
            return {"tool": name, "arguments": kwargs}

        compiled.append(
            StructuredTool.from_function(
                func=_placeholder,
                name=name,
                description=description,
            )
        )
    return compiled


def _tool_description(tool: Any) -> str:
    parts = [tool.metadata.description or tool.metadata.name or tool.tool_id]
    parts.append(f"Risk level: {tool.risk_level}.")
    if tool.approval.required:
        parts.append("Approval is required before execution.")
    if tool.implementation_plan:
        if tool.implementation_plan.resource_refs:
            parts.append("Resource refs: " + ", ".join(tool.implementation_plan.resource_refs) + ".")
        if tool.implementation_plan.allowed_operations:
            parts.append(
                "Allowed operations: "
                + "; ".join(tool.implementation_plan.allowed_operations[:6])
                + "."
            )
        if tool.implementation_plan.forbidden_operations:
            parts.append(
                "Forbidden operations: "
                + "; ".join(tool.implementation_plan.forbidden_operations[:6])
                + "."
            )
    return " ".join(parts)


def _builtin_tool_description(capability: Any) -> str:
    parts = [capability.description, f"Risk level: {capability.risk_level}."]
    if capability.approval_required:
        parts.append("Approval is required before execution.")
    if capability.allowed_domains:
        parts.append("Allowed domains: " + ", ".join(capability.allowed_domains) + ".")
    if capability.blocked_domains:
        parts.append("Blocked domains: " + ", ".join(capability.blocked_domains) + ".")
    return " ".join(parts)


def _builtin_tool_parameters_schema(capability: Any) -> dict[str, Any]:
    if capability.type == "web_search":
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": capability.max_results,
                    "description": "Maximum result count.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        }
    return {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "HTTP or HTTPS URL to fetch."},
            "max_content_chars": {
                "type": "integer",
                "minimum": 1,
                "maximum": capability.max_content_chars,
                "description": "Maximum extracted text characters.",
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    }


def _tool_parameters_schema(schema: dict[str, Any]) -> dict[str, Any]:
    if schema.get("type") == "object":
        parameters = dict(schema)
    else:
        parameters = {
            "type": "object",
            "properties": {"input": schema or {"type": "string"}},
            "required": ["input"],
        }
    parameters.setdefault("properties", {})
    parameters.setdefault("required", [])
    parameters.setdefault("additionalProperties", False)
    return parameters


def _tool_manifest_text(package: Any) -> str:
    lines = ["Available tools exposed through Runtime:"]
    for tool in package.generated_tools:
        if tool.exposure != "exposed":
            continue
        approval = "approval_required" if tool.approval.required else "auto_routable"
        lines.append(
            f"- {tool.tool_id}: {tool.metadata.description or tool.metadata.name}; "
            f"risk={tool.risk_level}; {approval}; return a tool call instead of pretending to execute it."
        )
    for capability in package.tools.builtin_capabilities:
        if capability.exposure != "exposed":
            continue
        approval = "approval_required" if capability.approval_required else "auto_routable"
        lines.append(
            f"- {capability.id}: {capability.description}; "
            f"type={capability.type}; risk={capability.risk_level}; {approval}; "
            "return a tool call instead of pretending to execute it."
        )
    return "\n".join(lines) if len(lines) > 1 else ""


def _intent_from_tool_proposals(proposals: list[ToolCallProposal]) -> str:
    if proposals:
        return proposals[0].name
    return "in_scope"


def _fallback_answer(user_input: str, intent: str, tool_results: list[ToolResultEnvelope]) -> str:
    if tool_results:
        completed = [item for item in tool_results if item.status == "completed"]
        interrupted = [item for item in tool_results if item.status == "interrupted"]
        needs_configuration = [item for item in tool_results if item.status == "needs_configuration"]
        if completed:
            summaries = []
            for item in completed:
                rendered = json.dumps(item.output or {}, ensure_ascii=False)
                summaries.append(f"{item.tool_id}: {rendered}")
            return "已通过受控工具链处理：" + "；".join(summaries)
        if needs_configuration:
            missing = needs_configuration[0].output or {}
            return (
                f"运行前还需要补充配置：{needs_configuration[0].tool_id}。"
                f"{json.dumps(missing, ensure_ascii=False)}"
            )
        if interrupted:
            return f"该操作需要人工确认后才能执行：{interrupted[0].tool_id}。"
    return "我已根据当前 AgentPackage 的能力边界处理这次请求。"


def _history_turn_count(history: list[LLMMessage]) -> int:
    return sum(1 for message in history if message.role == "user")


def _memory_summary(history: list[LLMMessage]) -> str | None:
    if not history:
        return None
    recent = history[-6:]
    return "\n".join(f"{message.role}: {message.content[:200]}" for message in recent)


def _result_status(state: AgentRuntimeState) -> AgentRunStatus:
    if state.runtime_status == "completed":
        return "completed"
    if state.runtime_status == "interrupted":
        return "interrupted"
    if state.runtime_status == "needs_configuration":
        return "needs_configuration"
    return "failed"


def _checkpoint_path(package_path: Path, session_id: str) -> Path:
    session_key = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    return package_path / "checkpoints" / f"{session_key}.json"


def _write_checkpoint(
    package_path: Path,
    state: AgentRuntimeState,
) -> tuple[Path, AgentRuntimeCheckpoint]:
    path = _checkpoint_path(package_path, state.session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = _build_checkpoint(state)
    path.write_text(checkpoint.model_dump_json(indent=2), encoding="utf-8")
    return path, checkpoint


def _read_checkpoint(package_path: Path, session_id: str) -> AgentRuntimeCheckpoint | None:
    path = _checkpoint_path(package_path, session_id)
    if not path.exists():
        return None
    try:
        return AgentRuntimeCheckpoint.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _build_checkpoint(state: AgentRuntimeState) -> AgentRuntimeCheckpoint:
    messages_digest = _stable_digest(
        [
            {
                "role": message.role,
                "content_hash": _stable_digest(message.content),
                "tool_call_id": message.tool_call_id,
            }
            for message in state.messages
        ]
    )
    context_bundle_ref = _stable_digest(
        redact_secrets(
            (state.context_bundle or ContextBundle()).model_dump(mode="json")
        )
    )
    memory_summary_ref = _stable_digest(redact_secrets(state.memory_summary)) if state.memory_summary else None
    pending_interrupt = redact_secrets(state.interrupt) if state.interrupt else None
    tool_call_pending = [
        {
            "id": proposal.id,
            "name": proposal.name,
            "arguments_digest": _stable_digest(redact_secrets(proposal.arguments)),
        }
        for proposal in state.pending_tool_calls
    ]
    hash_payload = {
        "run_id": state.run_id,
        "session_id": state.session_id,
        "turn_count": state.turn_count,
        "messages_digest": messages_digest,
        "context_bundle_ref": context_bundle_ref,
        "memory_summary_ref": memory_summary_ref,
        "pending_interrupt": pending_interrupt,
        "tool_call_pending": tool_call_pending,
        "visibility_policy_version": "visibility_policy.v1",
    }
    return AgentRuntimeCheckpoint(
        checkpoint_id=uuid.uuid4().hex,
        session_id=state.session_id,
        run_id=state.run_id,
        turn_count=state.turn_count,
        messages_digest=messages_digest,
        context_bundle_ref=context_bundle_ref,
        memory_summary_ref=memory_summary_ref,
        pending_interrupt=pending_interrupt,
        tool_call_pending=tool_call_pending,
        state_hash=_stable_digest(hash_payload),
    )


def _stable_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _compress_observation(result: ToolResultEnvelope) -> str:
    summary = result.observation_summary
    if not summary:
        payload = {
            "tool_id": result.tool_id,
            "status": result.status,
            "output": result.output,
            "error": result.error,
        }
        summary = json.dumps(redact_secrets(payload), ensure_ascii=False)
    if len(summary) > 3000:
        summary = summary[:3000] + "...[truncated]"
    return summary


def _record_and_dump(
    trace: Callable[[RuntimeEvent], None] | None,
    state: AgentRuntimeState,
    stage: str,
    status: Literal["completed", "failed", "interrupted", "needs_configuration"],
    message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> AgentRuntimeStateDict:
    if trace:
        trace(
            RuntimeEvent(
                run_id=state.run_id,
                stage=stage,
                status=status,
                message=message,
                payload=payload or {},
            )
        )
    return state.as_graph_state()


def _record_model_span(
    trace: Callable[[RuntimeEvent], None] | None,
    run_id: str,
    span: ModelCallTraceSpan | None,
) -> None:
    if trace is None or span is None:
        return
    trace(
        RuntimeEvent(
            run_id=run_id,
            stage="model_call",
            status="completed" if span.status == "completed" else "failed",
            message=span.error_type,
            payload=span.model_dump(mode="json"),
        )
    )


def _record_tool_event(
    trace: Callable[[RuntimeEvent], None] | None,
    run_id: str,
    result: ToolResultEnvelope,
) -> None:
    if trace is None:
        return
    trace(
        RuntimeEvent(
            run_id=run_id,
            stage="tool",
            status=(
                "interrupted"
                if result.status == "interrupted"
                else "needs_configuration"
                if result.status == "needs_configuration"
                else "failed"
                if result.status in {"failed", "blocked"}
                else "completed"
            ),
            message=result.error,
            payload={
                "tool_call_id": result.tool_call_id or result.invocation_id,
                "tool_id": result.tool_id,
                "status": result.status,
                "observation_summary": result.observation_summary,
                "redaction_report": result.redaction_report,
            },
        )
    )
