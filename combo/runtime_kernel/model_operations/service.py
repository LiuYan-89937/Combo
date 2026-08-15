from __future__ import annotations

import json
from contextvars import copy_context
from dataclasses import dataclass
from queue import Empty, Queue
from threading import RLock
from threading import Thread
from typing import Any, Literal
from uuid import uuid4

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from combo.context_system.events import emit_context_event
from combo.context_system.token_counter import (
    context_window_payload,
    model_context_limits,
    provider_token_budget_payload,
    token_count_from_usage_metadata,
)
from combo.context_system.token_estimation import (
    estimate_messages_tokens,
    estimate_text_tokens,
)
from combo.models.content import content_to_text, strip_internal_snapshot_blocks
from combo.models.message_layout import system_messages_first
from combo.models.reasoning import reasoning_content_from_message
from combo.models.usage import usage_metadata_with_fallback
from combo.runtime_kernel.model_inputs import (
    build_runtime_model_input,
)
from combo.runtime_kernel.model_operations.tool_calls import bind_tools, tool_calls_from_response
from combo.runtime_kernel.types import ModelInvocationResult
from combo.runtime_protocol import ModelSelectionSnapshot
from combo.tooling.description_context import contextualize_tool_descriptions
from combo.tooling.model_visibility import tools_visible_to_model
from combo.tooling.execution_context import (
    RuntimeModelGenerationInterrupted,
    begin_runtime_model_generation,
    execute_runtime_model_invocation,
    register_runtime_model_cancellation,
    runtime_model_generation_is_current,
)

_DEFAULT_STRUCTURED_METHOD = "json_mode"
ModelRole = Literal["main", "task", "compression"]


@dataclass(frozen=True, slots=True)
class RuntimeModelHandle:
    runtime_instance_id: str
    snapshot: ModelSelectionSnapshot
    model: Any
    settings: Any


@dataclass(frozen=True, slots=True)
class StructuredOutputInvocation:
    model: Any
    messages: tuple[Any, ...]
    method: str


def prepare_structured_output_invocation(
    *,
    model: Any,
    output_model: type[BaseModel],
    messages: list[Any],
    model_metadata: dict[str, Any],
    requested_method: str | None = None,
    config_tags: list[str] | None = None,
) -> StructuredOutputInvocation:
    method = _effective_structured_method(
        requested=requested_method,
        model_metadata=model_metadata,
    )
    request_messages = _structured_request_messages(
        messages=list(messages),
        output_model=output_model,
        output_json_schema=_schema_payload(output_model),
        structured_method=method,
    )
    return StructuredOutputInvocation(
        model=_structured_model(
            model=model,
            output_model=output_model,
            method=method,
            config_tags=_structured_config_tags(config_tags),
        ),
        messages=tuple(system_messages_first(request_messages)),
        method=method,
    )


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


class ModelInvocationOperations:
    """Kernel-level model invocation shapes shared by runtime services.

    The service is intentionally limited to model invocation shapes. It does
    not decide graph routes, plan tools, approve tools, or execute tools.
    """

    def text(
        self,
        *,
        state: Any,
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
        state: Any,
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
            raise
        except Exception as exc:
            _emit(emit_event, "model_call_failed", {"operation": "tool_bound_chat", "error": str(exc)})
            raise
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
                "provider_input_tokens": token_count_from_usage_metadata(usage_metadata),
                "reasoning_content": reasoning_content,
                **envelope.diagnostics(),
            },
        )

    def structured_json(
        self,
        *,
        output_model: type[BaseModel],
        state: Any,
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
                node_id=node_id,
                image_input_enabled=bool(metadata.get("multimodal")),
            )
            request_messages = envelope.messages
        attempts = max(1, int(max_attempts))
        last_error: Exception | None = None
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
        request_messages = list(invocation.messages)
        input_diagnostics = _structured_input_diagnostics(
            envelope=envelope,
            request_messages=request_messages,
            tool_count=0,
        )
        for attempt in range(1, attempts + 1):
            _emit(
                emit_event,
                "model_call_started",
                {"operation": "structured_json", "attempt": attempt, "max_attempts": attempts, **operation_context},
            )
            try:
                generation_revision = begin_runtime_model_generation()
                result = execute_runtime_model_invocation(
                    lambda: invocation.model.invoke(request_messages),
                    revision=generation_revision,
                )
                if isinstance(result, output_model):
                    parsed = result
                else:
                    parsed = output_model.model_validate(result)
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
                )
                _emit(
                    emit_event,
                    "model_call_completed",
                    {
                        "operation": "structured_json",
                        "attempt": attempt,
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
            except RuntimeModelGenerationInterrupted:
                _emit(
                    emit_event,
                    "model_generation_interrupted",
                    {
                        "operation": "structured_json",
                        "attempt": attempt,
                    },
                )
                raise
            except Exception as exc:
                last_error = exc
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
                if attempt < attempts:
                    request_messages = [
                        *request_messages,
                        HumanMessage(
                            content=_structured_retry_instruction(
                                output_model=output_model,
                                error=exc,
                                attempt=attempt,
                                max_attempts=attempts,
                                output_json_schema=schema_payload,
                            )
                        ),
                    ]
                    input_diagnostics = _structured_input_diagnostics(
                        envelope=envelope,
                        request_messages=request_messages,
                        tool_count=0,
                    )
        raise RuntimeError(f"structured model operation failed after {attempts} attempts: {last_error}")


class ModelOperationService(ModelInvocationOperations):
    """Resolve exactly one model handle frozen for the current runtime instance."""

    model_role = "runtime"
    authoritative_runtime_model = True

    def __init__(self, registry: RuntimeModelHandleRegistry) -> None:
        self._registry = registry

    @staticmethod
    def _system_prompt(*, state: Any) -> str:
        runtime_config = getattr(state, "runtime_config", None)
        system_prompt = str(getattr(runtime_config, "system_prompt", "") or "").strip()
        if not system_prompt:
            raise RuntimeError("fixed runtime model operations require runtime_config.system_prompt")
        return system_prompt

    def _resolve_model(
        self,
        role: ModelRole | None = None,
        *,
        state: Any | None = None,
    ) -> tuple[Any, dict[str, Any]]:
        if role is not None:
            raise RuntimeError("fixed runtime model operations do not accept role selection")
        runtime_instance_id = str(
            getattr(getattr(state, "run", None), "runtime_instance_id", "") or ""
        ).strip()
        handle = self._registry.require(runtime_instance_id)
        settings_metadata = handle.settings.metadata() if hasattr(handle.settings, "metadata") else {}
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
        state: Any | None = None,
    ) -> dict[str, int | None]:
        if role not in {None, "runtime", "main_turn", "temporary_turn"}:
            raise RuntimeError("fixed runtime context limits do not accept legacy model roles")
        _model, metadata = self._resolve_model(state=state)
        return {
            "max_input_tokens": metadata.get("max_input_tokens"),
            "compression_trigger_tokens": metadata.get("compression_trigger_tokens"),
        }


def _emit(emit_event, event_type: str, payload: dict[str, Any]) -> None:
    if emit_event is None:
        return
    emit_event({"event_type": event_type, **payload})


def _record_model_token_budget(
    *,
    state: Any,
    node_id: str | None,
    model_role: str,
    usage_metadata: Any,
    usage_observation: dict[str, Any],
) -> None:
    if state is None or node_id is None:
        return
    context = getattr(state, "context", None)
    if context is None or not hasattr(context, "token_budget"):
        return
    payload = provider_token_budget_payload(
        usage_metadata=usage_metadata,
        node_id=node_id,
        model_role=model_role,
        provider_input_tokens=usage_observation.get("input_tokens"),
        fallback_output_tokens=usage_observation.get("output_tokens"),
        usage_source=str(usage_observation.get("usage_source") or "local_estimation"),
    )
    if not payload:
        return
    context.token_budget = {
        **dict(getattr(context, "token_budget", {}) or {}),
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
    except (AttributeError, NotImplementedError):
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
        try:
            merged = merged + chunk
        except TypeError:
            merged = chunk
    return merged


def _attach_reasoning_content(response: Any, reasoning_content: str) -> None:
    additional_kwargs = getattr(response, "additional_kwargs", None)
    if isinstance(additional_kwargs, dict):
        additional_kwargs["reasoning_content"] = reasoning_content
        return
    try:
        response.additional_kwargs = {"reasoning_content": reasoning_content}
    except Exception:
        return


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


def _structured_model(
    *,
    model: Any,
    output_model: type[BaseModel],
    method: str | None,
    config_tags: list[str] | None,
) -> Any:
    structured = (
        model.with_structured_output(output_model, method=method)
        if method
        else model.with_structured_output(output_model)
    )
    if config_tags and hasattr(structured, "with_config"):
        structured = structured.with_config(tags=list(config_tags))
    return structured


def _structured_config_tags(config_tags: list[str] | None) -> list[str]:
    tags = ["nostream"]
    for tag in config_tags or []:
        item = str(tag).strip()
        if item and item not in tags:
            tags.append(item)
    return tags


def _effective_structured_method(*, requested: str | None, model_metadata: dict[str, Any]) -> str:
    method = str(requested or model_metadata.get("structured_output_method") or "").strip()
    if not method:
        method = str(
            model_metadata.get("default_structured_output_method")
            or _DEFAULT_STRUCTURED_METHOD
        ).strip()
    supported = {
        str(item)
        for item in (model_metadata.get("structured_output_methods") or [])
        if str(item).strip()
    }
    if supported and method not in supported:
        provider = str(model_metadata.get("provider") or "model")
        supported_text = ", ".join(sorted(supported))
        raise RuntimeError(
            f"structured output method {method!r} is not supported by {provider}; "
            f"supported methods: {supported_text}"
        )
    return method or _DEFAULT_STRUCTURED_METHOD


def _structured_request_messages(
    *,
    messages: list[Any],
    output_model: type[BaseModel],
    output_json_schema: str,
    structured_method: str,
) -> list[Any]:
    if structured_method != "json_mode":
        return messages
    return [
        *messages,
        HumanMessage(
            content=_structured_json_mode_instruction(
                output_model=output_model,
                output_json_schema=output_json_schema,
            )
        ),
    ]


def _schema_payload(output_model: type[BaseModel]) -> str:
    try:
        return json.dumps(output_model.model_json_schema(), ensure_ascii=False, sort_keys=True)
    except Exception:
        return output_model.__name__


def _structured_json_mode_instruction(
    *,
    output_model: type[BaseModel],
    output_json_schema: str,
) -> str:
    return (
        "Return JSON only. Do not include markdown fences, comments, or explanatory text.\n"
        "The JSON response must validate against the schema below.\n"
        f"Schema name: {output_model.__name__}\n"
        f"Output JSON schema:\n{output_json_schema}"
    )


def _structured_retry_instruction(
    *,
    output_model: type[BaseModel],
    error: Exception,
    attempt: int,
    max_attempts: int,
    output_json_schema: Any,
) -> str:
    return (
        "The previous structured JSON output failed schema validation.\n"
        "Regenerate the full response as JSON only. Do not explain the error.\n"
        "You must obey every JSON schema constraint, including required fields, enum values, "
        "minItems, maxItems, field types, numeric ranges, and extra=forbid.\n"
        f"Schema name: {output_model.__name__}\n"
        f"Validation observation from attempt {attempt}/{max_attempts}:\n{type(error).__name__}: {error}\n\n"
        f"Output JSON schema:\n{output_json_schema}"
    )


def _emit_model_usage_context_window(
    *,
    state: Any,
    services: Any | None,
    node_id: str | None,
    model_role: str,
    usage_observation: dict[str, Any],
) -> None:
    if services is None or node_id is None:
        return
    token_count = int(usage_observation.get("total_tokens") or 0)
    limits = model_context_limits(services=services, state=state, model_role=model_role)
    context_runtime = getattr(services, "context_system", None)
    resolve_context_limits = getattr(context_runtime, "model_context_limits", None)
    if callable(resolve_context_limits):
        limits = resolve_context_limits(
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
    context = getattr(state, "context", None)
    if context is not None and hasattr(context, "token_budget"):
        context.token_budget = {
            **dict(getattr(context, "token_budget", {}) or {}),
            **payload,
        }
    emit_context_event(
        services=services,
        state=state,
        event_type="context_window_updated",
        node_id=node_id,
        payload=payload,
    )
