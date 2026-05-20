from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_factory.runtime_kernel.adapters import InMemoryToolRegistry
from agent_factory.memory_system import (
    MemorySystemConfig,
    default_agent_memory_config,
    default_agent_runtime,
)
from agent_factory.memory_system.background import MemoryBackgroundWorker
from agent_factory.memory_system.namespace import agent_memory_namespace
from agent_factory.memory_system.store_index import build_memory_store_index
from agent_factory.runtime_kernel.bindings import BindingSet, RuntimeServices
from agent_factory.runtime_kernel.context import ContextEngine
from agent_factory.runtime_kernel.execution import ExecutionController
from agent_factory.runtime_kernel.knowledge import KnowledgeEngine
from agent_factory.runtime_kernel.kernel.models import CompiledKernelApp, RuntimeKernelInstance
from agent_factory.runtime_kernel.nodes.registry import NodeRegistry
from agent_factory.runtime_kernel.nodes.standard import (
    CognitiveAnswerNode,
    CognitiveClarifyNode,
    CognitivePlanNode,
    CognitiveReviewNode,
    CognitiveRouteNode,
    FinalizeNode,
    GovernanceApprovalGateNode,
    GovernancePostcheckNode,
    GovernancePrecheckNode,
    GovernanceRefusalGateNode,
    IngressNode,
    OperationalKnowledgeRetrieveNode,
    OperationalResourceProbeNode,
    OperationalToolCallNode,
    TerminalCloseNode,
    TerminalCommitNode,
)
from agent_factory.runtime_kernel.observability import ObservabilityManager
from agent_factory.runtime_kernel.patterns.compiler import PatternCompiler
from agent_factory.runtime_kernel.patterns.registry import PatternRegistry
from agent_factory.runtime_kernel.patterns.validator import PatternValidator
from agent_factory.runtime_kernel.persistence import (
    LangGraphCheckpointerConfig,
    LangGraphCheckpointerFactory,
    LangGraphStoreConfig,
    LangGraphStoreFactory,
)
from agent_factory.runtime_kernel.policy import PolicyEngine
from agent_factory.runtime_kernel.session import AgentSessionConfig, AgentSessionManager
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_kernel.background_workers import RuntimeBackgroundWorkerManager
from agent_factory.runtime_render import RenderManifest, default_node_render_spec, validate_render_manifest
from agent_factory.runtime_kernel.wrappers.system_registry import DEFAULT_RUNTIME_SYSTEM_WRAPPER_IDS


@dataclass(slots=True)
class RuntimeKernelRunContext:
    state: RuntimeState
    thread_id: str
    session_manager: AgentSessionManager
    session_id: str
    first_user_input: str


class RuntimeKernelFacade:
    def __init__(
        self,
        *,
        builtins_dir: str | Path | None = None,
        checkpointer_config: LangGraphCheckpointerConfig | None = None,
        memory_store_config: LangGraphStoreConfig | None = None,
        memory_system_config: MemorySystemConfig | dict | None = None,
        session_config: AgentSessionConfig | None = None,
    ) -> None:
        builtins_dir = builtins_dir or Path(__file__).resolve().parents[1] / "patterns" / "builtins"
        node_registry = NodeRegistry()
        for impl in [
            IngressNode(),
            GovernancePrecheckNode(),
            GovernancePostcheckNode(),
            GovernanceApprovalGateNode(),
            GovernanceRefusalGateNode(),
            CognitiveClarifyNode(),
            CognitivePlanNode(),
            CognitiveRouteNode(),
            CognitiveAnswerNode(),
            CognitiveReviewNode(),
            OperationalToolCallNode(),
            OperationalKnowledgeRetrieveNode(),
            OperationalResourceProbeNode(),
            TerminalCommitNode(),
            TerminalCloseNode(),
            FinalizeNode(),
        ]:
            node_registry.register(impl)
        pattern_registry = PatternRegistry(builtins_dir=builtins_dir)
        validator = PatternValidator()
        compiler = PatternCompiler(node_registry=node_registry, pattern_registry=pattern_registry, validator=validator)
        controller = ExecutionController()
        checkpointer = LangGraphCheckpointerFactory().build(
            checkpointer_config
            or LangGraphCheckpointerConfig(
                backend="sqlite",
                path=Path(".agent_runtime/checkpoints/agent.sqlite"),
            )
        ).saver
        memory_config = (
            memory_system_config
            if isinstance(memory_system_config, MemorySystemConfig)
            else MemorySystemConfig.model_validate(memory_system_config or default_agent_memory_config().model_dump(mode="json"))
        )
        resolved_memory_store_config = memory_store_config or LangGraphStoreConfig(
            backend=memory_config.store.backend,
            path=Path(memory_config.store.path) if memory_config.store.backend == "sqlite" else None,
            index=build_memory_store_index(memory_config),
        )
        memory_store = LangGraphStoreFactory().build(resolved_memory_store_config).store
        memory_runtime = default_agent_runtime(
            agent_id="default-agent",
            config=memory_config,
            store=memory_store,
        )
        self.background_workers = RuntimeBackgroundWorkerManager()
        self._default_memory_worker: MemoryBackgroundWorker | None = None
        if memory_config.write_enabled:
            worker = MemoryBackgroundWorker(store=memory_store, config=memory_config)
            memory_runtime.writer = worker
            self._default_memory_worker = worker
            self.background_workers.add(worker)
        services = RuntimeServices(
            model_service=None,
            tool_registry=InMemoryToolRegistry(),
            memory_store=memory_store,
            memory_system=memory_runtime,
            knowledge_engine=KnowledgeEngine(),
            context_engine=ContextEngine(),
            policy_engine=PolicyEngine(),
            observability_manager=ObservabilityManager(),
            checkpointer=checkpointer,
        )
        self.session_manager = AgentSessionManager(session_config)
        self.instance = RuntimeKernelInstance(
            services=services,
            node_registry=node_registry,
            pattern_registry=pattern_registry,
            validator=validator,
            compiler=compiler,
            controller=controller,
        )

    def compile(
        self,
        *,
        pattern_id: str,
        bindings: BindingSet | None = None,
        services: RuntimeServices | None = None,
        render_manifest: RenderManifest | dict | None = None,
        system_wrapper_ids: list[str] | tuple[str, ...] | None = None,
    ) -> CompiledKernelApp:
        services = services or self.instance.services
        if services is self.instance.services:
            self._start_default_background_workers()
        bindings = bindings or BindingSet()
        pattern = self.instance.pattern_registry.get(pattern_id)
        resolved_render_manifest = _resolve_render_manifest(pattern, render_manifest)
        _ensure_memory_runtime(services)
        services.validate_required(_required_services_for_pattern(pattern))
        return self.instance.compiler.compile(
            pattern_id=pattern_id,
            bindings=bindings,
            services=services,
            render_manifest=resolved_render_manifest,
            system_wrapper_ids=DEFAULT_RUNTIME_SYSTEM_WRAPPER_IDS if system_wrapper_ids is None else system_wrapper_ids,
        )

    def _start_default_background_workers(self) -> None:
        if self._default_memory_worker is None:
            return
        events = self.background_workers.start_all()
        if any(event.status == "failed" and event.worker_type == "MemoryBackgroundWorker" for event in events):
            memory_system = getattr(self.instance.services, "memory_system", None)
            if memory_system is not None:
                memory_system.writer = None

    def shutdown(self) -> None:
        self.background_workers.shutdown_all()

    def run(
        self,
        compiled: CompiledKernelApp,
        *,
        user_input: str,
        user_config: dict | None = None,
        agent_config: dict | None = None,
        session_config: dict | None = None,
    ) -> RuntimeState:
        run_context = self.prepare_run_context(
            compiled,
            user_input=user_input,
            user_config=user_config,
            agent_config=agent_config,
            session_config=session_config,
        )
        result = self.instance.controller.run(compiled, run_context.state, thread_id=run_context.thread_id)
        run_context.session_manager.touch_turn(run_context.session_id, first_user_input=run_context.first_user_input)
        return result

    def stream(
        self,
        compiled: CompiledKernelApp,
        *,
        user_input: str,
        user_config: dict | None = None,
        agent_config: dict | None = None,
        session_config: dict | None = None,
    ) -> Iterator[tuple[str, Any]]:
        run_context = self.prepare_run_context(
            compiled,
            user_input=user_input,
            user_config=user_config,
            agent_config=agent_config,
            session_config=session_config,
        )
        final_seen = False
        for item in self.instance.controller.stream(compiled, run_context.state, thread_id=run_context.thread_id):
            if item[0] == "runtime_final":
                final_seen = True
            yield item
        if final_seen:
            run_context.session_manager.touch_turn(run_context.session_id, first_user_input=run_context.first_user_input)

    def prepare_run_context(
        self,
        compiled: CompiledKernelApp,
        *,
        user_input: str,
        user_config: dict | None = None,
        agent_config: dict | None = None,
        session_config: dict | None = None,
    ) -> RuntimeKernelRunContext:
        agent_config = dict(agent_config or {})
        session_config = dict(session_config or {})
        agent_id = str(agent_config.get("agent_id") or compiled.metadata.get("agent_id") or compiled.pattern_spec.pattern_id)
        session_manager = _session_manager_from_config(session_config, default=self.session_manager)
        session_id = session_config.get("session_id")
        session = session_manager.load(str(session_id)) if session_id else session_manager.create(
            agent_id=agent_id,
            first_user_input=user_input,
        )
        state = RuntimeState()
        state.run.agent_id = agent_id
        state.run.session_id = session.session_id
        state.run.pattern_id = compiled.pattern_spec.pattern_id
        state.run.pattern_version = compiled.pattern_spec.version
        state.conversation.current_user_input = user_input
        state.conversation.turn_index = int(session.turn_count or 0)
        state.runtime_config.user_config = dict(user_config or {})
        state.runtime_config.agent_config = agent_config
        state.runtime_config.session_config = {
            **session_config,
            "session_id": session.session_id,
            "thread_id": session.thread_id,
        }
        _configure_memory_runtime_for_agent(compiled.services, agent_id)
        return RuntimeKernelRunContext(
            state=state,
            thread_id=session.thread_id,
            session_manager=session_manager,
            session_id=session.session_id,
            first_user_input=user_input,
        )

    def resume(
        self,
        compiled: CompiledKernelApp,
        *,
        session_id: str,
        resume_payload: dict | None = None,
        session_config: dict | None = None,
    ) -> RuntimeState:
        run_context = self.prepare_resume_context(
            compiled,
            session_id=session_id,
            session_config=session_config,
        )
        return self.instance.controller.resume(
            compiled,
            run_context.state,
            thread_id=run_context.thread_id,
            resume_payload=resume_payload,
        )

    def stream_resume(
        self,
        compiled: CompiledKernelApp,
        *,
        session_id: str,
        resume_payload: dict | None = None,
        session_config: dict | None = None,
    ) -> Iterator[tuple[str, Any]]:
        run_context = self.prepare_resume_context(
            compiled,
            session_id=session_id,
            session_config=session_config,
        )
        final_seen = False
        for item in self.instance.controller.stream_resume(
            compiled,
            run_context.state,
            thread_id=run_context.thread_id,
            resume_payload=resume_payload,
        ):
            if item[0] == "runtime_final":
                final_seen = True
            yield item
        if final_seen:
            run_context.session_manager.touch_turn(run_context.session_id)

    def prepare_resume_context(
        self,
        compiled: CompiledKernelApp,
        *,
        session_id: str,
        session_config: dict | None = None,
    ) -> RuntimeKernelRunContext:
        session_manager = _session_manager_from_config(session_config or {}, default=self.session_manager)
        session = session_manager.load(session_id)
        state = RuntimeState()
        state.run.agent_id = session.agent_id
        state.run.session_id = session.session_id
        state.run.pattern_id = compiled.pattern_spec.pattern_id
        state.run.pattern_version = compiled.pattern_spec.version
        state.runtime_config.session_config = {
            **dict(session_config or {}),
            "session_id": session.session_id,
            "thread_id": session.thread_id,
        }
        _configure_memory_runtime_for_agent(compiled.services, session.agent_id)
        return RuntimeKernelRunContext(
            state=state,
            thread_id=session.thread_id,
            session_manager=session_manager,
            session_id=session.session_id,
            first_user_input=session.first_user_input or "",
        )


def _required_services_for_pattern(pattern) -> list[str]:
    required = {"observability_manager", "checkpointer"}
    for node in pattern.nodes:
        if node.impl.startswith("cognitive."):
            required.update({"model_service", "context_engine"})
        elif node.impl == "governance.precheck" or node.impl == "governance.postcheck":
            required.add("policy_engine")
        elif node.impl.startswith("operational.tool_call"):
            required.add("tool_registry")
        elif node.impl.startswith("operational.knowledge_retrieve"):
            required.add("knowledge_engine")
        for wrapper in node.wrappers:
            if wrapper.id.startswith("context."):
                required.add("context_engine")
            elif wrapper.id.startswith("policy."):
                required.add("policy_engine")
            elif wrapper.id.startswith("tool."):
                required.add("tool_registry")
    for capability in pattern.constraints.required_capabilities:
        if capability == "tools":
            required.add("tool_registry")
        elif capability == "knowledge":
            required.add("knowledge_engine")
        elif capability == "context":
            required.add("context_engine")
        elif capability == "policy":
            required.add("policy_engine")
        elif capability == "harness":
            required.add("harness_bridge")
    return sorted(required)


def _ensure_memory_runtime(services: RuntimeServices) -> None:
    if services.memory_system is None:
        return
    runtime = services.memory_system
    config = getattr(runtime, "config", None)
    if config is None or not getattr(config, "enabled", False):
        return
    if getattr(runtime, "store", None) is None:
        if services.memory_store is None:
            raise RuntimeError("cross-session memory is enabled but BaseStore is missing")
        runtime.store = services.memory_store


def _configure_memory_runtime_for_agent(services: RuntimeServices, agent_id: str) -> None:
    runtime = getattr(services, "memory_system", None)
    if runtime is None:
        return
    runtime.scope = "agent"
    runtime.namespace = agent_memory_namespace(agent_id)


def _session_manager_from_config(session_config: dict, *, default: AgentSessionManager) -> AgentSessionManager:
    root = session_config.get("session_root")
    if root:
        return AgentSessionManager(AgentSessionConfig(root=Path(str(root))))
    return default


def _resolve_render_manifest(pattern, render_manifest: RenderManifest | dict | None) -> RenderManifest:
    if render_manifest is None:
        manifest = RenderManifest(
            graph_id=pattern.pattern_id,
            nodes={
                node.id: default_node_render_spec(node_id=node.id, node_type=node.type, impl=node.impl)
                for node in pattern.nodes
            },
        )
    elif isinstance(render_manifest, RenderManifest):
        manifest = render_manifest
    else:
        manifest = RenderManifest.model_validate(render_manifest)
    return validate_render_manifest(manifest, {node.id for node in pattern.nodes})
