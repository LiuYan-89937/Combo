from __future__ import annotations

from typing import Any
from agent_factory.runtime_kernel.observability.schema import TraceEvent
from agent_factory.runtime_kernel.state import RuntimeState


class ExecutionController:
    def __init__(self) -> None:
        pass

    def run(self, compiled_app: Any, state: RuntimeState, *, thread_id: str) -> RuntimeState:
        self._emit(
            compiled_app,
            state,
            "run_started",
            message="Kernel run started.",
            payload={
                "agent_id": state.run.agent_id,
                "pattern_id": state.run.pattern_id,
                "pattern_version": state.run.pattern_version,
            },
        )
        state = self._invoke_graph(compiled_app, state, thread_id=thread_id)
        self._emit_run_completed(compiled_app, state)
        return state

    def resume(
        self,
        compiled_app: Any,
        state: RuntimeState,
        *,
        thread_id: str,
        resume_payload: dict[str, Any] | None = None,
    ) -> RuntimeState:
        state.execution.finished = False
        state.execution.finish_status = None
        state.execution.interrupted = False
        state.execution.resume_payload = resume_payload or {}
        state.policy.interrupted = False
        state.policy.interrupt_required = False
        state.policy.approval_required = False
        self._emit(compiled_app, state, "resume_started", message="Kernel resume started.")
        state = self._invoke_graph(compiled_app, state, thread_id=thread_id)
        self._emit(compiled_app, state, "resume_completed", message="Kernel resumed from checkpoint.")
        self._emit_run_completed(compiled_app, state)
        return state

    def _invoke_graph(self, compiled_app: Any, state: RuntimeState, *, thread_id: str) -> RuntimeState:
        recursion_limit = max(state.execution.max_turns + state.execution.max_subgraph_depth + 8, 25)
        raw = compiled_app.graph_app.invoke(
            {"runtime": state.model_dump(mode="python")},
            config={
                "recursion_limit": recursion_limit,
                "configurable": {"thread_id": thread_id},
            },
        )
        result = RuntimeState.model_validate(raw.get("runtime") or {})
        if not result.execution.finished:
            result.execution.finished = True
            result.execution.finish_status = result.execution.finish_status or "completed"
        return result

    def _emit_run_completed(self, compiled_app: Any, state: RuntimeState) -> None:
        self._emit(
            compiled_app,
            state,
            "run_completed",
            message=state.execution.finish_status or "completed",
            payload={
                "finish_status": state.execution.finish_status or "completed",
                "turn_count": state.execution.turn_count,
            },
        )

    def _emit(
        self,
        compiled_app: Any,
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
        compiled_app.services.observability_manager.emit(event)
        state.observability.events.append(event.model_dump(mode="json"))
