from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from agent_factory.memory_system.config import should_enqueue_memory_write
from agent_factory.memory_system.reports import memory_event_payload
from agent_factory.memory_system.segment import build_conversation_segment
from agent_factory.memory_system.schema import MemoryWriteJob
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
        state, graph_messages = self._invoke_graph(compiled_app, state, thread_id=thread_id)
        self._enqueue_memory_write(compiled_app, state, thread_id=thread_id, messages=graph_messages)
        self._emit_run_completed(compiled_app, state)
        return state

    def stream(self, compiled_app: Any, state: RuntimeState, *, thread_id: str) -> Iterator[tuple[str, Any]]:
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
        final_raw: dict[str, Any] = {"runtime": state.model_dump(mode="python")}
        graph_messages: list[Any] = []
        for stream_mode, chunk in self._stream_graph(compiled_app, state, thread_id=thread_id):
            if stream_mode == "values" and isinstance(chunk, dict):
                final_raw = chunk
                graph_messages = list(chunk.get("messages") or [])
            yield stream_mode, chunk
        result = self._final_state_from_raw(final_raw)
        memory_event = self._enqueue_memory_write(compiled_app, result, thread_id=thread_id, messages=graph_messages)
        if memory_event is not None:
            yield "custom", memory_event
        self._emit_run_completed(compiled_app, result)
        yield "runtime_final", result

    def stream_resume(
        self,
        compiled_app: Any,
        state: RuntimeState,
        *,
        thread_id: str,
        resume_payload: dict[str, Any] | None = None,
    ) -> Iterator[tuple[str, Any]]:
        self._emit(compiled_app, state, "resume_started", message="Kernel resume started.")
        final_raw: dict[str, Any] = {"runtime": state.model_dump(mode="python")}
        graph_messages: list[Any] = []
        for stream_mode, chunk in self._stream_graph(
            compiled_app,
            state,
            thread_id=thread_id,
            stream_input=Command(resume=resume_payload or {}),
        ):
            if stream_mode == "values" and isinstance(chunk, dict):
                final_raw = chunk
                graph_messages = list(chunk.get("messages") or [])
            yield stream_mode, chunk
        result = self._final_state_from_raw(final_raw)
        memory_event = self._enqueue_memory_write(compiled_app, result, thread_id=thread_id, messages=graph_messages)
        if memory_event is not None:
            yield "custom", memory_event
        self._emit(compiled_app, result, "resume_completed", message="Kernel resumed from checkpoint.")
        self._emit_run_completed(compiled_app, result)
        yield "runtime_final", result

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
        state, graph_messages = self._invoke_graph(compiled_app, state, thread_id=thread_id)
        self._enqueue_memory_write(compiled_app, state, thread_id=thread_id, messages=graph_messages)
        self._emit(compiled_app, state, "resume_completed", message="Kernel resumed from checkpoint.")
        self._emit_run_completed(compiled_app, state)
        return state

    def _invoke_graph(self, compiled_app: Any, state: RuntimeState, *, thread_id: str) -> tuple[RuntimeState, list[Any]]:
        raw = compiled_app.graph_app.invoke(
            _graph_input(state),
            config=_graph_config(state, thread_id=thread_id),
        )
        return self._final_state_from_raw(raw), list(raw.get("messages") or [])

    def _stream_graph(
        self,
        compiled_app: Any,
        state: RuntimeState,
        *,
        thread_id: str,
        stream_input: Any | None = None,
    ) -> Iterator[tuple[str, Any]]:
        yield from compiled_app.graph_app.stream(
            _graph_input(state) if stream_input is None else stream_input,
            config=_graph_config(state, thread_id=thread_id),
            stream_mode=["updates", "values", "messages", "debug", "custom"],
        )

    def _final_state_from_raw(self, raw: dict[str, Any]) -> RuntimeState:
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

    def _enqueue_memory_write(
        self,
        compiled_app: Any,
        state: RuntimeState,
        *,
        thread_id: str,
        messages: list[Any],
    ) -> dict[str, Any] | None:
        if state.execution.finish_status != "completed" or state.execution.last_error:
            return None
        runtime = getattr(compiled_app.services, "memory_system", None)
        writer = getattr(runtime, "writer", None)
        if runtime is None or writer is None:
            return None
        if not getattr(runtime.config, "enabled", False) or not getattr(runtime.config, "write_enabled", False):
            return None
        turn_index = int(state.conversation.turn_index or 0)
        if not should_enqueue_memory_write(turn_index=turn_index, config=runtime.config):
            return None
        source = {
            "agent_id": state.run.agent_id,
            "session_id": state.run.session_id,
            "thread_id": thread_id,
            "run_id": state.run.run_id,
            "node_id": state.execution.current_node,
        }
        segment = build_conversation_segment(
            scope="agent",
            namespace=tuple(runtime.namespace),
            source=source,
            messages=messages or _messages_delta(state),
            end_turn=turn_index,
            max_turns=runtime.config.background.write_interval_turns,
        )
        if segment is None:
            return None
        job = MemoryWriteJob(
            scope="agent",
            namespace=tuple(runtime.namespace),
            source=source,
            segment=segment,
        )
        try:
            report = writer.enqueue(job)
            event_type = "memory_write_queued" if report.status == "queued" else "memory_write_queued_failed"
            payload = {"event_type": event_type, **memory_event_payload(report)}
            self._emit(
                compiled_app,
                state,
                event_type,
                message=report.status,
                payload=payload,
            )
            return {"type": "memory_event", "payload": payload}
        except Exception as exc:
            payload = {
                "event_type": "memory_write_queued_failed",
                "namespace": list(tuple(runtime.namespace)),
                "error": f"{type(exc).__name__}: {exc}",
            }
            self._emit(
                compiled_app,
                state,
                "memory_write_queued_failed",
                message=f"{type(exc).__name__}: {exc}",
                payload=payload,
            )
            return {"type": "memory_event", "payload": payload}


def _messages_delta(state: RuntimeState) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if state.conversation.current_user_input:
        messages.append({"role": "user", "content": state.conversation.current_user_input})
    assistant_text = state.conversation.final_answer or state.conversation.assistant_draft
    if assistant_text:
        messages.append({"role": "assistant", "content": assistant_text})
    return messages


def _graph_input(state: RuntimeState) -> dict[str, Any]:
    payload: dict[str, Any] = {"runtime": state.model_dump(mode="python")}
    user_input = (state.conversation.current_user_input or "").strip()
    if user_input:
        payload["messages"] = [HumanMessage(content=user_input)]
    return payload


def _graph_config(state: RuntimeState, *, thread_id: str) -> dict[str, Any]:
    recursion_limit = max(state.execution.max_turns + state.execution.max_subgraph_depth + 8, 25)
    return {
        "recursion_limit": recursion_limit,
        "configurable": {"thread_id": thread_id},
    }
