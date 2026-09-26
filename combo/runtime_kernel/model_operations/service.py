from __future__ import annotations

from collections.abc import Callable, Iterable
from contextvars import copy_context
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import RLock
from threading import Thread
from typing import Any, Literal
from uuid import uuid4

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from combo.context_system.events import emit_context_event
from combo.context_system.token_counter import (
    context_window_payload,
    provider_token_budget_payload,
    token_count_from_usage_metadata,
)
from combo.context_system.token_estimation import (
    estimate_messages_tokens,
    estimate_text_tokens,
)
from combo.models.content import content_to_text, strip_internal_snapshot_blocks
from combo.models.chat_model import ChatModelSettings
from combo.models.message_layout import system_messages_first
from combo.models.reasoning import reasoning_content_from_message
from combo.models.usage import usage_metadata_with_fallback
from combo.runtime_kernel.model_inputs import (
    build_runtime_model_input,
)
from combo.runtime_kernel.model_operations.tool_calls import bind_tools, tool_calls_from_response
from combo.runtime_kernel.state import RuntimeState
from combo.model_invocation.structured_output import (
    StructuredOutputExecution,
    StructuredOutputInvocation,
    execute_structured_output_invocation,
    prepare_structured_output_invocation,
)
from combo.runtime_kernel.types import ModelInvocationResult
from combo.runtime_protocol import ModelSelectionSnapshot
from combo.tooling.description_context import contextualize_tool_descriptions
from combo.tooling.model_visibility import tools_visible_to_model
from combo.runtime_protocol.interruption import RuntimeModelGenerationInterrupted
from combo.tooling.execution_context import (
    begin_runtime_model_generation,
    consume_runtime_inputs,
    execute_runtime_model_invocation,
    register_runtime_model_cancellation,
    runtime_model_generation_is_current,
)

ModelRole = Literal["main", "task", "compression"]


@dataclass(frozen=True, slots=True)
class RuntimeModelHandle:
    runtime_instance_id: str
    snapshot: ModelSelectionSnapshot
    model: Any
    settings: ChatModelSettings
    compression_model: Any
    compression_settings: ChatModelSettings


class RuntimeModelHandleRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._handles: dict[str, RuntimeModelHandle] = {}

    def register(self, handle: RuntimeModelHandle) -> None:
        runtime_instance_id = str(handle.runtime_instance_id or "").strip()
        if not runtime_instance_id:
            raise ValueError("runtime model handle requires runtime_instance_id")
        with self._lock:
            existing = self._handles.get(runtime_instance_id)
            if existing is not None and existing != handle:
                raise RuntimeError("runtime instance already has a different model handle")
            self._handles[runtime_instance_id] = handle

    def require(self, runtime_instance_id: str) -> RuntimeModelHandle:
        key = str(runtime_instance_id or "").strip()
        if not key:
            raise RuntimeError("runtime model resolution requires runtime_instance_id")
        with self._lock:
            handle = self._handles.get(key)
        if handle is None:
            raise RuntimeError(f"runtime model handle is not registered: {key}")
        return handle

    def release(self, runtime_instance_id: str) -> RuntimeModelHandle | None:
        key = str(runtime_instance_id or "").strip()
        if not key:
            raise ValueError("runtime_instance_id must not be empty")
        with self._lock:
            return self._handles.pop(key, None)


class ModelOperationService:
    """Invoke the model handle frozen for the current runtime instance."""

    model_role = "runtime"

    def __init__(
        self,
        registry: RuntimeModelHandleRegistry,
        *,
        workspace_path_resolver: Callable[[str], Path],
    ) -> None:
        self._registry = registry
        self._workspace_path_resolver = workspace_path_resolver

    @staticmethod
    def _system_prompt(*, state: RuntimeState) -> str:
        system_prompt = state.runtime_config.system_prompt.strip()
        if not system_prompt:
            raise RuntimeError("fixed runtime model operations require runtime_config.system_prompt")
        return system_prompt

    def _resolve_model(
        self,
        role: ModelRole | None = None,
        *,
        state: RuntimeState,
    ) -> tuple[Any, dict[str, Any]]:
        if role is not None:
            raise RuntimeError("fixed runtime model operations do not accept role selection")
        handle = self._registry.require(state.run.runtime_instance_id)
        settings_metadata = handle.settings.metadata()
        return handle.model, {
            **settings_metadata,
            "model_operation": handle.snapshot.operation,
            "model_role": handle.snapshot.operation,
            "model_profile_id": handle.snapshot.profile_id,
            "model_profile_revision": handle.snapshot.profile_revision,
            "credential_resource_id": handle.snapshot.credential_resource_id,
            "credential_revision": handle.snapshot.credential_revision,
            "provider": handle.snapshot.provider,
            "model": handle.snapshot.model_name,
            "model_source": "runtime_policy_snapshot",
        }

    def context_limits_for_role(
        self,
        role: str | None = None,
        *,
        state: RuntimeState,
    ) -> dict[str, int | None]:
        if role not in {None, "runtime", "main_turn", "temporary_turn"}:
            raise RuntimeError("fixed runtime context limits do not accept legacy model roles")
        _model, metadata = self._resolve_model(state=state)
        return {
            "max_input_tokens": metadata.get("max_input_tokens"),
            "compression_trigger_tokens": metadata.get("compression_trigger_tokens"),
        }

    def operation_for_state(self, state: RuntimeState) -> str:
        _model, metadata = self._resolve_model(state=state)
        return str(metadata["model_operation"])

    def compression_model_for_state(self, state: RuntimeState) -> tuple[Any, int | None, dict[str, Any]]:
        handle = self._registry.require(state.run.runtime_instance_id)
        return (
            handle.compression_model,
            handle.compression_settings.max_output_tokens,
            handle.compression_settings.metadata(),
        )

    def text(
        self,
        *,
        state: RuntimeState,
        messages: list[Any] | None = None,
        emit_event=None,
        model_role: ModelRole | None = None,
    ) -> ModelInvocationResult:
        return self.tool_bound_chat(
            state=state,
            messages=messages,
            tools=[],
            emit_event=emit_event,
            model_role=model_role,
        )

    def tool_bound_chat(
        self,
        *,
        state: RuntimeState,
        messages: list[Any] | None = None,
        tools: list[BaseTool] | None = None,
        emit_event=None,
        services: Any | None = None,
        node_id: str | None = None,
        model_role: ModelRole | None = None,
    ) -> ModelInvocationResult:
        model, metadata = self._resolve_model(model_role, state=state)
        effective_model_role = str(metadata.get("model_role") or model_role or self.model_role)
        image_input_enabled = bool(metadata.get("multimodal"))
        tool_list = sorted(
            contextualize_tool_descriptions(
                tools_visible_to_model(tools or [], image_input_enabled=image_input_enabled)
            ),
            key=lambda tool: str(getattr(tool, "name", "") or ""),
        )
        envelope = build_runtime_model_input(
            state=state,
            system_prompt=self._system_prompt(state=state),
            messages=messages or [],
            tools=tool_list,
            workspace_path_resolver=self._workspace_path_resolver,
            node_id=node_id,
            image_input_enabled=image_input_enabled,
        )
        stream_id = uuid4().hex
        _emit(
            emit_event,
            "model_call_started",
            {"operation": "tool_bound_chat", "model_role": effective_model_role, "stream_id": stream_id},
        )
        try:
            response = _invoke_tool_bound_chat(
                model=bind_tools(model, tool_list),
                messages=envelope.messages,
                emit_event=emit_event,
                stream_id=stream_id,
            )
        except RuntimeModelGenerationInterrupted as exc:
            _emit(
                emit_event,
                "model_generation_interrupted",
                {
                    "operation": "tool_bound_chat",
                    "stream_id": stream_id,
                    "content": exc.partial_text,
                    "reasoning_content": exc.reasoning_content,
                    "completion_reason": "user_interrupted",
                },
            )
            raise RuntimeModelGenerationInterrupted(
                str(exc),
                partial_text=exc.partial_text,
                reasoning_content=exc.reasoning_content,
                partial_tool_calls=exc.partial_tool_calls,
                stream_id=stream_id,
                input_injections=consume_runtime_inputs(),
            ) from exc
        except Exception as exc:
            _emit(emit_event, "model_call_failed", {"operation": "tool_bound_chat", "error": str(exc)})
            raise
        if isinstance(response, BaseMessage):
            response = response.model_copy(update={"id": stream_id})
        text = strip_internal_snapshot_blocks(content_to_text(getattr(response, "content", response))).strip()
        reasoning_content = reasoning_content_from_message(response)
        tool_calls = tool_calls_from_response(response)
        _emit_model_message_completed(
            emit_event,
            stream_id=stream_id,
            response=response,
            tool_call_count=len(tool_calls),
        )
        usage_metadata = getattr(response, "usage_metadata", None) or {}
        usage_observation = _model_usage_payload(
            node_id=node_id,
            model_metadata=metadata,
            usage_metadata=usage_metadata,
            input_diagnostics=envelope.diagnostics(),
            fallback_input_tokens=estimate_messages_tokens(envelope.messages),
            fallback_output_tokens=estimate_text_tokens(
                "\n".join(part for part in (reasoning_content, text) if part)
            ),
        )
        _record_model_token_budget(
            state=state,
            node_id=node_id,
            model_role=effective_model_role,
            usage_metadata=usage_metadata,
            usage_observation=usage_observation,
            retained_message_tokens_after_call=estimate_messages_tokens([
                *envelope.messages,
                response,
            ]),
        )
        _emit(
            emit_event,
            "model_call_completed",
            {
                "operation": "tool_bound_chat",
                "tool_call_count": len(tool_calls),
                "usage_metadata": usage_metadata,
                "model_input": envelope.diagnostics(),
            },
        )
        _emit(emit_event, "model_usage_completed", usage_observation)
        _emit_model_usage_context_window(
            state=state,
            services=services,
            node_id=node_id,
            model_role=effective_model_role,
            usage_observation=usage_observation,
        )
        return ModelInvocationResult(
            ai_message=response if isinstance(response, BaseMessage) else None,
            assistant_draft=text,
            final_answer=None if tool_calls else text,
            tool_calls=tool_calls,
            metadata={
                **metadata,
                "tool_count": len(tool_list),
                "usage_metadata": usage_metadata,
                "usage_observation": usage_observation,
                "retained_message_tokens_after_call": estimate_messages_tokens([
                    *envelope.messages,
                    response,
                ]),
                "provider_input_tokens": token_count_from_usage_metadata(usage_metadata),
                "reasoning_content": reasoning_content,
                **envelope.diagnostics(),
            },
        )

    def structured_json(
        self,
        *,
        output_model: type[BaseModel],
        state: RuntimeState,
        messages: list[Any] | None = None,
        prebuilt_messages: list[Any] | None = None,
        structured_method: str | None = None,
        config_tags: list[str] | None = None,
        max_attempts: int = 3,
        emit_event=None,
        operation_metadata: dict[str, Any] | None = None,
        services: Any | None = None,
        node_id: str | None = None,
        model_role: ModelRole | None = None,
    ) -> BaseModel:
        model, metadata = self._resolve_model(model_role, state=state)
        effective_model_role = str(metadata.get("model_role") or model_role or self.model_role)
        envelope = None
        if prebuilt_messages is not None:
            request_messages = list(prebuilt_messages)
        else:
            envelope = build_runtime_model_input(
                state=state,
                system_prompt=self._system_prompt(state=state),
                messages=messages or [],
                tools=[],
                workspace_path_resolver=self._workspace_path_resolver,
                node_id=node_id,
                image_input_enabled=bool(metadata.get("multimodal")),
            )
            request_messages = envelope.messages
        invocation = prepare_structured_output_invocation(
            model=model,
            output_model=output_model,
            messages=request_messages,
            model_metadata=metadata,
            requested_method=structured_method,
            config_tags=config_tags,
        )
        effective_structured_method = invocation.method
        operation_context = {
            **metadata,
            "structured_output_method": effective_structured_method,
            **(operation_metadata or {}),
        }
        input_diagnostics = _structured_input_diagnostics(
            envelope=envelope,
            request_messages=list(invocation.messages),
            tool_count=0,
        )
        current_attempt = 0

        def before_attempt(
            attempt: int,
            attempts: int,
            attempt_messages: tuple[Any, ...],
        ) -> None:
            nonlocal current_attempt, input_diagnostics
            current_attempt = attempt
            input_diagnostics = _structured_input_diagnostics(
                envelope=envelope,
                request_messages=list(attempt_messages),
                tool_count=0,
            )
            _emit(
                emit_event,
                "model_call_started",
                {"operation": "structured_json", "attempt": attempt, "max_attempts": attempts, **operation_context},
            )

        def invoke_model(
            structured_model: Any,
            attempt_messages: tuple[Any, ...],
            _attempt: int,
        ) -> Any:
            generation_revision = begin_runtime_model_generation()
            return execute_runtime_model_invocation(
                lambda: structured_model.invoke(list(attempt_messages)),
                revision=generation_revision,
            )

        def on_attempt_failure(exc: Exception, attempt: int, attempts: int) -> None:
            _emit(
                emit_event,
                "model_call_failed",
                {
                    "operation": "structured_json",
                    "attempt": attempt,
                    "max_attempts": attempts,
                    "error": str(exc),
                    **operation_context,
                },
            )

        try:
            execution = execute_structured_output_invocation(
                invocation,
                max_attempts=max_attempts,
                invoke_model=invoke_model,
                before_attempt=before_attempt,
                on_attempt_failure=on_attempt_failure,
            )
        except RuntimeModelGenerationInterrupted:
            _emit(
                emit_event,
                "model_generation_interrupted",
                {
                    "operation": "structured_json",
                    "attempt": current_attempt,
                },
            )
            raise

        parsed = execution.value
        result = execution.raw
        request_messages = list(execution.messages)
        usage_metadata = getattr(result, "usage_metadata", None) or {}
        usage_observation = _model_usage_payload(
            node_id=node_id,
            model_metadata=metadata,
            usage_metadata=usage_metadata,
            input_diagnostics=input_diagnostics,
            fallback_input_tokens=estimate_messages_tokens(request_messages),
            fallback_output_tokens=estimate_text_tokens(parsed.model_dump_json()),
        )
        _record_model_token_budget(
            state=state,
            node_id=node_id,
            model_role=effective_model_role,
            usage_metadata=usage_metadata,
            usage_observation=usage_observation,
            retained_message_tokens_after_call=estimate_messages_tokens(request_messages),
        )
        _emit(
            emit_event,
            "model_call_completed",
            {
                "operation": "structured_json",
                "attempt": execution.attempt_count,
                "usage_metadata": usage_metadata,
                "model_input": input_diagnostics,
            },
        )
        _emit(emit_event, "model_usage_completed", usage_observation)
        _emit_model_usage_context_window(
            state=state,
            services=services,
            node_id=node_id,
            model_role=effective_model_role,
            usage_observation=usage_observation,
        )
        return parsed


def _emit(emit_event, event_type: str, payload: dict[str, Any]) -> None:
    if emit_event is None:
        return
    emit_event({"event_type": event_type, **payload})


def _record_model_token_budget(
    *,
    state: RuntimeState,
    node_id: str | None,
    model_role: str,
    usage_metadata: Any,
    usage_observation: dict[str, Any],
    retained_message_tokens_after_call: int | None = None,
) -> None:
    if node_id is None:
        return
    payload = provider_token_budget_payload(
        usage_metadata=usage_metadata,
        node_id=node_id,
        model_role=model_role,
        provider_input_tokens=usage_observation.get("input_tokens"),
        fallback_output_tokens=usage_observation.get("output_tokens"),
        usage_source=str(usage_observation.get("usage_source") or "local_estimation"),
        retained_message_tokens_after_call=retained_message_tokens_after_call,
    )
    if not payload:
        return
    state.context.token_budget = {
        **state.context.token_budget,
        **payload,
    }


def _invoke_tool_bound_chat(
    *,
    model: Any,
    messages: list[Any],
    emit_event,
    stream_id: str,
) -> Any:
    messages = system_messages_first(messages)
    generation_revision = begin_runtime_model_generation()
    stream = getattr(model, "stream", None)
    if not callable(stream):
        return execute_runtime_model_invocation(
            lambda: model.invoke(messages),
            revision=generation_revision,
        )
    chunks: list[Any] = []
    reasoning_parts: list[str] = []
    cancelled = False
    stream_iterator = stream(messages)
    if not isinstance(stream_iterator, Iterable):
        raise TypeError("model stream must return an iterable")
    stream_events: Queue[tuple[str, Any]] = Queue()
    context = copy_context()

    def produce() -> None:
        try:
            for chunk in stream_iterator:
                if cancelled:
                    break
                stream_events.put(("chunk", chunk))
        except BaseException as exc:
            if not cancelled:
                stream_events.put(("error", exc))
        finally:
            stream_events.put(("completed", None))

    def cancel_stream() -> None:
        nonlocal cancelled
        cancelled = True
        close = getattr(stream_iterator, "close", None)
        if callable(close):
            try:
                close()
            except (RuntimeError, ValueError):
                pass

    unregister = register_runtime_model_cancellation(cancel_stream)
    producer = Thread(
        target=lambda: context.run(produce),
        name="combo-model-stream",
        daemon=True,
    )
    producer.start()
    try:
        while True:
            if cancelled or not runtime_model_generation_is_current(generation_revision):
                raise RuntimeModelGenerationInterrupted("Model generation was superseded.")
            try:
                event_type, value = stream_events.get(timeout=0.05)
            except Empty:
                continue
            if event_type == "completed":
                break
            if event_type == "error":
                raise value
            chunk = value
            chunks.append(chunk)
            reasoning_delta = reasoning_content_from_message(chunk)
            if reasoning_delta:
                reasoning_parts.append(reasoning_delta)
                _emit(
                    emit_event,
                    "model_reasoning_delta",
                    {
                        "stream_id": stream_id,
                        "delta": reasoning_delta,
                        "content_mode": "delta",
                    },
                )
            delta = strip_internal_snapshot_blocks(content_to_text(getattr(chunk, "content", chunk)))
            if delta:
                _emit(
                    emit_event,
                    "model_stream_delta",
                    {
                        "stream_id": stream_id,
                        "delta": delta,
                        "content_mode": "delta",
                    },
                )
    except RuntimeModelGenerationInterrupted as exc:
        partial_text = ""
        partial_tool_calls: tuple[dict[str, Any], ...] = ()
        if chunks:
            partial_response = _merge_stream_chunks(chunks)
            partial_text = strip_internal_snapshot_blocks(
                content_to_text(getattr(partial_response, "content", ""))
            )
            partial_tool_calls = tuple(tool_calls_from_response(partial_response))
        raise RuntimeModelGenerationInterrupted(
            str(exc),
            partial_text=partial_text,
            reasoning_content="".join(reasoning_parts),
            partial_tool_calls=partial_tool_calls,
        ) from exc
    except NotImplementedError:
        if chunks:
            raise
        return execute_runtime_model_invocation(
            lambda: model.invoke(messages),
            revision=generation_revision,
        )
    finally:
        unregister()
    if cancelled or not runtime_model_generation_is_current(generation_revision):
        raise RuntimeModelGenerationInterrupted("Model generation was superseded.")
    if not chunks:
        return execute_runtime_model_invocation(
            lambda: model.invoke(messages),
            revision=generation_revision,
        )
    response = _merge_stream_chunks(chunks)
    if reasoning_parts and not reasoning_content_from_message(response):
        _attach_reasoning_content(response, "".join(reasoning_parts))
    return response


def _merge_stream_chunks(chunks: list[Any]) -> Any:
    merged = chunks[0]
    for chunk in chunks[1:]:
        merged = merged + chunk
    return merged


def _attach_reasoning_content(response: Any, reasoning_content: str) -> None:
    additional_kwargs = getattr(response, "additional_kwargs", None)
    if not isinstance(additional_kwargs, dict):
        raise TypeError("streamed model response has no additional_kwargs mapping")
    additional_kwargs["reasoning_content"] = reasoning_content


def _emit_model_message_completed(
    emit_event,
    *,
    stream_id: str,
    response: Any,
    tool_call_count: int,
) -> None:
    content = strip_internal_snapshot_blocks(content_to_text(getattr(response, "content", response))).strip()
    reasoning_content = reasoning_content_from_message(response)
    if reasoning_content:
        _emit(
            emit_event,
            "model_reasoning_completed",
            {
                "stream_id": stream_id,
                "content": reasoning_content,
                "content_mode": "snapshot",
                "completion_reason": "model_completed",
            },
        )
    _emit(
        emit_event,
        "model_message_completed",
        {
            "stream_id": stream_id,
            "content": content,
            "content_mode": "snapshot",
            "completion_reason": "model_completed",
            "tool_call_count": tool_call_count,
            "presentation": "activity" if tool_call_count else "answer",
            "discard": bool(tool_call_count),
            **({"reasoning_content": reasoning_content} if reasoning_content else {}),
        },
    )


def _model_usage_payload(
    *,
    node_id: str | None,
    model_metadata: dict[str, Any],
    usage_metadata: dict[str, Any],
    input_diagnostics: dict[str, Any],
    fallback_input_tokens: int,
    fallback_output_tokens: int,
) -> dict[str, Any]:
    normalized_usage, usage_source = usage_metadata_with_fallback(
        usage_metadata,
        fallback_input_tokens=fallback_input_tokens,
        fallback_output_tokens=fallback_output_tokens,
    )
    input_tokens = normalized_usage.input_tokens
    output_tokens = normalized_usage.output_tokens
    return {
        "version": "runtime_model_usage_observation.v1",
        "node_id": str(node_id or "model"),
        "model_operation": model_metadata.get("model_operation"),
        "model_profile_id": model_metadata.get("model_profile_id"),
        "model_profile_revision": model_metadata.get("model_profile_revision"),
        "provider": model_metadata.get("provider"),
        "model_name": model_metadata.get("model"),
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "total_tokens": int(normalized_usage.total_tokens or 0),
        "reasoning_tokens": int(normalized_usage.reasoning_tokens or 0),
        "cache_read_tokens": int(normalized_usage.cache_hit_tokens or 0),
        "cache_write_tokens": int(normalized_usage.cache_write_tokens or 0),
        "usage_source": usage_source,
        "model_input": input_diagnostics,
    }


def _structured_input_diagnostics(
    *,
    envelope: Any | None,
    request_messages: list[Any],
    tool_count: int,
) -> dict[str, Any]:
    if envelope is not None:
        diagnostics = dict(envelope.diagnostics())
    else:
        diagnostics = {
            "stable_prefix_digest": "",
            "dynamic_evidence_digest": "",
            "tool_surface_digest": "",
            "stable_system_chars": 0,
            "dynamic_evidence_chars": 0,
            "history_message_count": _base_message_count(request_messages),
            "tool_count": tool_count,
        }
    diagnostics["request_message_count"] = _base_message_count(request_messages)
    diagnostics["request_message_chars"] = _request_message_chars(request_messages)
    return diagnostics


def _base_message_count(messages: list[Any]) -> int:
    return sum(1 for message in messages if isinstance(message, BaseMessage))


def _request_message_chars(messages: list[Any]) -> int:
    return sum(len(_message_content_text(message)) for message in messages)


def _message_content_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    return str(content)


def _emit_model_usage_context_window(
    *,
    state: RuntimeState,
    services: Any | None,
    node_id: str | None,
    model_role: str,
    usage_observation: dict[str, Any],
) -> None:
    if services is None or node_id is None:
        return
    token_count = int(usage_observation.get("total_tokens") or 0)
    limits = services.context_system.model_context_limits(
        services=services,
        state=state,
        model_role=model_role,
    )
    payload = context_window_payload(
        node_id=node_id,
        token_count=token_count,
        token_count_method=str(usage_observation.get("usage_source") or "local_estimation"),
        compression_threshold_tokens=limits.compression_trigger_tokens,
        context_window_tokens=limits.context_window_tokens,
        model_role=model_role,
        source=f"model_operation.{usage_observation.get('usage_source') or 'local_estimation'}",
    )
    state.context.token_budget = {
        **state.context.token_budget,
        **payload,
    }
    emit_context_event(
        services=services,
        state=state,
        event_type="context_window_updated",
        node_id=node_id,
        payload=payload,
    )
