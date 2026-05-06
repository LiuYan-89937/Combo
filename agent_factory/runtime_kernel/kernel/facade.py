from __future__ import annotations

from pathlib import Path

from agent_factory.runtime_kernel.adapters import (
    InMemoryToolRegistry,
    ScriptedModelService,
)
from agent_factory.runtime_kernel.bindings import BindingSet, RuntimeServices
from agent_factory.runtime_kernel.checkpoint import FilesystemCheckpointManager
from agent_factory.runtime_kernel.context import ContextEngine
from agent_factory.runtime_kernel.execution import ExecutionController
from agent_factory.runtime_kernel.knowledge import KnowledgeEngine
from agent_factory.runtime_kernel.kernel.models import CompiledKernelApp, RuntimeKernelInstance
from agent_factory.runtime_kernel.memory import InMemoryMemoryEngine
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
    OperationalMemoryRetrieveNode,
    OperationalResourceProbeNode,
    OperationalToolCallNode,
    TerminalCloseNode,
    TerminalCommitNode,
)
from agent_factory.runtime_kernel.observability import ObservabilityManager
from agent_factory.runtime_kernel.patterns.compiler import PatternCompiler
from agent_factory.runtime_kernel.patterns.registry import PatternRegistry
from agent_factory.runtime_kernel.patterns.validator import PatternValidator
from agent_factory.runtime_kernel.policy import PolicyEngine
from agent_factory.runtime_kernel.state import RuntimeState


class RuntimeKernelFacade:
    def __init__(self, *, builtins_dir: str | Path | None = None) -> None:
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
            OperationalMemoryRetrieveNode(),
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
        services = RuntimeServices(
            model_service=ScriptedModelService(),
            tool_registry=InMemoryToolRegistry(),
            memory_engine=InMemoryMemoryEngine(),
            knowledge_engine=KnowledgeEngine(),
            context_engine=ContextEngine(),
            policy_engine=PolicyEngine(),
            observability_manager=ObservabilityManager(),
            checkpoint_manager=FilesystemCheckpointManager(),
        )
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
    ) -> CompiledKernelApp:
        services = services or self.instance.services
        bindings = bindings or BindingSet()
        pattern = self.instance.pattern_registry.get(pattern_id)
        services.validate_required(_required_services_for_pattern(pattern))
        return self.instance.compiler.compile(
            pattern_id=pattern_id,
            bindings=bindings,
            services=services,
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
        state = RuntimeState()
        state.run.pattern_id = compiled.pattern_spec.pattern_id
        state.run.pattern_version = compiled.pattern_spec.version
        state.conversation.current_user_input = user_input
        state.runtime_config.user_config = dict(user_config or {})
        state.runtime_config.agent_config = dict(agent_config or {})
        state.runtime_config.session_config = dict(session_config or {})
        return self.instance.controller.run(compiled, state)

    def resume(
        self,
        compiled: CompiledKernelApp,
        *,
        checkpoint_id: str,
        resume_payload: dict | None = None,
    ) -> RuntimeState:
        record = compiled.services.checkpoint_manager.load(checkpoint_id)
        state = self.instance.controller.checkpoint_serializer.from_record(record)
        return self.instance.controller.resume(compiled, state, resume_payload=resume_payload)


def _required_services_for_pattern(pattern) -> list[str]:
    required = {"observability_manager", "checkpoint_manager"}
    for node in pattern.nodes:
        if node.impl.startswith("cognitive."):
            required.update({"model_service", "context_engine"})
        elif node.impl == "governance.precheck" or node.impl == "governance.postcheck":
            required.add("policy_engine")
        elif node.impl.startswith("operational.tool_call"):
            required.add("tool_registry")
        elif node.impl.startswith("operational.memory_retrieve") or node.impl.startswith("terminal.commit"):
            required.add("memory_engine")
        elif node.impl.startswith("operational.knowledge_retrieve"):
            required.add("knowledge_engine")
        for wrapper in node.wrappers:
            if wrapper.id.startswith("context."):
                required.add("context_engine")
            elif wrapper.id.startswith("memory."):
                required.add("memory_engine")
            elif wrapper.id.startswith("policy."):
                required.add("policy_engine")
            elif wrapper.id.startswith("tool."):
                required.add("tool_registry")
    for capability in pattern.constraints.required_capabilities:
        if capability == "tools":
            required.add("tool_registry")
        elif capability == "memory":
            required.add("memory_engine")
        elif capability == "knowledge":
            required.add("knowledge_engine")
        elif capability == "context":
            required.add("context_engine")
        elif capability == "policy":
            required.add("policy_engine")
        elif capability == "harness":
            required.add("harness_bridge")
    return sorted(required)
