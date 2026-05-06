from __future__ import annotations

from typing import Any
from uuid import uuid4

from agent_factory.runtime_kernel.checkpoint.serializer import CheckpointSerializer
from agent_factory.runtime_kernel.observability.schema import TraceEvent
from agent_factory.runtime_kernel.state import RuntimeState


class ExecutionController:
    def __init__(self, *, checkpoint_serializer: CheckpointSerializer | None = None) -> None:
        self.checkpoint_serializer = checkpoint_serializer or CheckpointSerializer()

    def run(self, compiled_app: Any, state: RuntimeState) -> RuntimeState:
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
        state = self._invoke_graph(compiled_app, state)
        state = self._finalize_interrupt_if_needed(compiled_app, state)
        self._emit_run_completed(compiled_app, state)
        return state

    def resume(
        self,
        compiled_app: Any,
        state: RuntimeState,
        *,
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
        state = self._invoke_graph(compiled_app, state)
        state = self._finalize_interrupt_if_needed(compiled_app, state)
        self._emit(compiled_app, state, "resume_completed", message="Kernel resumed from checkpoint.")
        self._emit_run_completed(compiled_app, state)
        return state

    def _invoke_graph(self, compiled_app: Any, state: RuntimeState) -> RuntimeState:
        recursion_limit = max(state.execution.max_turns + state.execution.max_subgraph_depth + 8, 25)
        raw = compiled_app.graph_app.invoke(
            state.model_dump(mode="python"),
            config={"recursion_limit": recursion_limit},
        )
        result = RuntimeState.model_validate(raw)
        if not result.execution.finished:
            result.execution.finished = True
            result.execution.finish_status = result.execution.finish_status or "completed"
        return result

    def _finalize_interrupt_if_needed(self, compiled_app: Any, state: RuntimeState) -> RuntimeState:
        if not (state.execution.interrupted or state.policy.interrupted):
            return state
        state.execution.interrupted = True
        state.execution.finished = True
        state.execution.finish_status = "interrupted"
        state.execution.resume_token = state.execution.resume_token or uuid4().hex
        self._emit(
            compiled_app,
            state,
            "checkpoint_operation",
            node_id=state.execution.current_node,
            payload={"reason": "interrupt"},
        )
        record = self.checkpoint_serializer.to_record(state=state, reason="interrupt")
        path = compiled_app.services.checkpoint_manager.save(record)
        state.observability.debug_refs.append(
            {
                "kind": "checkpoint",
                "path": str(path),
                "checkpoint_id": record.checkpoint_id,
                "summary": "Interrupt checkpoint",
            }
        )
        self._emit(
            compiled_app,
            state,
            "interrupt_triggered",
            node_id=state.execution.current_node,
            payload=state.execution.interrupt_payload,
        )
        return state

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
