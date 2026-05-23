from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.tools import BaseTool
from pydantic import BaseModel

from agent_factory.runtime_kernel.adapters.model import (
    ModelRole,
    _bind_tools,
    _configured_model_for_role,
    _content_to_text,
    _messages_for_state,
    _tool_calls_from_response,
)
from agent_factory.runtime_kernel.types import ModelInvocationResult
from agent_factory.context_system.events import emit_context_event
from agent_factory.context_system.token_counter import (
    count_messages_tokens,
    context_window_payload,
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
        request_messages = _messages_for_state(
            state=state,
            prompt_binding=prompt_binding or {},
            messages=messages or [],
            tools=tool_list,
        )
        _emit_context_window(
            state=state,
            services=services,
            node_id=node_id,
            model=model,
            messages=request_messages,
            tools=tool_list,
            source="model_operation.before_call",
        )
        _emit(emit_event, "model_call_started", {"operation": "tool_bound_chat", "model_role": self.model_role})
        try:
            response = _bind_tools(model, tool_list).invoke(request_messages)
        except Exception as exc:
            _emit(emit_event, "model_call_failed", {"operation": "tool_bound_chat", "error": str(exc)})
            raise
        text = _content_to_text(getattr(response, "content", response)).strip()
        tool_calls = _tool_calls_from_response(response)
        usage_metadata = getattr(response, "usage_metadata", None) or {}
        _emit(
            emit_event,
            "model_call_completed",
            {
                "operation": "tool_bound_chat",
                "tool_call_count": len(tool_calls),
                "usage_metadata": usage_metadata,
            },
        )
        _emit_provider_usage_context_window(
            state=state,
            services=services,
            node_id=node_id,
            response=response,
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
            },
        )

    def structured_json(
        self,
        *,
        output_model: type[BaseModel],
        state: Any,
        prompt_binding: dict[str, Any] | None = None,
        messages: list[Any] | None = None,
        max_attempts: int = 3,
        emit_event=None,
    ) -> BaseModel:
        model, metadata = self._resolve_model()
        request_messages = _messages_for_state(
            state=state,
            prompt_binding=prompt_binding or {},
            messages=messages or [],
            tools=[],
        )
        attempts = max(1, int(max_attempts))
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            _emit(
                emit_event,
                "model_call_started",
                {"operation": "structured_json", "attempt": attempt, **metadata},
            )
            try:
                structured_model = model.with_structured_output(output_model)
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
                return parsed
            except Exception as exc:
                last_error = exc
                _emit(
                    emit_event,
                    "model_call_failed",
                    {"operation": "structured_json", "attempt": attempt, "error": str(exc)},
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
