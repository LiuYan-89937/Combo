from __future__ import annotations

import hashlib
import json
import pickle
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import ConfigDict, Field

from agent_factory.context import ContextBundle, ContextManager, tool_runtime_context
from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory.web_search import FactoryWebSearchService
from agent_factory.factory_runtime.redaction import redact_secrets
from agent_factory.memory import AgentMemoryRecord, AgentMemoryStore
from agent_factory.package import PackageLoader
from agent_factory.runtime.context_engineering import (
    ContextBudget,
    ContextPriority,
    MessageWindowPolicy,
    SummaryPolicy,
    ToolObservationCompressor,
    VisibilityPolicy,
)
from agent_factory.runtime.langchain_chat import (
    RuntimeModelConfigError,
    RuntimeModelError,
    build_runtime_chat_model,
)
from agent_factory.runtime.types import RuntimeErrorInfo, RuntimeTokenUsage
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
RuntimeToolCall = dict[str, Any]
RunPhase = Literal["running", "done", "failed", "configuration_needed"]


class RuntimeEvent(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    stage: str
    status: Literal["started", "completed", "failed", "interrupted", "needs_configuration"]
    message: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AgentRunRequest(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    package_path: Path
    user_input: str
    session_id: str = "default"
    history: list[BaseMessage] = Field(default_factory=list)
    process_isolated: bool = False
    approved_tool_call_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class AgentRunResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    package_path: Path
    status: AgentRunStatus
    answer: str = ""
    runtime_type: str = "langgraph_native"
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
    tool_proposals: list[RuntimeToolCall] = Field(default_factory=list)
    tool_results: list[ToolResultEnvelope] = Field(default_factory=list)
    usage: RuntimeTokenUsage | None = None
    error: RuntimeErrorInfo | None = None
    upgrade_request_path: Path | None = None
    interrupt: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.status == "completed"


class RuntimeGraphState(TypedDict, total=False):
    messages: list[BaseMessage]
    session_id: str
    run_id: str
    trace_id: str
    tool_calls: list[RuntimeToolCall]
    active_calls: list[RuntimeToolCall]
    tool_results: list[dict[str, Any]]
    interrupt_payload: dict[str, Any] | None
    memory_summary: str | None
    context_bundle: ContextBundle | None
    run_phase: RunPhase
    route_key: str
    turn_count: int
    max_turns: int
    answer: str
    error: dict[str, Any] | None
    usage: dict[str, Any] | None
    tool_summary_fallback: bool
    upgrade_request: dict[str, Any] | None
    context_compression_triggered: bool


class CompiledAgentRuntime(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    langgraph_app: Any
    langchain_tools: list[Any] = Field(default_factory=list)
    runtime_context_factory: Callable[[AgentRunRequest, ContextBundle], dict[str, Any]]
    policy_wrapped_tool_node: Any
    trace_adapter: Any
    memory_adapter: Any
    runtime_type: str = "langgraph_native"
    checkpoint_path: Path | None = None


class RuntimeContextCompiler:
    """Compile node-visible context and keep hidden values out of model prompts."""

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
        state: RuntimeGraphState,
    ) -> tuple[list[BaseMessage], dict[str, Any]]:
        context_bundle = self.visibility_policy.redact_bundle(
            state.get("context_bundle") or ContextBundle()
        )
        message_policy = MessageWindowPolicy(
            max_recent_turns=max(1, package.primitives.conversation.history_window)
        )
        messages = list(state.get("messages") or [])
        window = message_policy.apply(messages)
        updates: dict[str, Any] = {}
        if window.compression_triggered:
            updates["context_compression_triggered"] = True
            updates["memory_summary"] = self.summary_policy.summarize(
                window.historical_messages,
                existing_summary=state.get("memory_summary"),
            )
        instructions = package.primitives.instructions
        sections = [
            f"Persona: {instructions.persona}",
            f"Goal: {instructions.goal}",
            "Use LangChain tool calls when a package capability is needed.",
            "Never claim a tool was executed unless a ToolMessage observation is present.",
        ]
        if instructions.boundaries:
            sections.append("Boundaries:\n" + "\n".join(f"- {item}" for item in instructions.boundaries))
        tool_text = _tool_manifest_text(package)
        if tool_text:
            sections.append(tool_text)
        memory_summary = updates.get("memory_summary") or state.get("memory_summary")
        if memory_summary:
            sections.append(f"Memory summary:\n{memory_summary}")
        if context_bundle.visible_to_model:
            sections.append(
                "Visible context:\n" + "\n".join(f"- {item}" for item in context_bundle.visible_to_model)
            )
        return [SystemMessage(content="\n\n".join(sections)), *window.recent_messages], updates

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

    def route(
        self,
        tool_call: RuntimeToolCall,
        *,
        approved_ref: str | None,
    ) -> ToolResultEnvelope | Any:
        router = ToolRouter(self.package_path, loader=self.loader)
        call_id = _tool_call_id(tool_call)
        tool_id = _tool_call_name(tool_call)
        invocation = ToolInvocation(
            invocation_id=call_id,
            tool_call_id=call_id,
            tool_id=tool_id,
            arguments=_tool_call_args(tool_call),
            approved=approved_ref in {call_id, tool_id},
        )
        route = router.route(invocation)
        if isinstance(route, ToolResultEnvelope):
            return route
        return route, invocation

    def execute(
        self,
        routed: tuple[Any, ToolInvocation],
        *,
        context_bundle: ContextBundle,
    ) -> ToolResultEnvelope:
        tool, invocation = routed
        executor = ToolExecutor(web_search_service=self.web_search_service, env_file=self.env_file)
        runtime_context = self.context_compiler.compile_tool_context(
            package_path=self.package_path,
            context_bundle=context_bundle,
            env_file=self.env_file,
        )
        return executor.execute(
            self.package_path,
            tool,
            invocation,
            runtime_context=runtime_context,
        )


class FileSystemCheckpointer(InMemorySaver):
    """LangGraph checkpointer backed by a package-local file for process resume."""

    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

    def put(self, config: Any, checkpoint: Any, metadata: Any, new_versions: Any) -> Any:
        result = super().put(config, checkpoint, metadata, new_versions)
        self._persist()
        return result

    def put_writes(
        self,
        config: Any,
        writes: Any,
        task_id: str,
        task_path: str = "",
    ) -> None:
        super().put_writes(config, writes, task_id, task_path)
        self._persist()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            payload = pickle.loads(self.path.read_bytes())
        except Exception:
            return
        self.storage.update(payload.get("storage") or {})
        self.writes.update(payload.get("writes") or {})
        self.blobs.update(payload.get("blobs") or {})

    def _persist(self) -> None:
        payload = {
            "storage": _plain_mapping(self.storage),
            "writes": _plain_mapping(self.writes),
            "blobs": _plain_mapping(self.blobs),
        }
        self.path.write_bytes(pickle.dumps(payload))


class TaskGraphCompiler:
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

    def compile(
        self,
        package_path: str | Path,
        *,
        chat_model: BaseChatModel | None = None,
        env_file: str | Path | None = None,
        web_search_service: FactoryWebSearchService | None = None,
        trace: Callable[[RuntimeEvent], None] | None = None,
        run_id: str,
        session_id: str,
    ) -> CompiledAgentRuntime:
        package_root = Path(package_path)
        package = self.loader.load_full_package(package_root)
        task_graph = package.task_graph
        tool_node = PolicyWrappedToolNode(
            package_path=package_root,
            loader=self.loader,
            env_file=env_file,
            context_compiler=self.context_compiler,
            web_search_service=web_search_service,
        )
        langchain_tools = _langchain_tools_for_package(package)
        runtime_chat_model = _bind_tools_if_supported(
            chat_model
            or build_runtime_chat_model(
                env_file=str(env_file) if env_file is not None else None,
                tool_definitions=_openai_tool_dicts_for_package(package),
                metadata={"agent": package.manifest.agent_id, "runtime": "langgraph_native"},
            ),
            langchain_tools,
        )
        capability_node = _first_node_of_type(task_graph, "capability")
        router_node = _first_node_of_type(task_graph, "router")
        checkpointer_path = _native_checkpoint_path(package_root, session_id)
        checkpointer = FileSystemCheckpointer(checkpointer_path)

        def make_model_node(node_id: str) -> Callable[[RuntimeGraphState], RuntimeGraphState]:
            def model_node(raw_state: RuntimeGraphState) -> RuntimeGraphState:
                state = _state_copy(raw_state)
                if int(state.get("turn_count") or 0) >= int(state.get("max_turns") or package.runtime.max_turns):
                    state["run_phase"] = "failed"
                    state["error"] = RuntimeErrorInfo(
                        type="max_turns_exceeded",
                        message="package.runtime.max_turns was exceeded.",
                    ).model_dump(mode="json")
                    _record(trace, run_id, "graph.limit", "failed", state["error"]["message"])
                    return state
                messages, context_updates = self.context_compiler.compile_model_context(
                    package=package,
                    state=state,
                )
                state.update(context_updates)
                try:
                    response = runtime_chat_model.invoke(messages)
                except RuntimeModelError as error:
                    state["run_phase"] = "failed"
                    state["error"] = error.error.model_dump(mode="json")
                    _record_model_span(trace, run_id, getattr(runtime_chat_model, "last_span", None))
                    _record(trace, run_id, "model", "failed", error.error.message)
                    return state
                _record_model_span(trace, run_id, getattr(runtime_chat_model, "last_span", None))
                if not isinstance(response, AIMessage):
                    response = AIMessage(content=_message_content(response))
                calls = [_normalize_tool_call(item) for item in response.tool_calls]
                clean_response = AIMessage(
                    content=_message_content(response),
                    tool_calls=calls,
                    response_metadata=dict(response.response_metadata),
                )
                state["messages"] = [*list(state.get("messages") or []), clean_response]
                if calls:
                    state["active_calls"] = calls
                    state["tool_calls"] = [*list(state.get("tool_calls") or []), *calls]
                    state["route_key"] = "needs_capability"
                    _record(
                        trace,
                        run_id,
                        f"task.{node_id}.model",
                        "completed",
                        payload={"tool_call_count": len(calls)},
                    )
                    return state
                answer = _message_content(response)
                if answer:
                    state["answer"] = answer
                state["route_key"] = "ready"
                _record(trace, run_id, f"task.{node_id}.model", "completed")
                return state

            return model_node

        def make_router_node(node_id: str) -> Callable[[RuntimeGraphState], RuntimeGraphState]:
            def router(raw_state: RuntimeGraphState) -> RuntimeGraphState:
                state = _state_copy(raw_state)
                if state.get("run_phase") in {"failed", "configuration_needed"}:
                    state["route_key"] = "end"
                elif state.get("active_calls"):
                    state["route_key"] = "needs_capability"
                elif (state.get("interrupt_payload") or {}).get("type") == "user_input_required":
                    state["route_key"] = "needs_user_input"
                else:
                    state["route_key"] = "ready"
                _record(
                    trace,
                    run_id,
                    f"task.{node_id}.router",
                    "completed",
                    payload={"route": state["route_key"]},
                )
                return state

            return router

        def make_capability_node(node_id: str) -> Callable[[RuntimeGraphState], RuntimeGraphState]:
            def capability(raw_state: RuntimeGraphState) -> RuntimeGraphState:
                state = _state_copy(raw_state)
                context_bundle = state.get("context_bundle") or ContextBundle()
                completed_results: list[ToolResultEnvelope] = []
                messages = list(state.get("messages") or [])
                for call in list(state.get("active_calls") or []):
                    approved_ref = _tool_call_id(call)
                    routed = tool_node.route(call, approved_ref=None)
                    if isinstance(routed, ToolResultEnvelope) and routed.status == "interrupted":
                        payload = _approval_payload(routed, call)
                        state["interrupt_payload"] = payload
                        _record(trace, run_id, "interrupt", "interrupted", routed.error, payload=payload)
                        resume_data = interrupt(payload)
                        approved_ref = _resume_approval_ref(resume_data)
                        routed = tool_node.route(call, approved_ref=approved_ref)
                    if isinstance(routed, ToolResultEnvelope):
                        result = routed
                    else:
                        result = tool_node.execute(routed, context_bundle=context_bundle)
                    completed_results.append(result)
                    messages.append(
                        ToolMessage(
                            content=self.context_compiler.compress_tool_observation(result),
                            tool_call_id=_tool_call_id(call),
                            name=_tool_call_name(call),
                        )
                    )
                    _record_tool_event(trace, run_id, result)
                    if result.status == "needs_configuration":
                        state["run_phase"] = "configuration_needed"
                    elif result.status in {"failed", "blocked"}:
                        state["run_phase"] = "failed"
                        state["error"] = RuntimeErrorInfo(
                            type="tool_failed",
                            message=result.error or f"Tool failed: {result.tool_id}",
                        ).model_dump(mode="json")
                state["messages"] = messages
                state["tool_results"] = [
                    *list(state.get("tool_results") or []),
                    *[item.model_dump(mode="json") for item in completed_results],
                ]
                state["active_calls"] = []
                state["turn_count"] = int(state.get("turn_count") or 0) + 1
                if int(state["turn_count"]) >= int(state.get("max_turns") or package.runtime.max_turns):
                    if state.get("run_phase") == "running":
                        state["run_phase"] = "failed"
                        state["error"] = RuntimeErrorInfo(
                            type="max_turns_exceeded",
                            message="package.runtime.max_turns was exceeded.",
                        ).model_dump(mode="json")
                _record(trace, run_id, f"task.{node_id}.capability", "completed")
                return state

            return capability

        def make_interrupt_node(node_id: str) -> Callable[[RuntimeGraphState], RuntimeGraphState]:
            def interrupt_node(raw_state: RuntimeGraphState) -> RuntimeGraphState:
                state = _state_copy(raw_state)
                payload = state.get("interrupt_payload") or {
                    "type": task_graph.nodes[node_id].interrupt_type or "user_input_required",
                    "message": "User input is required before continuing.",
                }
                _record(trace, run_id, "interrupt", "interrupted", payload=payload)
                resume_data = interrupt(payload)
                state["interrupt_payload"] = {
                    "type": "user_input_received",
                    "value": resume_data,
                }
                return state

            return interrupt_node

        graph = StateGraph(RuntimeGraphState)
        for node_id, node in task_graph.nodes.items():
            if node.type == "model" or node.type == "finalizer":
                graph.add_node(node_id, make_model_node(node_id))
            elif node.type == "router":
                graph.add_node(node_id, make_router_node(node_id))
            elif node.type == "capability":
                graph.add_node(node_id, make_capability_node(node_id))
            elif node.type == "interrupt":
                graph.add_node(node_id, make_interrupt_node(node_id))
            else:
                raise ValueError(f"Unsupported task graph node type: {node.type}")

        for edge in task_graph.edges:
            source = _graph_endpoint(edge.from_)
            target = _graph_endpoint(edge.to)
            if source in {START, END} or task_graph.nodes.get(str(edge.from_ or "")) is None:
                graph.add_edge(source, target)
                continue
            source_node = task_graph.nodes[edge.from_]
            if source_node.type not in {"model", "router"}:
                graph.add_edge(source, target)

        for node_id, node in task_graph.nodes.items():
            if node.type == "router":
                mapping = {
                    route.when: _graph_endpoint(route.to)
                    for route in node.routes
                }
                if not mapping:
                    mapping = {
                        "needs_capability": capability_node or END,
                        "needs_user_input": _first_node_of_type(task_graph, "interrupt") or END,
                        "ready": _first_final_node(task_graph) or END,
                        "end": END,
                    }
                mapping.setdefault("end", END)
                graph.add_conditional_edges(
                    node_id,
                    lambda state: str(state.get("route_key") or "ready"),
                    mapping,
                )
            elif node.type in {"model", "finalizer"}:
                normal_target = _first_static_target(task_graph, node_id) or END
                mapping = {"capability": capability_node or END, "next": normal_target}
                graph.add_conditional_edges(
                    node_id,
                    lambda state: "capability" if state.get("active_calls") else "next",
                    mapping,
                )

        return CompiledAgentRuntime(
            langgraph_app=graph.compile(checkpointer=checkpointer),
            langchain_tools=langchain_tools,
            runtime_context_factory=lambda req, bundle: self.context_compiler.compile_tool_context(
                package_path=package_root,
                context_bundle=bundle,
                env_file=env_file,
            ),
            policy_wrapped_tool_node=tool_node,
            trace_adapter=trace,
            memory_adapter=AgentMemoryStore(package_root, loader=self.loader),
            checkpoint_path=checkpointer_path,
        )


class RuntimeGraphCompiler:
    def __init__(
        self,
        *,
        loader: PackageLoader | None = None,
        context_manager: ContextManager | None = None,
        context_compiler: RuntimeContextCompiler | None = None,
    ) -> None:
        self.task_compiler = TaskGraphCompiler(
            loader=loader,
            context_manager=context_manager,
            context_compiler=context_compiler,
        )

    def compile(self, *args: Any, **kwargs: Any) -> CompiledAgentRuntime:
        return self.task_compiler.compile(*args, **kwargs)


class AgentInstanceRuntime:
    def __init__(
        self,
        *,
        chat_model: BaseChatModel | None = None,
        env_file: str | Path | None = None,
        loader: PackageLoader | None = None,
        context_manager: ContextManager | None = None,
        web_search_service: FactoryWebSearchService | None = None,
        compiler: RuntimeGraphCompiler | None = None,
        **_: Any,
    ) -> None:
        self.chat_model = chat_model
        self.env_file = Path(env_file) if env_file is not None else None
        self.loader = loader or PackageLoader()
        self.context_manager = context_manager or ContextManager(loader=self.loader)
        self.web_search_service = web_search_service
        self.compiler = compiler or RuntimeGraphCompiler(
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
            compiled = self.compiler.compile(
                package_path,
                chat_model=self.chat_model,
                env_file=self.env_file,
                web_search_service=self.web_search_service,
                trace=record,
                run_id=run_id,
                session_id=request.session_id,
            )
            graph_config = {
                "configurable": {"thread_id": _thread_id(package.manifest.agent_id, request.session_id)},
                "recursion_limit": max(10, package.runtime.max_turns * 6 + 8),
            }
            if request.approved_tool_call_id:
                record(
                    RuntimeEvent(
                        run_id=run_id,
                        stage="resume",
                        status="completed",
                        payload={"approved_tool_call_id": request.approved_tool_call_id},
                    )
                )
                output = compiled.langgraph_app.invoke(
                    Command(resume={"approved_tool_call_id": request.approved_tool_call_id}),
                    config=graph_config,
                )
            else:
                initial: RuntimeGraphState = {
                    "run_id": run_id,
                    "trace_id": run_id,
                    "session_id": request.session_id,
                    "messages": [*history, HumanMessage(content=request.user_input)],
                    "tool_calls": [],
                    "active_calls": [],
                    "tool_results": [],
                    "interrupt_payload": None,
                    "memory_summary": memory_summary,
                    "context_bundle": context_bundle,
                    "run_phase": "running",
                    "route_key": "ready",
                    "turn_count": 0,
                    "max_turns": package.runtime.max_turns,
                    "answer": "",
                    "error": None,
                    "usage": None,
                    "tool_summary_fallback": False,
                    "upgrade_request": None,
                    "context_compression_triggered": False,
                }
                output = compiled.langgraph_app.invoke(initial, config=graph_config)

            snapshot = compiled.langgraph_app.get_state(graph_config)
            state = _state_copy(snapshot.values or {})
            interrupt_payload = _interrupt_payload(output) or _snapshot_interrupt_payload(snapshot)
            if interrupt_payload:
                status: AgentRunStatus = "interrupted"
                state["interrupt_payload"] = interrupt_payload
                tool_results = _tool_results_from_state(state)
                if not tool_results:
                    synthetic = _interrupted_tool_result(interrupt_payload)
                    if synthetic is not None:
                        tool_results = [synthetic]
                answer = _fallback_answer(
                    request.user_input,
                    _intent_from_tool_proposals(list(state.get("tool_calls") or [])),
                    tool_results,
                )
            else:
                tool_results = _tool_results_from_state(state)
                status = _result_status(state)
                answer = state.get("answer") or _fallback_answer(
                    request.user_input,
                    _intent_from_tool_proposals(list(state.get("tool_calls") or [])),
                    tool_results,
                )

            record(
                RuntimeEvent(
                    run_id=run_id,
                    stage="checkpoint",
                    status="completed",
                    payload={
                        "checkpoint_path": str(compiled.checkpoint_path),
                        "session_id": request.session_id,
                        "thread_id": graph_config["configurable"]["thread_id"],
                    },
                )
            )
            if status == "completed":
                memory.append(
                    AgentMemoryRecord(
                        run_id=run_id,
                        session_id=request.session_id,
                        type="agent_turn",
                        summary=f"Handled intent={_intent_from_tool_proposals(list(state.get('tool_calls') or []))}",
                        payload={
                            "status": status,
                            "user_input": request.user_input,
                            "answer": answer,
                            "runtime_type": "langgraph_native",
                            "tool_results": [item.model_dump(mode="json") for item in tool_results],
                        },
                    )
                )
            record(
                RuntimeEvent(
                    run_id=run_id,
                    stage="complete" if status == "completed" else status,
                    status="completed" if status in {"completed", "needs_upgrade"} else status,
                    payload={
                        "intent": _intent_from_tool_proposals(list(state.get("tool_calls") or [])),
                        "tool_count": len(tool_results),
                        "session_id": request.session_id,
                        "history_turn_count": history_turn_count,
                        "runtime_type": "langgraph_native",
                        "context_compression_triggered": bool(state.get("context_compression_triggered")),
                    },
                )
            )
            return AgentRunResult(
                run_id=run_id,
                package_path=package_path,
                status=status,
                answer=answer,
                runtime_type="langgraph_native",
                session_id=request.session_id,
                history_turn_count=history_turn_count,
                intent=_intent_from_tool_proposals(list(state.get("tool_calls") or [])),
                trace_path=trace_path,
                memory_path=memory.path,
                checkpoint_path=compiled.checkpoint_path,
                events=events,
                context_bundle=context_bundle,
                context_compression_triggered=bool(state.get("context_compression_triggered")),
                tool_proposals=list(state.get("tool_calls") or []),
                tool_results=tool_results,
                usage=_token_usage(state.get("usage")),
                error=_model_error(state.get("error")),
                interrupt=interrupt_payload,
            )
        except RuntimeModelConfigError as error:
            model_error = RuntimeErrorInfo(type="model_config_error", message=str(error))
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
            model_error = RuntimeErrorInfo(type="runtime_error", message=str(error))
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


def _openai_tool_dicts_for_package(package: Any) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    for tool in package.generated_tools:
        if tool.exposure != "exposed":
            continue
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool.tool_id,
                    "description": _tool_description(tool),
                    "parameters": _tool_parameters_schema(tool.input_schema),
                },
            }
        )
    for capability in package.tools.builtin_capabilities:
        if capability.exposure != "exposed":
            continue
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": capability.id,
                    "description": _builtin_tool_description(capability),
                    "parameters": _builtin_tool_parameters_schema(capability),
                },
            }
        )
    return tools


def _langchain_tools_for_package(package: Any) -> list[Any]:
    try:
        from langchain_core.tools import StructuredTool
    except Exception:
        return []

    compiled = []
    for definition in _openai_tool_dicts_for_package(package):
        name = str(definition["function"].get("name") or "tool")
        description = str(definition["function"].get("description") or name)

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


def _bind_tools_if_supported(model: Any, tools: list[Any]) -> Any:
    if not tools or not hasattr(model, "bind_tools"):
        return model
    try:
        return model.bind_tools(tools)
    except Exception:
        return model


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
    lines = ["Available package capabilities:"]
    for tool in package.generated_tools:
        if tool.exposure != "exposed":
            continue
        approval = "approval_required" if tool.approval.required else "auto_routable"
        lines.append(
            f"- {tool.tool_id}: {tool.metadata.description or tool.metadata.name}; "
            f"risk={tool.risk_level}; {approval}; use a LangChain tool call."
        )
    for capability in package.tools.builtin_capabilities:
        if capability.exposure != "exposed":
            continue
        approval = "approval_required" if capability.approval_required else "auto_routable"
        lines.append(
            f"- {capability.id}: {capability.description}; "
            f"type={capability.type}; risk={capability.risk_level}; {approval}; use a LangChain tool call."
        )
    return "\n".join(lines) if len(lines) > 1 else ""


def _intent_from_tool_proposals(proposals: list[RuntimeToolCall]) -> str:
    if proposals:
        return _tool_call_name(proposals[0])
    return "in_scope"


def _fallback_answer(user_input: str, intent: str, tool_results: list[ToolResultEnvelope]) -> str:
    if tool_results:
        completed = [item for item in tool_results if item.status == "completed"]
        interrupted_results = [item for item in tool_results if item.status == "interrupted"]
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
        if interrupted_results:
            return f"该操作需要人工确认后才能执行：{interrupted_results[0].tool_id}。"
    return "我已根据当前 AgentPackage 的能力边界处理这次请求。"


def _history_turn_count(history: list[BaseMessage]) -> int:
    return sum(1 for message in history if isinstance(message, HumanMessage))


def _memory_summary(history: list[BaseMessage]) -> str | None:
    if not history:
        return None
    recent = history[-6:]
    return "\n".join(f"{_message_role(message)}: {_message_content(message)[:200]}" for message in recent)


def _result_status(state: RuntimeGraphState) -> AgentRunStatus:
    phase = state.get("run_phase")
    if phase == "configuration_needed":
        return "needs_configuration"
    if phase == "failed":
        return "failed"
    return "completed"


def _native_checkpoint_path(package_path: Path, session_id: str) -> Path:
    session_key = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    return package_path / "checkpoints" / f"langgraph_{session_key}.pkl"


def _thread_id(agent_id: str, session_id: str) -> str:
    return f"{agent_id}:{session_id}"


def _normalize_tool_call(tool_call: Any) -> RuntimeToolCall:
    if isinstance(tool_call, dict):
        return {
            "id": str(tool_call.get("id") or uuid.uuid4().hex),
            "name": str(tool_call.get("name") or "unknown_tool"),
            "args": dict(tool_call.get("args") or tool_call.get("arguments") or {}),
            "type": "tool_call",
        }
    return {
        "id": str(getattr(tool_call, "id", None) or uuid.uuid4().hex),
        "name": str(getattr(tool_call, "name", None) or "unknown_tool"),
        "args": dict(getattr(tool_call, "args", None) or getattr(tool_call, "arguments", None) or {}),
        "type": "tool_call",
    }


def _tool_call_id(tool_call: RuntimeToolCall) -> str:
    return str(tool_call.get("id") or uuid.uuid4().hex)


def _tool_call_name(tool_call: RuntimeToolCall) -> str:
    return str(tool_call.get("name") or "unknown_tool")


def _tool_call_args(tool_call: RuntimeToolCall) -> dict[str, Any]:
    args = tool_call.get("args") or tool_call.get("arguments") or {}
    return dict(args) if isinstance(args, dict) else {"value": args}


def _message_role(message: BaseMessage) -> str:
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, AIMessage):
        return "assistant"
    if isinstance(message, ToolMessage):
        return "tool"
    if isinstance(message, SystemMessage):
        return "system"
    return getattr(message, "type", "message")


def _message_content(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


def _record(
    trace: Callable[[RuntimeEvent], None] | None,
    run_id: str,
    stage: str,
    status: Literal["completed", "failed", "interrupted", "needs_configuration"],
    message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    if trace is None:
        return
    trace(
        RuntimeEvent(
            run_id=run_id,
            stage=stage,
            status=status,
            message=message,
            payload=payload or {},
        )
    )


def _record_model_span(
    trace: Callable[[RuntimeEvent], None] | None,
    run_id: str,
    span: dict[str, Any] | None,
) -> None:
    if trace is None or span is None:
        return
    status = span.get("status")
    trace(
        RuntimeEvent(
            run_id=run_id,
            stage="model_call",
            status="completed" if status == "completed" else "failed",
            message=span.get("error_type"),
            payload=dict(span),
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
                "needs_configuration"
                if result.status == "needs_configuration"
                else "failed"
                if result.status in {"failed", "blocked"}
                else "interrupted"
                if result.status == "interrupted"
                else "completed"
            ),
            message=result.error,
            payload={
                "tool_call_id": result.tool_call_id or result.invocation_id,
                "tool_id": result.tool_id,
                "status": result.status,
                "approval_required": result.approval_required,
            },
        )
    )


def _approval_payload(result: ToolResultEnvelope, tool_call: RuntimeToolCall) -> dict[str, Any]:
    return {
        "type": result.interrupt_type or "human_confirm",
        "tool_call_id": result.tool_call_id or result.invocation_id or _tool_call_id(tool_call),
        "tool_id": result.tool_id,
        "approval_required": result.approval_required,
        "reason": result.error or result.observation_summary,
        "message": f"该操作需要人工确认后才能执行：{result.tool_id}。",
    }


def _resume_approval_ref(value: Any) -> str | None:
    if isinstance(value, dict):
        return (
            str(value.get("approved_tool_call_id"))
            if value.get("approved_tool_call_id") is not None
            else str(value.get("tool_id")) if value.get("tool_id") is not None else None
        )
    if value is None:
        return None
    return str(value)


def _interrupt_payload(output: Any) -> dict[str, Any] | None:
    if not isinstance(output, dict) or "__interrupt__" not in output:
        return None
    items = output.get("__interrupt__") or []
    if not items:
        return None
    value = getattr(items[0], "value", None)
    return dict(value) if isinstance(value, dict) else {"value": value}


def _snapshot_interrupt_payload(snapshot: Any) -> dict[str, Any] | None:
    interrupts = getattr(snapshot, "interrupts", None) or ()
    if not interrupts:
        return None
    value = getattr(interrupts[0], "value", None)
    return dict(value) if isinstance(value, dict) else {"value": value}


def _interrupted_tool_result(payload: dict[str, Any]) -> ToolResultEnvelope | None:
    tool_id = payload.get("tool_id")
    if not tool_id:
        return None
    call_id = str(payload.get("tool_call_id") or uuid.uuid4().hex)
    return ToolResultEnvelope(
        invocation_id=call_id,
        tool_call_id=call_id,
        tool_id=str(tool_id),
        status="interrupted",
        error=str(payload.get("reason") or payload.get("message") or ""),
        observation_summary=str(payload.get("reason") or payload.get("message") or ""),
        interrupt_type=str(payload.get("type") or "human_confirm"),
        approval_required=bool(payload.get("approval_required", True)),
    )


def _tool_results_from_state(state: RuntimeGraphState) -> list[ToolResultEnvelope]:
    results: list[ToolResultEnvelope] = []
    for item in state.get("tool_results") or []:
        if isinstance(item, ToolResultEnvelope):
            results.append(item)
        elif isinstance(item, dict):
            results.append(ToolResultEnvelope.model_validate(item))
    return results


def _token_usage(value: Any) -> RuntimeTokenUsage | None:
    if value is None:
        return None
    if isinstance(value, RuntimeTokenUsage):
        return value
    if isinstance(value, dict):
        return RuntimeTokenUsage.model_validate(value)
    return None


def _model_error(value: Any) -> RuntimeErrorInfo | None:
    if value is None:
        return None
    if isinstance(value, RuntimeErrorInfo):
        return value
    if isinstance(value, dict):
        return RuntimeErrorInfo.model_validate(value)
    return RuntimeErrorInfo(type="runtime_error", message=str(value))


def _state_copy(state: RuntimeGraphState | dict[str, Any]) -> RuntimeGraphState:
    return dict(state)


def _graph_endpoint(value: str) -> Any:
    if value == "START":
        return START
    if value == "END":
        return END
    return value


def _first_node_of_type(task_graph: Any, node_type: str) -> str | None:
    for node_id, node in task_graph.nodes.items():
        if node.type == node_type:
            return node_id
    return None


def _first_final_node(task_graph: Any) -> str | None:
    for node_id, node in task_graph.nodes.items():
        if node.type == "finalizer" or node.purpose == "final_answer":
            return node_id
    return None


def _first_static_target(task_graph: Any, node_id: str) -> Any:
    for edge in task_graph.edges:
        if edge.from_ == node_id:
            return _graph_endpoint(edge.to)
    return None


def _plain_mapping(value: Any) -> Any:
    if isinstance(value, defaultdict):
        return {key: _plain_mapping(item) for key, item in value.items()}
    if isinstance(value, dict):
        return {key: _plain_mapping(item) for key, item in value.items()}
    return value
