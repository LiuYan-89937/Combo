from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphInterrupt
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime

from combo.runtime_kernel.services import RuntimeServices
from combo.runtime_kernel.nodes.base import NodeExecutionContext, NodeImplementation
from combo.runtime_kernel.observability.node_events import emit_runtime_node_event
from combo.runtime_kernel.observability.schema import RuntimeObservationEvent
from combo.runtime_kernel.observability.tool_events import emit_runtime_tool_activity
from combo.runtime_kernel.observability.runtime_events import apply_node_metrics, emit_state_event
from combo.runtime_kernel.state.runtime_graph import (
    runtime_graph_patch,
    runtime_state_from_graph,
    split_graph_patch,
    validate_patch_sections,
)
from combo.runtime_kernel.state import RuntimeState, merge_state_patch
from combo.runtime_protocol.messages import (
    close_incomplete_tool_call_messages,
    incomplete_tool_call_ids,
)
from combo.tooling.execution_context import consume_runtime_inputs
from combo.tooling.execution_context import (
    RuntimeModelGenerationInterrupted,
    runtime_terminal_cancellation_requested,
)


NextNodeResolver = Callable[[str, str | None], tuple[str, str] | None]


def make_fixed_runner(
    *,
    node_id: str,
    implementation: NodeImplementation,
    services: RuntimeServices,
    success_nodes: frozenset[str],
    next_node: NextNodeResolver,
) -> Callable[..., dict[str, Any]]:
    """Build one node runner for the two immutable runtime graphs.

    Fixed runners deliberately have no Pattern binding, Package state manager,
    render manifest, bookmark, hook, retry wrapper, or arbitrary node wrapper.
    """

    def runner(
        raw_state: dict[str, Any],
        config: RunnableConfig = None,
        runtime: Runtime = None,
    ) -> dict[str, Any]:
        state = runtime_state_from_graph(raw_state)
        if state.execution.finished:
            return runtime_graph_patch(state)
        if _timed_out(state) and not _must_close_tool_protocol(implementation, raw_state):
            _finish(state, status="failed", error="Execution timed out before node execution.")
            return runtime_graph_patch(state)

        started = perf_counter()
        emit_state_event(
            services,
            state,
            "node_entered",
            node_id=node_id,
            payload={"impl": implementation.impl_id},
        )
        emitted_events: list[dict[str, Any]] = []

        def emit_event(payload: dict[str, Any]) -> None:
            event = RuntimeObservationEvent(
                trace_id=state.observability.trace_id,
                run_id=state.run.run_id,
                event_type=payload.get("event_type", "node_event"),
                node_id=node_id,
                payload=payload,
            )
            services.observability_manager.emit(event)
            emit_runtime_node_event(event)
            if event.persistence == "durable":
                emitted_events.append(event.model_dump(mode="json"))
            emit_runtime_tool_activity(payload, node_id=node_id)

        context = NodeExecutionContext(
            node_id=node_id,
            impl=implementation.impl_id,
            services=services,
            emit_event=emit_event,
            graph_messages=list(raw_state.get("messages") or []),
            graph_config=config,
            graph_runtime=runtime,
        )
        active_state = state
        messages_patch: list[Any] = []
        try:
            injected_messages = (
                _consume_injected_messages()
                if implementation.impl_id in {"cognitive.answer", "terminal.commit"}
                else []
            )
            if injected_messages:
                context.graph_messages.extend(injected_messages)
            if implementation.impl_id == "terminal.commit" and injected_messages:
                context_messages = None
                raw_patch = {
                    "execution": {
                        "current_node": context.node_id,
                        "route_decision": "runtime.steered",
                    }
                }
            else:
                active_state, context_messages = _prepare_context(
                    state=active_state,
                    context=context,
                    services=services,
                )
                raw_patch = implementation.execute(active_state, context)
            prepared_messages = (
                context_messages
                if context_messages is not None
                else list(context.graph_messages)
                if injected_messages
                else None
            )
            if prepared_messages is not None:
                messages_patch.extend([RemoveMessage(id=REMOVE_ALL_MESSAGES), *prepared_messages])

            node_messages, patch = split_graph_patch(raw_patch)
            route_decision = str((patch.get("execution") or {}).get("route_decision") or "")
            if implementation.impl_id == "cognitive.answer" and route_decision != "model.requests_tool":
                late_messages = _consume_injected_messages()
                if late_messages:
                    node_messages = [*node_messages, *late_messages]
                    conversation_patch = dict(patch.get("conversation") or {})
                    conversation_patch["final_answer"] = None
                    conversation_patch["clarification_question"] = None
                    patch["conversation"] = conversation_patch
                    execution_patch = dict(patch.get("execution") or {})
                    execution_patch["route_decision"] = "runtime.steered"
                    patch["execution"] = execution_patch
            messages_patch.extend(node_messages)
            validate_patch_sections(
                implementation.impl_id,
                patch,
                set(implementation.writable_sections),
            )
            updated = merge_state_patch(active_state, patch)
            if emitted_events:
                updated.observability.events = [*updated.observability.events, *emitted_events]
            updated.execution.turn_count += 1
            apply_node_metrics(updated, perf_counter() - started)
            _mark_activity(updated)
            _resolve_after_node(
                state=updated,
                node_id=node_id,
                success_nodes=success_nodes,
                next_node=next_node,
            )
            duration_ms = int((perf_counter() - started) * 1000)
            emit_state_event(
                services,
                updated,
                "node_completed",
                node_id=node_id,
                payload={"impl": implementation.impl_id, "duration_ms": duration_ms},
            )
            return runtime_graph_patch(updated, messages=messages_patch)
        except GraphInterrupt:
            raise
        except RuntimeModelGenerationInterrupted as exc:
            interrupted = active_state
            if runtime_terminal_cancellation_requested():
                _preserve_interrupted_conversation(interrupted, exc)
                interrupted.conversation.final_answer = None
                interrupted.conversation.clarification_question = None
                interrupted.execution.interrupted = True
                _finish(interrupted, status="cancelled", location="runtime.cancel")
                return runtime_graph_patch(
                    interrupted,
                    messages=[
                        *messages_patch,
                        *_interrupted_model_messages(exc, error_code="runtime_cancelled"),
                    ],
                )
            steered_messages = _consume_injected_messages()
            if not steered_messages:
                raise
            _preserve_interrupted_conversation(interrupted, exc)
            interrupted.conversation.final_answer = None
            interrupted.conversation.clarification_question = None
            interrupted.execution.route_decision = "runtime.steered"
            interrupted.execution.current_node = node_id
            interrupted.execution.finished = False
            interrupted.execution.interrupted = False
            partial_messages = _interrupted_model_messages(
                exc,
                error_code="runtime_steered",
            )
            _resolve_after_node(
                state=interrupted,
                node_id=node_id,
                success_nodes=success_nodes,
                next_node=next_node,
            )
            return runtime_graph_patch(
                interrupted,
                messages=[*messages_patch, *partial_messages, *steered_messages],
            )
        except Exception as exc:
            failed = active_state
            failed.execution.retry_count += 1
            _finish(failed, status="failed", error=str(exc), location=node_id)
            emit_state_event(
                services,
                failed,
                "node_failed",
                node_id=node_id,
                payload={"impl": implementation.impl_id, "error": str(exc)},
            )
            return runtime_graph_patch(failed)

    return runner


def _preserve_interrupted_conversation(
    state: RuntimeState,
    interruption: RuntimeModelGenerationInterrupted,
) -> None:
    partial_text = str(interruption.partial_text or "").strip()
    reasoning_content = str(interruption.reasoning_content or "").strip()
    state.conversation.assistant_draft = (
        partial_text or state.conversation.assistant_draft
    )
    state.conversation.reasoning_content = (
        reasoning_content or state.conversation.reasoning_content
    )


def _interrupted_model_messages(
    interruption: RuntimeModelGenerationInterrupted,
    *,
    error_code: str,
) -> list[Any]:
    partial_text = str(interruption.partial_text or "").strip()
    reasoning_content = str(interruption.reasoning_content or "").strip()
    partial_tool_calls = [dict(call) for call in interruption.partial_tool_calls]
    messages: list[Any] = []
    if partial_text or reasoning_content or partial_tool_calls:
        additional_kwargs = {"completion_reason": "user_interrupted"}
        if reasoning_content:
            additional_kwargs["reasoning_content"] = reasoning_content
        messages.append(
            AIMessage(
                content=partial_text,
                **({"tool_calls": partial_tool_calls} if partial_tool_calls else {}),
                additional_kwargs=additional_kwargs,
            )
        )
    return close_incomplete_tool_call_messages(
        messages,
        status="cancelled",
        error_code=error_code,
    )


def _consume_injected_messages() -> list[Any]:
    messages: list[Any] = []
    for injection in consume_runtime_inputs():
        role = str(getattr(injection, "role", "") or "")
        content = str(getattr(injection, "content", "") or "").strip()
        injection_id = str(getattr(injection, "injection_id", "") or "").strip()
        if not content or not injection_id:
            continue
        if role == "user":
            messages.append(HumanMessage(id=injection_id, content=content))
        elif role == "system":
            messages.append(
                SystemMessage(
                    id=injection_id,
                    content=content,
                    additional_kwargs={"kind": "runtime_notification"},
                )
            )
    return messages


def _prepare_context(
    *,
    state: RuntimeState,
    context: NodeExecutionContext,
    services: RuntimeServices,
) -> tuple[RuntimeState, list[Any] | None]:
    if not context.impl.startswith("cognitive."):
        return state, None
    context_system = services.context_system
    result = context_system.prepare_before_model_call(
        state=state,
        node_id=context.node_id,
        impl=context.impl,
        messages=list(context.graph_messages),
        services=services,
        resources=services.runtime_context_resources.current(),
        enable_dynamic_evidence=(
            state.run.strategy != "plan_and_execute"
            or context.node_id == "executor"
        ),
    )
    context.graph_messages = list(result.messages)
    return result.state, list(result.messages) if result.messages_changed else None


def _resolve_after_node(
    *,
    state: RuntimeState,
    node_id: str,
    success_nodes: frozenset[str],
    next_node: NextNodeResolver,
) -> None:
    if state.policy.interrupted or state.execution.interrupted:
        state.execution.interrupted = True
        state.execution.finished = True
        state.execution.finish_status = "interrupted"
        state.execution.current_node = node_id
        state.execution.interrupt_payload = {
            "node_id": node_id,
            "interrupt_type": state.policy.interrupt_type,
            "approval_required": state.policy.approval_required,
            "reason": state.policy.block_reason or state.policy.refusal_reason,
        }
        return
    if state.policy.blocked:
        state.execution.finish_status = state.execution.finish_status or "blocked"
    if node_id in success_nodes:
        state.execution.current_node = node_id
        state.execution.finished = True
        state.execution.finish_status = state.execution.finish_status or "completed"
        return
    if state.execution.finished:
        state.execution.current_node = node_id
        state.execution.finish_status = state.execution.finish_status or (
            "blocked" if state.policy.blocked else "completed"
        )
        return
    resolved = next_node(node_id, state.execution.route_decision)
    if resolved is None:
        _finish(state, status="failed", error=f"No next node resolved from {node_id}.")
        state.execution.current_node = node_id
        return
    condition, target = resolved
    state.execution.route_decision = condition
    state.execution.current_node = target


def _finish(
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


def _timed_out(state: RuntimeState) -> bool:
    if state.execution.timeout_seconds <= 0:
        return False
    try:
        activity_at = datetime.fromisoformat(
            state.execution.last_activity_at or state.run.started_at
        )
    except ValueError:
        return False
    if activity_at.tzinfo is None:
        activity_at = activity_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - activity_at).total_seconds() > state.execution.timeout_seconds


def _mark_activity(state: RuntimeState) -> None:
    state.execution.last_activity_at = datetime.now(timezone.utc).isoformat()


def _must_close_tool_protocol(implementation: NodeImplementation, raw_state: dict[str, Any]) -> bool:
    return implementation.impl_id == "operational.tool_call" and bool(
        incomplete_tool_call_ids(raw_state.get("messages") or [])
    )
