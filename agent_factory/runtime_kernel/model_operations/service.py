from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from agent_factory.runtime_kernel.adapters.model import (
    ModelRole,
    _bind_tools,
    _configured_model_for_role,
    _content_to_text,
    strip_internal_snapshot_blocks,
    _tool_calls_from_response,
)
from agent_factory.runtime_kernel.model_inputs import build_runtime_model_input
from agent_factory.runtime_kernel.types import ModelInvocationResult
from agent_factory.context_system.events import emit_context_event
from agent_factory.context_system.token_counter import (
    cached_input_token_count_from_usage_metadata,
    count_messages_tokens,
    context_window_payload,
    output_token_count_from_usage_metadata,
    token_count_from_usage_metadata,
)


class ModelOperationService:
    """Kernel-level model operations used by generated Agent runtimes.

    The service is intentionally limited to model invocation shapes. It does
    not decide graph routes, plan tools, approve tools, or execute tools.
    """

    def __init__(self, *, role: ModelRole = "main", model: Any | None = None) -> None:
        self.model_role = role
        self._model = model

    def text(
        self,
        *,
        state: Any,
        prompt_binding: dict[str, Any] | None = None,
        messages: list[Any] | None = None,
        emit_event=None,
    ) -> ModelInvocationResult:
        return self.tool_bound_chat(
            state=state,
            prompt_binding=prompt_binding,
            messages=messages,
            tools=[],
            emit_event=emit_event,
        )

    def tool_bound_chat(
        self,
        *,
        state: Any,
        prompt_binding: dict[str, Any] | None = None,
        messages: list[Any] | None = None,
        tools: list[BaseTool] | None = None,
        emit_event=None,
        services: Any | None = None,
        node_id: str | None = None,
    ) -> ModelInvocationResult:
        model, metadata = self._resolve_model()
        tool_list = list(tools or [])
        envelope = build_runtime_model_input(
            state=state,
            prompt_binding=prompt_binding or {},
            messages=messages or [],
            tools=tool_list,
            node_id=node_id,
        )
        _emit_context_window(
            state=state,
            services=services,
            node_id=node_id,
            model=model,
            messages=envelope.messages,
            tools=tool_list,
            source="model_operation.before_call",
        )
        trace_span_id = _start_trace_span(
            state=state,
            services=services,
            node_id=node_id,
            operation="tool_bound_chat",
            payload={"model_role": self.model_role, **envelope.diagnostics()},
        )
        _emit(emit_event, "model_call_started", {"operation": "tool_bound_chat", "model_role": self.model_role})
        try:
            response = _bind_tools(model, tool_list).invoke(envelope.messages)
        except Exception as exc:
            _emit(emit_event, "model_call_failed", {"operation": "tool_bound_chat", "error": str(exc)})
            _finish_trace_span(
                state=state,
                services=services,
                node_id=node_id,
                span_id=trace_span_id,
                operation="tool_bound_chat",
                status="failed",
                payload={"error": str(exc)},
            )
            raise
        text = strip_internal_snapshot_blocks(_content_to_text(getattr(response, "content", response))).strip()
        tool_calls = _tool_calls_from_response(response)
        usage_metadata = getattr(response, "usage_metadata", None) or {}
        cache_metrics = _model_cache_metrics_payload(
            state=state,
            node_id=node_id,
            model_metadata=metadata,
            usage_metadata=usage_metadata,
            input_diagnostics=envelope.diagnostics(),
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
        _emit(emit_event, "model_cache_metrics", cache_metrics)
        _emit_provider_usage_context_window(
            state=state,
            services=services,
            node_id=node_id,
            response=response,
        )
        _finish_trace_span(
            state=state,
            services=services,
            node_id=node_id,
            span_id=trace_span_id,
            operation="tool_bound_chat",
            status="completed",
            payload={
                "tool_call_count": len(tool_calls),
                "usage_metadata": usage_metadata,
                "model_input": envelope.diagnostics(),
                "model_cache": cache_metrics,
            },
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
                "provider_input_tokens": token_count_from_usage_metadata(usage_metadata),
                **envelope.diagnostics(),
            },
        )

    def structured_json(
        self,
        *,
        output_model: type[BaseModel],
        state: Any,
        prompt_binding: dict[str, Any] | None = None,
        messages: list[Any] | None = None,
        prebuilt_messages: list[Any] | None = None,
        structured_method: str | None = None,
        config_tags: list[str] | None = None,
        max_attempts: int = 3,
        emit_event=None,
        operation_metadata: dict[str, Any] | None = None,
        services: Any | None = None,
        node_id: str | None = None,
    ) -> BaseModel:
        model, metadata = self._resolve_model()
        envelope = None
        if prebuilt_messages is not None:
            request_messages = list(prebuilt_messages)
        else:
            envelope = build_runtime_model_input(
                state=state,
                prompt_binding=prompt_binding or {},
                messages=messages or [],
                tools=[],
                node_id=node_id,
            )
            request_messages = envelope.messages
        attempts = max(1, int(max_attempts))
        last_error: Exception | None = None
        operation_context = {**metadata, **(operation_metadata or {})}
        schema_payload = _schema_payload(output_model)
        trace_span_id = _start_trace_span(
            state=state,
            services=services,
            node_id=node_id,
            operation="structured_json",
            payload={"schema_name": output_model.__name__, **operation_context},
        )
        for attempt in range(1, attempts + 1):
            _emit(
                emit_event,
                "model_call_started",
                {"operation": "structured_json", "attempt": attempt, "max_attempts": attempts, **operation_context},
            )
            try:
                structured_model = _structured_model(
                    model=model,
                    output_model=output_model,
                    method=structured_method,
                    config_tags=config_tags,
                )
                result = structured_model.invoke(request_messages)
                if isinstance(result, output_model):
                    parsed = result
                else:
                    parsed = output_model.model_validate(result)
                _emit(
                    emit_event,
                    "model_call_completed",
                    {"operation": "structured_json", "attempt": attempt},
                )
                _finish_trace_span(
                    state=state,
                    services=services,
                    node_id=node_id,
                    span_id=trace_span_id,
                    operation="structured_json",
                    status="completed",
                    payload={
                        "attempt": attempt,
                        "schema_name": output_model.__name__,
                        "model_input": envelope.diagnostics() if envelope is not None else {},
                    },
                )
                return parsed
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
        _finish_trace_span(
            state=state,
            services=services,
            node_id=node_id,
            span_id=trace_span_id,
            operation="structured_json",
            status="failed",
            payload={"error": str(last_error), "schema_name": output_model.__name__},
        )
        raise RuntimeError(f"structured model operation failed after {attempts} attempts: {last_error}")

    def _resolve_model(self) -> tuple[Any, dict[str, Any]]:
        if self._model is not None:
            return self._model, {"model_role": self.model_role, "model": "injected"}
        model, settings = _configured_model_for_role(self.model_role)
        if model is None:
            raise RuntimeError(f"{self.model_role} model is not configured for AgentPackage runtime")
        return model, {"model_role": settings.role, "model": settings.model or ""}


def _emit(emit_event, event_type: str, payload: dict[str, Any]) -> None:
    if emit_event is None:
        return
    emit_event({"event_type": event_type, **payload})


def _model_cache_metrics_payload(
    *,
    state: Any,
    node_id: str | None,
    model_metadata: dict[str, Any],
    usage_metadata: dict[str, Any],
    input_diagnostics: dict[str, Any],
) -> dict[str, Any]:
    input_tokens = token_count_from_usage_metadata(usage_metadata)
    output_tokens = output_token_count_from_usage_metadata(usage_metadata)
    cached_input_tokens = cached_input_token_count_from_usage_metadata(usage_metadata)
    hit_ratio = None
    if input_tokens and cached_input_tokens is not None:
        hit_ratio = round(float(cached_input_tokens) / float(input_tokens), 6)
    return {
        "version": "runtime_model_cache_metrics.v0",
        "node_id": node_id,
        "agent_id": str(getattr(getattr(state, "run", None), "agent_id", "") or ""),
        "session_id": str(getattr(getattr(state, "run", None), "session_id", "") or ""),
        "run_id": str(getattr(getattr(state, "run", None), "run_id", "") or ""),
        "pattern_id": str(getattr(getattr(state, "run", None), "pattern_id", "") or ""),
        "model_role": model_metadata.get("model_role"),
        "model": model_metadata.get("model"),
        "provider_cache": {
            "available": cached_input_tokens is not None,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_input_tokens": cached_input_tokens,
            "hit_ratio": hit_ratio,
            "source": "usage_metadata.input_token_details.cache_read" if cached_input_tokens is not None else None,
        },
        "model_input": input_diagnostics,
    }


def _start_trace_span(
    *,
    state: Any,
    services: Any | None,
    node_id: str | None,
    operation: str,
    payload: dict[str, Any],
) -> str | None:
    recorder = getattr(services, "trace_recorder", None) if services is not None else None
    if recorder is None or state is None:
        return None
    return recorder.start_span(
        trace_id=state.observability.trace_id,
        run_id=state.run.run_id,
        span_kind="model.call",
        name=operation,
        node_id=node_id,
        payload=payload,
    )


def _finish_trace_span(
    *,
    state: Any,
    services: Any | None,
    node_id: str | None,
    span_id: str | None,
    operation: str,
    status: str,
    payload: dict[str, Any],
) -> None:
    recorder = getattr(services, "trace_recorder", None) if services is not None else None
    if recorder is None or state is None or span_id is None:
        return
    recorder.finish_span(
        trace_id=state.observability.trace_id,
        run_id=state.run.run_id,
        span_id=span_id,
        span_kind="model.call",
        name=operation,
        status=status,
        node_id=node_id,
        payload=payload,
    )


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


def _schema_payload(output_model: type[BaseModel]) -> str:
    try:
        return json.dumps(output_model.model_json_schema(), ensure_ascii=False, sort_keys=True)
    except Exception:
        return output_model.__name__


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


def _emit_context_window(
    *,
    state: Any,
    services: Any | None,
    node_id: str | None,
    model: Any,
    messages: list[Any],
    tools: list[BaseTool],
    source: str,
) -> None:
    if services is None or node_id is None:
        return
    threshold = _compression_threshold(services=services, node_id=node_id)
    result = count_messages_tokens(messages, services=services, model=model, tools=tools)
    if result.token_count is None:
        return
    emit_context_event(
        services=services,
        state=state,
        event_type="context_window_updated",
        node_id=node_id,
        payload=context_window_payload(
            node_id=node_id,
            token_count=result.token_count,
            token_count_method=result.method,
            compression_threshold_tokens=threshold,
            error=result.error,
            model_role=result.model_role or _model_role(services),
            source=source,
        ),
    )


def _emit_provider_usage_context_window(
    *,
    state: Any,
    services: Any | None,
    node_id: str | None,
    response: Any,
) -> None:
    if services is None or node_id is None:
        return
    token_count = token_count_from_usage_metadata(getattr(response, "usage_metadata", None))
    if token_count is None:
        return
    emit_context_event(
        services=services,
        state=state,
        event_type="context_window_updated",
        node_id=node_id,
        payload=context_window_payload(
            node_id=node_id,
            token_count=token_count,
            token_count_method="provider_usage",
            compression_threshold_tokens=_compression_threshold(services=services, node_id=node_id),
            model_role=_model_role(services),
            source="model_operation.provider_usage",
        ),
    )


def _compression_threshold(*, services: Any, node_id: str) -> int | None:
    runtime = getattr(services, "context_system", None)
    if runtime is None or not hasattr(runtime, "policy_for_node"):
        return None
    try:
        return int(runtime.policy_for_node(node_id).compression.trigger_token_threshold)
    except Exception:
        return None


def _model_role(services: Any) -> str:
    service = getattr(services, "model_operation_service", None)
    return str(getattr(service, "model_role", None) or "main")
