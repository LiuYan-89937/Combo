from __future__ import annotations

from copy import deepcopy
from time import perf_counter
from typing import Any

from langgraph.graph import END, START, StateGraph

from agent_factory.runtime_kernel.bindings import BindingSet, RuntimeServices
from agent_factory.runtime_kernel.kernel.models import CompiledKernelApp
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.nodes.registry import NodeRegistry
from agent_factory.runtime_kernel.observability.schema import TraceEvent
from agent_factory.runtime_kernel.patterns.registry import PatternRegistry
from agent_factory.runtime_kernel.patterns.schema import GraphPatternSpec, PatternIOContractSpec, PatternNodeSpec
from agent_factory.runtime_kernel.patterns.validator import PatternValidator
from agent_factory.runtime_kernel.state import RuntimeState


class PatternCompiler:
    def __init__(
        self,
        *,
        node_registry: NodeRegistry,
        pattern_registry: PatternRegistry,
        validator: PatternValidator,
    ) -> None:
        self.node_registry = node_registry
        self.pattern_registry = pattern_registry
        self.validator = validator

    def compile(
        self,
        *,
        pattern_id: str,
        bindings: BindingSet,
        services: RuntimeServices,
    ) -> CompiledKernelApp:
        pattern = self.pattern_registry.get(pattern_id)
        self.validator.validate(pattern, known_patterns=set(self.pattern_registry.list_pattern_ids()))
        node_runners = {
            node.id: self._make_node_runner(node=node, pattern=pattern, bindings=bindings, services=services)
            for node in pattern.nodes
        }
        graph = StateGraph(dict)
        for node_id, runner in node_runners.items():
            graph.add_node(node_id, runner)
        graph.add_edge(START, pattern.entry_node)
        outgoing = {}
        for edge in pattern.edges:
            outgoing.setdefault(edge.from_, {})[edge.when] = edge.to
        for node in pattern.nodes:
            if node.id in pattern.termination.success_nodes or node.id in pattern.termination.failure_nodes:
                graph.add_edge(node.id, END)
                continue
            mapping = dict(outgoing.get(node.id, {}))
            mapping["__end__"] = END
            graph.add_conditional_edges(node.id, self._route_from_state, mapping)
        graph_app = graph.compile()
        return CompiledKernelApp(
            pattern_spec=pattern,
            graph_app=graph_app,
            services=services,
            bindings=bindings,
            metadata={"compiled_pattern_id": pattern.pattern_id},
            node_runners=node_runners,
        )

    def _make_node_runner(
        self,
        *,
        node: PatternNodeSpec,
        pattern: GraphPatternSpec,
        bindings: BindingSet,
        services: RuntimeServices,
    ):
        node_bindings = [
            item.model_dump(mode="json")
            for item in bindings.node_bindings
            if item.target.node_id == node.id and item.target.impl == node.impl
        ]
        hook_bindings = [item.model_dump(mode="json") for item in bindings.hooks if item.enabled]
        if node.type == "sub_graph":
            child = self.compile(pattern_id=node.pattern_ref or "", bindings=bindings, services=services)
            _validate_subgraph_exit_routes(node_id=node.id, pattern=pattern, child=child.pattern_spec)
            return _make_subgraph_runner(
                node_id=node.id,
                compiled=child,
                services=services,
                input_contract=child.pattern_spec.input_contract,
                output_contract=child.pattern_spec.output_contract,
                state_mode=child.pattern_spec.state_mode,
            )
        impl = self.node_registry.get(node.impl)

        def runner(raw_state: dict[str, Any]) -> dict[str, Any]:
            state = RuntimeState.model_validate(raw_state)
            started = perf_counter()
            span = services.observability_manager.start_span(
                trace_id=state.observability.trace_id,
                run_id=state.run.run_id,
                span_type="node_execution",
                name=node.id,
                metadata={"impl": node.impl},
            )
            emitted_events: list[dict[str, Any]] = []

            def emit_event(payload: dict[str, Any]) -> None:
                event = TraceEvent(
                    trace_id=state.observability.trace_id,
                    run_id=state.run.run_id,
                    event_type=payload.get("event_type", "node_event"),
                    node_id=node.id,
                    payload=payload,
                )
                services.observability_manager.emit(event)
                emitted_events.append(event.model_dump(mode="json"))

            context = NodeExecutionContext(
                node_id=node.id,
                impl=node.impl,
                bindings=node_bindings,
                hook_bindings=hook_bindings,
                services=services,
                emit_event=emit_event,
            )
            working_state, pre_patch = _run_pre_hooks(state, context)
            patch = impl.execute(working_state, context)
            _validate_patch_sections(node.impl, patch)
            post_patch = _run_post_hooks(working_state, context)
            merged = _merge_patches(pre_patch, patch)
            if post_patch:
                merged = _merge_patches(merged, post_patch)
            if emitted_events:
                merged.setdefault("observability", {})
                merged["observability"] = {
                    **merged["observability"],
                    "events": [*state.observability.events, *emitted_events],
                }
            _apply_metrics_patch(working_state, merged, perf_counter() - started)
            services.observability_manager.finish_span(
                span.span_id,
                trace_id=state.observability.trace_id,
                run_id=state.run.run_id,
                status="completed",
                metadata={"node_id": node.id},
            )
            return merged

        return runner

    @staticmethod
    def _route_from_state(raw_state: dict[str, Any]) -> str:
        state = RuntimeState.model_validate(raw_state)
        return state.execution.route_decision or "__end__"


def _make_subgraph_runner(
    *,
    node_id: str,
    compiled: CompiledKernelApp,
    services: RuntimeServices,
    input_contract: PatternIOContractSpec,
    output_contract: PatternIOContractSpec,
    state_mode: str,
):
    from agent_factory.runtime_kernel.execution import ExecutionController

    controller = ExecutionController()

    def runner(raw_state: dict[str, Any]) -> dict[str, Any]:
        parent_state = RuntimeState.model_validate(raw_state)
        entered = TraceEvent(
            trace_id=parent_state.observability.trace_id,
            run_id=parent_state.run.run_id,
            event_type="subgraph_entered",
            node_id=node_id,
            subgraph_id=compiled.pattern_spec.pattern_id,
        )
        services.observability_manager.emit(entered)
        child_input = _project_state_for_subgraph(
            parent_state,
            input_contract=input_contract,
            state_mode=state_mode,
        )
        child_input.execution.current_subgraph = compiled.pattern_spec.pattern_id
        child_state = controller.run(compiled, child_input)
        route = child_state.execution.route_decision or ""
        if route.startswith("subgraph."):
            exit_route = route.split(".", 1)[1]
        else:
            exit_route = child_state.execution.finish_status or "done"
            if exit_route == "completed":
                exit_route = "done"
        merged_sections = _merge_subgraph_output(parent_state, child_state, output_contract)
        exited = TraceEvent(
            trace_id=parent_state.observability.trace_id,
            run_id=parent_state.run.run_id,
            event_type="subgraph_exited",
            node_id=node_id,
            subgraph_id=compiled.pattern_spec.pattern_id,
            payload={"exit_route": exit_route},
        )
        services.observability_manager.emit(exited)
        return {
            **merged_sections,
            "execution": {
                "current_node": node_id,
                "route_decision": f"subgraph.{exit_route}",
                "current_subgraph": None,
            },
            "observability": {
                "events": [*parent_state.observability.events, entered.model_dump(mode="json"), *child_state.observability.events, exited.model_dump(mode="json")],
                "debug_refs": [*parent_state.observability.debug_refs, *child_state.observability.debug_refs],
                "metrics": {
                    **parent_state.observability.metrics,
                    "subgraph_count": int(parent_state.observability.metrics.get("subgraph_count", 0)) + 1,
                },
            },
        }

    return runner


def _run_pre_hooks(state: RuntimeState, context: NodeExecutionContext) -> tuple[RuntimeState, dict[str, Any]]:
    updated = state.model_copy(deep=True)
    patch: dict[str, Any] = {}
    if context.impl.startswith("cognitive."):
        prompt_binding = _first_binding_payload(context.bindings, "prompt")
        updated.context.model_context = context.services.context_engine.build_model_context(
            state=updated,
            binding=prompt_binding,
        )
        updated.context.assembly_log.append(f"auto_pre_cognitive:{context.node_id}")
        patch["context"] = updated.context.model_dump(mode="json")
    elif context.impl.startswith("operational."):
        tool_binding = _first_binding_payload(context.bindings, "tool_access") or _first_binding_payload(context.bindings, "retrieval_profile")
        updated.context.tool_context = context.services.context_engine.build_tool_context(
            state=updated,
            binding=tool_binding,
        )
        updated.context.assembly_log.append(f"auto_pre_operational:{context.node_id}")
        patch["context"] = updated.context.model_dump(mode="json")
    for hook in sorted(context.hook_bindings, key=lambda item: int(item.get("order", 0))):
        point = hook.get("hook_point")
        if context.impl.startswith("cognitive.") and point == "pre_cognitive":
            prompt_binding = _first_binding_payload(context.bindings, "prompt")
            updated.context.model_context = context.services.context_engine.build_model_context(
                state=updated,
                binding=prompt_binding,
            )
            updated.context.assembly_log.append(f"pre_cognitive:{context.node_id}")
            patch["context"] = updated.context.model_dump(mode="json")
        elif context.impl.startswith("operational.") and point == "pre_operational":
            tool_binding = _first_binding_payload(context.bindings, "tool_access") or _first_binding_payload(context.bindings, "retrieval_profile")
            updated.context.tool_context = context.services.context_engine.build_tool_context(
                state=updated,
                binding=tool_binding,
            )
            updated.context.assembly_log.append(f"pre_operational:{context.node_id}")
            patch["context"] = updated.context.model_dump(mode="json")
        elif context.impl.startswith("governance.") and point == "pre_governance":
            updated.policy.checks.append({"hook": point, "node_id": context.node_id})
            patch["policy"] = updated.policy.model_dump(mode="json")
        elif context.impl.startswith("terminal.") and point == "pre_terminal":
            updated.observability.debug_refs.append({"kind": "hook", "phase": point, "node_id": context.node_id})
            patch["observability"] = updated.observability.model_dump(mode="json")
    return updated, patch


def _run_post_hooks(state: RuntimeState, context: NodeExecutionContext) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    debug_refs: list[dict[str, Any]] = []
    for hook in sorted(context.hook_bindings, key=lambda item: int(item.get("order", 0))):
        point = hook.get("hook_point")
        if point in {"post_cognitive", "post_operational", "post_governance", "post_terminal"}:
            debug_refs.append({"kind": "hook", "phase": point, "node_id": context.node_id})
        elif point == "on_interrupt" and (state.policy.interrupted or state.execution.interrupted):
            debug_refs.append({"kind": "hook", "phase": point, "node_id": context.node_id})
        elif point == "on_resume":
            debug_refs.append({"kind": "hook", "phase": point, "node_id": context.node_id})
    if debug_refs:
        patch["observability"] = {"debug_refs": [*state.observability.debug_refs, *debug_refs]}
    if context.impl.startswith("terminal.") or context.impl == "finalize":
        formatter = _first_binding_payload(context.bindings, "output_formatter")
        if formatter and formatter.get("mode") == "prefix" and state.conversation.final_answer:
            patch.setdefault("conversation", {})
            patch["conversation"]["final_answer"] = f"{formatter.get('config', {}).get('prefix', '')}{state.conversation.final_answer}"
    return patch


def _first_binding_payload(bindings: list[dict[str, Any]], binding_type: str) -> dict[str, Any] | None:
    for binding in bindings:
        if binding.get("binding_type") == binding_type:
            return dict(binding.get("payload") or {})
    return None


def _validate_patch_sections(impl_id: str, patch: dict[str, Any]) -> None:
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

    implementations = {
        item.impl_id: item
        for item in [
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
        ]
    }
    allowed = implementations[impl_id].writable_sections
    patch_sections = set(patch)
    illegal = patch_sections.difference(allowed)
    if illegal:
        raise ValueError(f"{impl_id} attempted to write disallowed sections: {', '.join(sorted(illegal))}")


def _merge_patches(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in extra.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _apply_metrics_patch(state: RuntimeState, patch: dict[str, Any], duration_seconds: float) -> None:
    obs = patch.setdefault("observability", {})
    metrics = dict(obs.get("metrics") or state.observability.metrics)
    metrics["turn_count"] = state.execution.turn_count + 1
    metrics["total_latency_ms"] = int(metrics.get("total_latency_ms", 0)) + int(duration_seconds * 1000)
    obs["metrics"] = metrics


def _project_state_for_subgraph(
    state: RuntimeState,
    *,
    input_contract: PatternIOContractSpec,
    state_mode: str,
) -> RuntimeState:
    source = state.model_copy(deep=True) if state_mode == "isolated" else state.model_copy(deep=True)
    allowed = set(input_contract.readable_sections)
    if not allowed:
        return source
    data = source.model_dump(mode="python")
    for section in [
        "conversation",
        "context",
        "tools",
        "memory",
        "knowledge",
        "policy",
        "execution",
        "observability",
    ]:
        if section not in allowed:
            data[section] = RuntimeState().model_dump(mode="python")[section]
    return RuntimeState.model_validate(data)


def _merge_subgraph_output(
    parent: RuntimeState,
    child: RuntimeState,
    output_contract: PatternIOContractSpec,
) -> dict[str, Any]:
    allowed = set(output_contract.writable_sections)
    if not allowed:
        return {}
    patch: dict[str, Any] = {}
    child_data = child.model_dump(mode="json")
    for section in allowed:
        if section in child_data:
            patch[section] = child_data[section]
    return patch


def _validate_subgraph_exit_routes(*, node_id: str, pattern: GraphPatternSpec, child: GraphPatternSpec) -> None:
    expected = {f"subgraph.{route}" for route in child.exit_routes}
    actual = {edge.when for edge in pattern.edges if edge.from_ == node_id and edge.when.startswith("subgraph.")}
    missing = expected.difference(actual)
    if missing:
        raise ValueError(
            f"Parent pattern {pattern.pattern_id} is missing subgraph routes for {node_id}: {', '.join(sorted(missing))}"
        )
