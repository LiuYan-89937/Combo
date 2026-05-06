from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.checkpoint.serializer import CheckpointSerializer
from agent_factory.runtime_kernel.errors import RuntimeKernelError
from agent_factory.runtime_kernel.execution.routing import resolve_next_node
from agent_factory.runtime_kernel.observability.schema import TraceEvent
from agent_factory.runtime_kernel.state import RuntimeState, merge_state_patch


class ExecutionController:
    def __init__(self, *, checkpoint_serializer: CheckpointSerializer | None = None) -> None:
        self.checkpoint_serializer = checkpoint_serializer or CheckpointSerializer()

    def run(self, compiled_app: Any, state: RuntimeState) -> RuntimeState:
        self._emit(compiled_app, state, "run_started", message="Kernel run started.")
        if state.execution.current_node is None:
            state.execution.current_node = compiled_app.pattern_spec.entry_node
        while not state.execution.finished:
            if state.execution.turn_count >= state.execution.max_turns:
                state.execution.finished = True
                state.execution.finish_status = "failed"
                break
            node_id = state.execution.current_node
            if not node_id:
                raise RuntimeKernelError("ExecutionController requires current_node.")
            runner = compiled_app.node_runners[node_id]
            self._emit(compiled_app, state, "node_entered", node_id=node_id)
            patch = runner(state)
            state = merge_state_patch(state, patch)
            state.execution.turn_count += 1
            self._emit(compiled_app, state, "node_completed", node_id=node_id)
            if state.policy.interrupted or state.execution.interrupted:
                self._emit(
                    compiled_app,
                    state,
                    "checkpoint_operation",
                    node_id=node_id,
                    payload={"reason": "interrupt"},
                )
                record = self.checkpoint_serializer.to_record(state=state, reason="interrupt")
                path = compiled_app.services.checkpoint_manager.save(record)
                state.observability.debug_refs.append(
                    {"kind": "checkpoint", "path": str(path), "checkpoint_id": record.checkpoint_id}
                )
                state.execution.finished = True
                state.execution.finish_status = "interrupted"
                self._emit(compiled_app, state, "interrupt_triggered", node_id=node_id)
                break
            if state.execution.finished:
                break
            next_node = resolve_next_node(compiled_app.pattern_spec, current_node=node_id, state=state)
            if next_node is None:
                if node_id in compiled_app.pattern_spec.termination.success_nodes:
                    state.execution.finished = True
                    state.execution.finish_status = state.execution.finish_status or "completed"
                    break
                raise RuntimeKernelError(f"No next node resolved from {node_id}.")
            state.execution.current_node = next_node
            self._emit(compiled_app, state, "route_selected", node_id=node_id, payload={"next_node": next_node})
        self._emit(compiled_app, state, "run_completed", message=state.execution.finish_status or "completed")
        return state

    def resume(self, compiled_app: Any, state: RuntimeState) -> RuntimeState:
        state.execution.interrupted = False
        state.policy.interrupted = False
        self._emit(compiled_app, state, "interrupt_operation", message="Resuming from checkpoint.")
        self._emit(compiled_app, state, "resume_completed", message="Kernel resumed from checkpoint.")
        return self.run(compiled_app, state)

    def _emit(
        self,
        compiled_app: Any,
        state: RuntimeState,
        event_type: str,
        *,
        node_id: str | None = None,
        message: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        event = TraceEvent(
            trace_id=state.observability.trace_id,
            run_id=state.run.run_id,
            event_type=event_type,
            node_id=node_id,
            message=message,
            payload=payload or {},
        )
        compiled_app.services.observability_manager.emit(event)
        state.observability.events.append(event.model_dump(mode="json"))
