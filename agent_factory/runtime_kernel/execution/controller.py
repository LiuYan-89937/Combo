from __future__ import annotations

from typing import Any
from agent_factory.memory_system.schema import MemoryWriteJob
from agent_factory.memory_system.reports import memory_event_payload
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
        self._enqueue_memory_write(compiled_app, state, thread_id=thread_id)
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
        self._enqueue_memory_write(compiled_app, state, thread_id=thread_id)
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

    def _enqueue_memory_write(self, compiled_app: Any, state: RuntimeState, *, thread_id: str) -> None:
        if state.execution.finish_status in {"failed", "blocked"} or state.execution.last_error:
            return
        runtime = getattr(compiled_app.services, "memory_system", None)
        writer = getattr(runtime, "writer", None)
        if runtime is None or writer is None:
            return
        messages_delta = _messages_delta(state)
        if not messages_delta:
            return
        job = MemoryWriteJob(
            scope="agent",
            namespace=tuple(runtime.namespace),
            source={
                "agent_id": state.run.agent_id,
                "session_id": state.run.session_id,
                "thread_id": thread_id,
                "run_id": state.run.run_id,
                "node_id": state.execution.current_node,
            },
            message_range={"turn_index": state.conversation.turn_index},
            messages_delta=messages_delta,
        )
        try:
            report = writer.enqueue(job)
            event_type = "memory_write_queued" if report.status == "queued" else "memory_write_queued_failed"
            self._emit(
                compiled_app,
                state,
                event_type,
                message=report.status,
                payload=memory_event_payload(report),
            )
        except Exception as exc:
            self._emit(
                compiled_app,
                state,
                "memory_write_queued_failed",
                message=f"{type(exc).__name__}: {exc}",
                payload={"namespace": list(tuple(runtime.namespace)), "error": f"{type(exc).__name__}: {exc}"},
            )


def _messages_delta(state: RuntimeState) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if state.conversation.current_user_input:
        messages.append({"role": "user", "content": state.conversation.current_user_input})
    assistant_text = state.conversation.final_answer or state.conversation.assistant_draft
    if assistant_text:
        messages.append({"role": "assistant", "content": assistant_text})
    return messages
