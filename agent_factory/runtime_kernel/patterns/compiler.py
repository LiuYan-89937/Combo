from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime

from agent_factory.runtime_kernel.bindings import BindingSet, RuntimeServices
from agent_factory.runtime_kernel.errors import RuntimeKernelError
from agent_factory.runtime_kernel.execution.routing import resolve_route
from agent_factory.runtime_kernel.kernel.models import CompiledKernelApp
from agent_factory.runtime_kernel.nodes.base import NodeExecutionContext
from agent_factory.runtime_kernel.nodes.registry import NodeRegistry
from agent_factory.runtime_kernel.observability.schema import TraceEvent
from agent_factory.runtime_kernel.observability.tool_events import emit_runtime_tool_activity
from agent_factory.runtime_kernel.patterns.registry import PatternRegistry
from agent_factory.runtime_kernel.patterns.schema import (
    GraphPatternSpec,
    PatternIOContractSpec,
    PatternNodeSpec,
    PatternNodeWrapperSpec,
)
from agent_factory.runtime_kernel.patterns.validator import PatternValidator
from agent_factory.runtime_kernel.state import RuntimeGraphState, RuntimeState, merge_state_patch
from agent_factory.runtime_kernel.wrappers import DEFAULT_NODE_WRAPPER_REGISTRY, NodeWrapperRegistry
from agent_factory.runtime_kernel.wrappers.system_registry import DEFAULT_SYSTEM_WRAPPER_REGISTRY
from agent_factory.runtime_protocol.messages import incomplete_tool_call_ids
from agent_factory.runtime_render import NodeRenderSpec, RenderManifest, default_node_render_spec, validate_render_manifest


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
        render_manifest: RenderManifest,
        system_wrapper_ids: list[str] | tuple[str, ...],
    ) -> CompiledKernelApp:
        pattern = self.pattern_registry.get(pattern_id)
        self.validator.validate(pattern, known_patterns=set(self.pattern_registry.list_pattern_ids()))
        validate_render_manifest(render_manifest, {node.id for node in pattern.nodes})
        system_wrappers = DEFAULT_SYSTEM_WRAPPER_REGISTRY.resolve_many(system_wrapper_ids)
        node_runners = {
            node.id: self._make_node_runner(
                node=node,
                pattern=pattern,
                bindings=bindings,
                services=services,
                render_manifest=render_manifest,
                system_wrapper_ids=system_wrapper_ids,
                system_wrappers=system_wrappers,
            )
            for node in pattern.nodes
        }
        graph = StateGraph(RuntimeGraphState)
        for node_id, runner in node_runners.items():
            graph.add_node(node_id, runner)
        graph.set_conditional_entry_point(
            _make_entry_router(pattern),
            {node.id: node.id for node in pattern.nodes},
        )
        outgoing = {}
        for edge in pattern.edges:
            outgoing.setdefault(edge.from_, {})[edge.when] = edge.to
        for node in pattern.nodes:
            if node.id in pattern.termination.success_nodes or node.id in pattern.termination.failure_nodes:
                graph.add_edge(node.id, END)
                continue
            mapping = dict(outgoing.get(node.id, {}))
            mapping["__end__"] = END
            graph.add_conditional_edges(node.id, _make_route_router(mapping), mapping)
        graph_app = graph.compile(checkpointer=services.checkpointer, store=services.memory_store)
        return CompiledKernelApp(
            pattern_spec=pattern,
            graph_app=graph_app,
            services=services,
            bindings=bindings,
            metadata={
                "compiled_pattern_id": pattern.pattern_id,
            },
            node_runners=node_runners,
        )

    def _make_node_runner(
        self,
        *,
        node: PatternNodeSpec,
        pattern: GraphPatternSpec,
        bindings: BindingSet,
        services: RuntimeServices,
        render_manifest: RenderManifest,
        system_wrapper_ids: list[str] | tuple[str, ...],
        system_wrappers: list[Any],
    ):
        node_bindings = [
            item.model_dump(mode="json")
            for item in bindings.node_bindings
            if item.target.node_id == node.id and item.target.impl == node.impl
        ]
        all_node_bindings = [item.model_dump(mode="json") for item in bindings.node_bindings]
        hook_bindings = [item.model_dump(mode="json") for item in bindings.hooks if item.enabled]
        for wrapper in node.wrappers:
            DEFAULT_NODE_WRAPPER_REGISTRY.validate_spec(wrapper)
        if node.type == "sub_graph":
            child_pattern = self.pattern_registry.get(node.pattern_ref or "")
            child = self.compile(
                pattern_id=node.pattern_ref or "",
                bindings=bindings,
                services=services,
                render_manifest=_default_render_manifest_for_pattern(child_pattern),
                system_wrapper_ids=system_wrapper_ids,
            )
            _validate_subgraph_exit_routes(node_id=node.id, pattern=pattern, child=child.pattern_spec)
            execute = _make_subgraph_executor(
                node_id=node.id,
                compiled=child,
                services=services,
                input_contract=child.pattern_spec.input_contract,
                output_contract=child.pattern_spec.output_contract,
                state_mode=child.pattern_spec.state_mode,
            )
            return _make_wrapped_runner(
                node=node,
                pattern=pattern,
                bindings=node_bindings,
                all_bindings=all_node_bindings,
                hook_bindings=hook_bindings,
                services=services,
                execute=execute,
                validate_sections=False,
                span_type="subgraph_execution",
                node_wrappers=node.wrappers,
                node_wrapper_registry=DEFAULT_NODE_WRAPPER_REGISTRY,
                render_spec=render_manifest.nodes.get(node.id),
                system_wrappers=system_wrappers,
            )
        impl = self.node_registry.get(node.impl)

        def execute(state: RuntimeState, context: NodeExecutionContext) -> dict[str, Any]:
            return impl.execute(state, context)

        return _make_wrapped_runner(
            node=node,
            pattern=pattern,
            bindings=node_bindings,
            all_bindings=all_node_bindings,
            hook_bindings=hook_bindings,
            services=services,
            execute=execute,
            validate_sections=True,
            span_type="node_execution",
            node_wrappers=node.wrappers,
            node_wrapper_registry=DEFAULT_NODE_WRAPPER_REGISTRY,
            render_spec=render_manifest.nodes.get(node.id),
            system_wrappers=system_wrappers,
        )


def _make_wrapped_runner(
    *,
    node: PatternNodeSpec,
    pattern: GraphPatternSpec,
    bindings: list[dict[str, Any]],
    all_bindings: list[dict[str, Any]],
    hook_bindings: list[dict[str, Any]],
    services: RuntimeServices,
    execute,
    validate_sections: bool,
    span_type: str,
    node_wrappers: list[PatternNodeWrapperSpec],
    node_wrapper_registry: NodeWrapperRegistry,
    render_spec: NodeRenderSpec | None,
    system_wrappers: list[Any],
):
    node_wrappers = sorted(node_wrappers, key=lambda item: int(item.order))

    def runner(
        raw_state: dict[str, Any],
        config: RunnableConfig = None,
        runtime: Runtime = None,
    ) -> dict[str, Any]:
        state = _runtime_state_from_graph(raw_state)
        if state.execution.finished:
            return _runtime_graph_patch(state)
        if _timed_out(state) and not _must_repair_tool_protocol(node, raw_state):
            _finish_state(state, status="failed", error="Execution timed out before node execution.")
            return _runtime_graph_patch(state)
        started = perf_counter()
        span = services.observability_manager.start_span(
            trace_id=state.observability.trace_id,
            run_id=state.run.run_id,
            span_type=span_type,
            name=node.id,
            metadata={"impl": node.impl, "node_id": node.id},
        )
        _push_span(state, span.span_id, span_type, node.id)
        _emit_state_event(services, state, "node_entered", node_id=node.id, payload={"impl": node.impl})
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
            emit_runtime_tool_activity(payload, node_id=node.id)

        context = NodeExecutionContext(
            node_id=node.id,
            impl=node.impl,
            bindings=bindings,
            all_bindings=all_bindings,
            hook_bindings=hook_bindings,
            services=services,
            emit_event=emit_event,
            render_spec=render_spec,
            graph_messages=list(raw_state.get("messages") or []),
            graph_config=config,
            graph_runtime=runtime,
        )
        active_state = state
        try:
            active_state, _system_start_patch = _run_system_before(
                stage="node_start",
                wrappers=system_wrappers,
                state=active_state,
                context=context,
            )
            working_state, _pre_patch = _run_pre_hooks(active_state, context)
            active_state = working_state
            before_state, _before_patch = _run_node_wrappers(
                phase="before",
                state=working_state,
                context=context,
                wrapper_specs=node_wrappers,
                wrapper_registry=node_wrapper_registry,
                services=services,
            )
            active_state = before_state
            memory_state, _memory_patch = _run_system_before(
                stage="pre_execute",
                wrappers=system_wrappers,
                state=before_state,
                context=context,
            )
            active_state = memory_state
            raw_patch = _execute_with_retries(memory_state, context, execute)
            messages_patch, patch = _split_graph_patch(raw_patch)
            if validate_sections:
                _validate_patch_sections(node.impl, patch)
            updated = merge_state_patch(memory_state, patch)
            active_state = updated
            after_state, _after_patch = _run_node_wrappers(
                phase="after",
                state=updated,
                context=context,
                wrapper_specs=node_wrappers,
                wrapper_registry=node_wrapper_registry,
                services=services,
                node_result=patch,
            )
            active_state = after_state
            updated = after_state
            post_patch = _run_post_hooks(updated, context)
            if post_patch:
                updated = merge_state_patch(updated, post_patch)
            if emitted_events:
                updated.observability.events = [*updated.observability.events, *emitted_events]
            updated.execution.turn_count += 1
            _apply_node_metrics(updated, perf_counter() - started)
            _resolve_after_node(pattern=pattern, node=node, state=updated, services=services)
            duration_ms = int((perf_counter() - started) * 1000)
            _run_system_after(
                wrappers=system_wrappers,
                state=updated,
                context=context,
                node_result=patch,
                duration_ms=duration_ms,
            )
            _emit_state_event(
                services,
                updated,
                "node_completed",
                node_id=node.id,
                payload={"impl": node.impl, "duration_ms": duration_ms},
            )
            services.observability_manager.finish_span(
                span.span_id,
                trace_id=updated.observability.trace_id,
                run_id=updated.run.run_id,
                status="completed",
                metadata={"node_id": node.id, "duration_ms": duration_ms},
            )
            _pop_span(updated, span.span_id)
            return _runtime_graph_patch(updated, messages=messages_patch)
        except GraphInterrupt:
            raise
        except Exception as exc:
            failed = active_state
            try:
                failed, on_error_patch = _run_node_wrappers(
                    phase="on_error",
                    state=failed,
                    context=context,
                    wrapper_specs=node_wrappers,
                    wrapper_registry=node_wrapper_registry,
                    services=services,
                    error=exc,
                )
                if on_error_patch:
                    failed = merge_state_patch(failed, on_error_patch)
            except Exception as wrapper_exc:
                exc = wrapper_exc
            failed.execution.retry_count += 1
            location = failed.execution.last_error_location or node.id
            _finish_state(failed, status="failed", error=str(exc), location=location)
            _run_system_on_error(wrappers=system_wrappers, state=failed, context=context, error=exc)
            _emit_state_event(
                services,
                failed,
                "node_failed",
                node_id=node.id,
                payload={"impl": node.impl, "error": str(exc)},
            )
            services.observability_manager.finish_span(
                span.span_id,
                trace_id=failed.observability.trace_id,
                run_id=failed.run.run_id,
                status="failed",
                metadata={"node_id": node.id, "error": str(exc)},
            )
            _pop_span(failed, span.span_id)
            return _runtime_graph_patch(failed)

    return runner


def _make_entry_router(pattern: GraphPatternSpec):
    node_ids = {node.id for node in pattern.nodes}

    def route(raw_state: dict[str, Any]) -> str:
        state = _runtime_state_from_graph(raw_state)
        if state.execution.current_node in node_ids and not state.execution.finished:
            return state.execution.current_node or pattern.entry_node
        return pattern.entry_node

    return route


def _make_route_router(mapping: dict[str, str]):
    allowed = set(mapping)

    def route(raw_state: dict[str, Any]) -> str:
        state = _runtime_state_from_graph(raw_state)
        if state.execution.finished or state.execution.interrupted or state.policy.interrupted:
            return "__end__"
        decision = state.execution.route_decision
        if decision in allowed:
            return decision or "__end__"
        return "__end__"

    return route


def _runtime_state_from_graph(raw_state: dict[str, Any]) -> RuntimeState:
    return RuntimeState.model_validate(raw_state.get("runtime") or {})


def _runtime_graph_patch(state: RuntimeState, *, messages: list[Any] | None = None) -> dict[str, Any]:
    patch: dict[str, Any] = {"runtime": state.model_dump(mode="json")}
    if messages:
        patch["messages"] = messages
    return patch


def _split_graph_patch(patch: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
    messages = list(patch.get("messages") or [])
    runtime_patch = {key: value for key, value in patch.items() if key != "messages"}
    return messages, runtime_patch


def _default_render_manifest_for_pattern(pattern: GraphPatternSpec) -> RenderManifest:
    return RenderManifest(
        graph_id=pattern.pattern_id,
        nodes={
            node.id: default_node_render_spec(
                node_id=node.id,
                node_type=node.type,
                impl=node.impl,
            )
            for node in pattern.nodes
        },
    )


def _execute_with_retries(
    state: RuntimeState,
    context: NodeExecutionContext,
    execute,
) -> dict[str, Any]:
    attempts = 0
    while True:
        try:
            return execute(state, context)
        except GraphInterrupt:
            raise
        except Exception:
            attempts += 1
            state.execution.retry_count += 1
            if attempts > state.execution.max_retries:
                raise


def _run_system_before(
    *,
    stage: str,
    wrappers: list[Any],
    state: RuntimeState,
    context: NodeExecutionContext,
) -> tuple[RuntimeState, dict[str, Any]]:
    working = state
    cumulative_patch: dict[str, Any] = {}
    for wrapper in wrappers:
        if getattr(wrapper, "before_stage", None) != stage:
            continue
        result = wrapper.before(state=working, context=context)
        if result is None:
            continue
        if not isinstance(result, tuple) or len(result) != 2:
            raise RuntimeKernelError(f"system wrapper {wrapper.wrapper_id} returned invalid before result")
        next_state, patch = result
        working = next_state
        cumulative_patch.update(patch or {})
    return working, cumulative_patch


def _run_system_after(
    *,
    wrappers: list[Any],
    state: RuntimeState,
    context: NodeExecutionContext,
    node_result: dict[str, Any],
    duration_ms: int,
) -> None:
    for wrapper in wrappers:
        after = getattr(wrapper, "after", None)
        if after is None:
            continue
        after(state=state, context=context, node_result=node_result, duration_ms=duration_ms)


def _run_system_on_error(
    *,
    wrappers: list[Any],
    state: RuntimeState,
    context: NodeExecutionContext,
    error: Exception,
) -> None:
    for wrapper in wrappers:
        on_error = getattr(wrapper, "on_error", None)
        if on_error is None:
            continue
        on_error(state=state, context=context, error=error)


def _run_node_wrappers(
    *,
    phase: str,
    state: RuntimeState,
    context: NodeExecutionContext,
    wrapper_specs: list[PatternNodeWrapperSpec],
    wrapper_registry: NodeWrapperRegistry,
    services: RuntimeServices,
    node_result: dict[str, Any] | None = None,
    error: Exception | None = None,
) -> tuple[RuntimeState, dict[str, Any]]:
    working = state
    cumulative_patch: dict[str, Any] = {}
    for spec in [item for item in wrapper_specs if item.phase == phase]:
        wrapper = wrapper_registry.create(spec)
        location = f"{context.node_id}.{phase}.{spec.id}"
        _emit_state_event(
            services,
            working,
            "wrapper_started",
            node_id=context.node_id,
            payload={"wrapper_id": spec.id, "phase": phase, "location": location},
        )
        try:
            if phase == "before":
                patch = wrapper.before(state=working, context=context, config=dict(spec.config))
            elif phase == "after":
                patch = wrapper.after(
                    state=working,
                    context=context,
                    config=dict(spec.config),
                    node_result=node_result or {},
                )
            elif phase == "on_error":
                patch = wrapper.on_error(
                    state=working,
                    context=context,
                    config=dict(spec.config),
                    error=error or RuntimeError("Unknown node error."),
                )
            else:
                raise RuntimeKernelError(f"Unsupported node wrapper phase: {phase}")
            patch = patch or {}
            _validate_wrapper_patch_sections(spec.id, wrapper.writable_sections, patch)
            if patch:
                working = merge_state_patch(working, patch)
                cumulative_patch = _merge_patches(cumulative_patch, patch)
            _emit_state_event(
                services,
                working,
                "wrapper_completed",
                node_id=context.node_id,
                payload={"wrapper_id": spec.id, "phase": phase, "location": location},
            )
        except Exception as exc:
            working.execution.last_error_location = location
            _emit_state_event(
                services,
                working,
                "wrapper_failed",
                node_id=context.node_id,
                payload={"wrapper_id": spec.id, "phase": phase, "location": location, "error": str(exc)},
            )
            raise
    return working, cumulative_patch


def _resolve_after_node(
    *,
    pattern: GraphPatternSpec,
    node: PatternNodeSpec,
    state: RuntimeState,
    services: RuntimeServices,
) -> None:
    if _timed_out(state) and state.execution.route_decision != "model.requests_tool":
        _finish_state(state, status="failed", error="Execution timed out.")
        return
    if state.policy.interrupted or state.execution.interrupted:
        state.execution.interrupted = True
        state.execution.finished = True
        state.execution.finish_status = "interrupted"
        state.execution.current_node = node.id
        state.execution.interrupt_payload = _interrupt_payload(state, node.id)
        return
    if state.policy.blocked:
        state.execution.finish_status = state.execution.finish_status or "blocked"
    if node.id in pattern.termination.success_nodes:
        state.execution.current_node = node.id
        state.execution.finished = True
        state.execution.finish_status = state.execution.finish_status or "completed"
        return
    if node.id in pattern.termination.failure_nodes:
        _finish_state(state, status="failed", error=state.execution.last_error)
        state.execution.current_node = node.id
        return
    if state.execution.finished:
        state.execution.current_node = node.id
        state.execution.finish_status = state.execution.finish_status or (
            "blocked" if state.policy.blocked else "completed"
        )
        return
    route = resolve_route(pattern, current_node=node.id, state=state)
    if route.next_node is None or route.condition is None:
        _finish_state(state, status="failed", error=f"No next node resolved from {node.id}.")
        state.execution.current_node = node.id
        return
    state.execution.route_decision = route.condition
    state.execution.current_node = route.next_node
    _emit_state_event(
        services,
        state,
        "route_selected",
        node_id=node.id,
        payload={"condition": route.condition, "next_node": route.next_node},
    )


def _finish_state(
    state: RuntimeState,
    *,
    status: str,
    error: str | None = None,
    location: str | None = None,
) -> None:
    state.execution.finished = True
    state.execution.finish_status = status
    state.execution.route_decision = "execution.finished"
    if error:
        state.execution.last_error = error
    if location:
        state.execution.last_error_location = location


def _interrupt_payload(state: RuntimeState, node_id: str) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "interrupt_type": state.policy.interrupt_type,
        "approval_required": state.policy.approval_required,
        "reason": state.policy.block_reason or state.policy.refusal_reason,
    }


def _timed_out(state: RuntimeState) -> bool:
    if state.execution.timeout_seconds <= 0:
        return False
    try:
        started_at = datetime.fromisoformat(state.run.started_at)
    except ValueError:
        return False
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    elapsed = datetime.now(timezone.utc) - started_at
    return elapsed.total_seconds() > state.execution.timeout_seconds


def _must_repair_tool_protocol(node: PatternNodeSpec, raw_state: dict[str, Any]) -> bool:
    return node.impl == "operational.tool_call" and bool(incomplete_tool_call_ids(raw_state.get("messages") or []))


def _emit_state_event(
    services: RuntimeServices,
    state: RuntimeState,
    event_type: str,
    *,
    node_id: str | None = None,
    message: str | None = None,
    payload: dict[str, Any] | None = None,
    subgraph_id: str | None = None,
) -> None:
    event = TraceEvent(
        trace_id=state.observability.trace_id,
        run_id=state.run.run_id,
        event_type=event_type,
        node_id=node_id,
        subgraph_id=subgraph_id,
        message=message,
        payload=payload or {},
    )
    services.observability_manager.emit(event)
    state.observability.events.append(event.model_dump(mode="json"))


def _push_span(state: RuntimeState, span_id: str, span_type: str, name: str) -> None:
    state.observability.span_stack.append({"span_id": span_id, "span_type": span_type, "name": name})


def _pop_span(state: RuntimeState, span_id: str) -> None:
    state.observability.span_stack = [
        item for item in state.observability.span_stack if item.get("span_id") != span_id
    ]


def _apply_node_metrics(state: RuntimeState, duration_seconds: float) -> None:
    duration_ms = int(duration_seconds * 1000)
    metrics = dict(state.observability.metrics)
    metrics["turn_count"] = state.execution.turn_count
    metrics["total_latency_ms"] = int(metrics.get("total_latency_ms", 0)) + duration_ms
    metrics["max_node_latency_ms"] = max(int(metrics.get("max_node_latency_ms", 0)), duration_ms)
    state.observability.metrics = metrics



def _make_subgraph_executor(
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

    def runner(parent_state: RuntimeState, _context: NodeExecutionContext) -> dict[str, Any]:
        if parent_state.execution.subgraph_depth >= parent_state.execution.max_subgraph_depth:
            return {
                "execution": {
                    "current_node": node_id,
                    "finished": True,
                    "finish_status": "failed",
                    "route_decision": "execution.finished",
                    "last_error": "Execution exceeded max_subgraph_depth.",
                }
            }
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
        child_input.execution.current_node = None
        child_input.execution.current_subgraph = compiled.pattern_spec.pattern_id
        child_input.execution.subgraph_depth = parent_state.execution.subgraph_depth + 1
        child_input.execution.finished = False
        child_input.execution.finish_status = None
        child_state = controller.run(compiled, child_input, thread_id=child_input.run.session_id)
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
                "subgraph_depth": parent_state.execution.subgraph_depth,
            },
            "observability": {
                "events": [
                    *parent_state.observability.events,
                    entered.model_dump(mode="json"),
                    *child_state.observability.events,
                    exited.model_dump(mode="json"),
                ],
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
        tool_binding = _first_binding_payload(context.bindings, "tool_access")
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
            tool_binding = _first_binding_payload(context.bindings, "tool_access")
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
        elif point == "on_resume" and state.execution.resume_payload:
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


def _validate_wrapper_patch_sections(
    wrapper_id: str,
    writable_sections: set[str],
    patch: dict[str, Any],
) -> None:
    patch_sections = set(patch)
    illegal = patch_sections.difference(writable_sections)
    if illegal:
        raise ValueError(
            f"{wrapper_id} attempted to write disallowed sections: {', '.join(sorted(illegal))}"
        )


def _merge_patches(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in extra.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


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
