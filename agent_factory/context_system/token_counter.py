from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage

from agent_factory.models import get_main_model, get_task_model


@dataclass(frozen=True, slots=True)
class TokenCountResult:
    token_count: int | None
    method: str
    error: str | None = None
    model_role: str | None = None


def context_window_tokens_from_env() -> int | None:
    value = os.getenv("AGENTFACTORY_CONTEXT_WINDOW_TOKENS")
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def count_messages_tokens(
    messages: list[Any],
    *,
    services: Any | None = None,
    model: Any | None = None,
    tools: list[Any] | None = None,
) -> TokenCountResult:
    selected_model = model
    model_role: str | None = None
    if selected_model is None:
        model_role = _model_role_from_services(services)
        selected_model = _model_for_role(model_role)
    if selected_model is None:
        return TokenCountResult(
            token_count=None,
            method="unavailable",
            error="model tokenizer is unavailable",
            model_role=model_role,
        )
    normalized = [message for message in messages if isinstance(message, BaseMessage)]
    if not normalized:
        normalized = [HumanMessage(content=str(message)) for message in messages if str(message)]
    counter = getattr(selected_model, "get_num_tokens_from_messages", None)
    if not callable(counter):
        return TokenCountResult(
            token_count=None,
            method="unavailable",
            error="model does not expose get_num_tokens_from_messages",
            model_role=model_role,
        )
    try:
        method = "model_tokenizer_messages_only" if tools else "model_tokenizer"
        return TokenCountResult(
            token_count=int(counter(normalized)),
            method=method,
            model_role=model_role,
        )
    except TypeError:
        try:
            return TokenCountResult(
                token_count=int(counter(normalized)),
                method="model_tokenizer",
                model_role=model_role,
            )
        except Exception as exc:
            return _count_error(exc, model_role=model_role)
    except Exception as exc:
        return _count_error(exc, model_role=model_role)


def count_text_tokens(text: str, *, services: Any | None = None, model: Any | None = None) -> TokenCountResult:
    if not text:
        return TokenCountResult(token_count=0, method="model_tokenizer", model_role=_model_role_from_services(services))
    return count_messages_tokens([HumanMessage(content=text)], services=services, model=model)


def context_window_payload(
    *,
    node_id: str,
    token_count: int | None,
    token_count_method: str,
    compression_threshold_tokens: int | None,
    context_window_tokens: int | None = None,
    error: str | None = None,
    model_role: str | None = None,
    source: str,
) -> dict[str, Any]:
    window = context_window_tokens if context_window_tokens is not None else context_window_tokens_from_env()
    payload: dict[str, Any] = {
        "node_id": node_id,
        "source": source,
        "token_count": token_count,
        "token_count_method": token_count_method,
        "context_window_tokens": window,
        "compression_threshold_tokens": compression_threshold_tokens,
        "model_role": model_role,
    }
    if token_count is not None and window:
        payload["window_usage_ratio"] = min(float(token_count) / float(window), 1.0)
    if token_count is not None and compression_threshold_tokens:
        payload["compression_usage_ratio"] = min(float(token_count) / float(compression_threshold_tokens), 1.0)
    if error:
        payload["error"] = error
    return payload


def token_count_from_usage_metadata(usage: Any) -> int | None:
    if not isinstance(usage, dict):
        return None
    for key in ("input_tokens", "prompt_tokens"):
        value = usage.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return None


def output_token_count_from_usage_metadata(usage: Any) -> int | None:
    if not isinstance(usage, dict):
        return None
    for key in ("output_tokens", "completion_tokens"):
        value = usage.get(key)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
    return None


def cached_input_token_count_from_usage_metadata(usage: Any) -> int | None:
    if not isinstance(usage, dict):
        return None
    for details_key in ("input_token_details", "prompt_tokens_details"):
        details = usage.get(details_key)
        if not isinstance(details, dict):
            continue
        for key in ("cache_read", "cached_tokens"):
            value = details.get(key)
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                return int(value)
    return None


def _model_role_from_services(services: Any | None) -> str:
    if services is None:
        return "main"
    for service_name in ("model_operation_service", "model_service"):
        service = getattr(services, service_name, None)
        role = getattr(service, "model_role", None)
        if role:
            return str(role)
    return "main"


def _model_for_role(role: str | None) -> Any | None:
    if role == "task":
        return get_task_model()
    return get_main_model()


def _count_error(exc: Exception, *, model_role: str | None) -> TokenCountResult:
    return TokenCountResult(
        token_count=None,
        method="unavailable",
        error=f"{type(exc).__name__}: {exc}",
        model_role=model_role,
    )
