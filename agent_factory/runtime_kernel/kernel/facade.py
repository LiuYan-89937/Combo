from __future__ import annotations

from pathlib import Path

from agent_factory.runtime_kernel.adapters import (
    InMemoryToolRegistry,
    ScriptedModelService,
)
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
from agent_factory.runtime_render import RenderManifest, default_node_render_spec, validate_render_manifest


class RuntimeKernelFacade:
    def __init__(
        self,
        *,
        builtins_dir: str | Path | None = None,
        checkpointer_config: LangGraphCheckpointerConfig | None = None,
        memory_store_config: LangGraphStoreConfig | None = None,
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
        memory_store = LangGraphStoreFactory().build(
            memory_store_config
            or LangGraphStoreConfig(
                backend="sqlite",
                path=Path(".agent_runtime/memory/agent.sqlite"),
            )
        ).store
        services = RuntimeServices(
            model_service=ScriptedModelService(),
            tool_registry=InMemoryToolRegistry(),
            memory_store=memory_store,
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
    ) -> CompiledKernelApp:
        services = services or self.instance.services
        bindings = bindings or BindingSet()
        pattern = self.instance.pattern_registry.get(pattern_id)
        resolved_render_manifest = _resolve_render_manifest(pattern, render_manifest)
        services.validate_required(_required_services_for_pattern(pattern))
        return self.instance.compiler.compile(
            pattern_id=pattern_id,
            bindings=bindings,
            services=services,
            render_manifest=resolved_render_manifest,
        )

    def run(
        self,
        compiled: CompiledKernelApp,
        *,
        user_input: str,
        user_config: dict | None = None,
        agent_config: dict | None = None,
        session_config: dict | None = None,
    ) -> RuntimeState:
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
        state.runtime_config.user_config = dict(user_config or {})
        state.runtime_config.agent_config = agent_config
        state.runtime_config.session_config = {
            **session_config,
            "session_id": session.session_id,
            "thread_id": session.thread_id,
        }
        result = self.instance.controller.run(compiled, state, thread_id=session.thread_id)
        session_manager.touch_turn(session.session_id, first_user_input=user_input)
        return result

    def resume(
        self,
        compiled: CompiledKernelApp,
        *,
        session_id: str,
        resume_payload: dict | None = None,
        session_config: dict | None = None,
    ) -> RuntimeState:
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
        return self.instance.controller.resume(
            compiled,
            state,
            thread_id=session.thread_id,
            resume_payload=resume_payload,
        )


def _required_services_for_pattern(pattern) -> list[str]:
    required = {"observability_manager", "checkpointer", "memory_store"}
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
