from __future__ import annotations

from time import perf_counter
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from agent_factory.context_system.schema import CompressionPolicy, ContextCompressionReport
from agent_factory.context_system.token_counter import TokenCountResult
from agent_factory.models import get_compression_model, get_compression_model_settings
from agent_factory.runtime_protocol.messages import incomplete_tool_call_ids


def maybe_compress_messages(
    *,
    messages: list[Any],
    policy: CompressionPolicy,
    node_id: str,
    token_counter: Callable[[list[Any]], TokenCountResult] | None = None,
    trigger_count: TokenCountResult | None = None,
    on_start: Callable[[ContextCompressionReport], None] | None = None,
) -> tuple[list[Any], ContextCompressionReport]:
    started = perf_counter()
    if not policy.enabled:
        return messages, ContextCompressionReport(status="skipped", node_id=node_id)
    count_before = trigger_count or _count_messages(messages, token_counter=token_counter)
    if count_before.token_count is None:
        return (
            messages,
            ContextCompressionReport(
                status="skipped",
                node_id=node_id,
                original_message_count=len(messages),
                compressed_message_count=len(messages),
                token_count_method=count_before.method,
                token_count_error=count_before.error,
                duration_ms=int((perf_counter() - started) * 1000),
            ),
        )
    token_before = count_before.token_count
    if token_before < policy.trigger_token_threshold:
        return (
            messages,
            ContextCompressionReport(
                status="skipped",
                node_id=node_id,
                original_message_count=len(messages),
                compressed_message_count=len(messages),
                token_estimate_before=token_before,
                token_estimate_after=token_before,
                token_count_method=count_before.method,
                duration_ms=int((perf_counter() - started) * 1000),
            ),
        )
    protected, compressible, recent = _partition_messages(messages, keep_recent=policy.keep_recent_messages)
    if not compressible:
        return (
            messages,
            ContextCompressionReport(
                status="skipped",
                node_id=node_id,
                original_message_count=len(messages),
                compressed_message_count=len(messages),
                token_estimate_before=token_before,
                token_estimate_after=token_before,
                token_count_method=count_before.method,
                duration_ms=int((perf_counter() - started) * 1000),
            ),
        )
    try:
        if on_start is not None:
            on_start(
                ContextCompressionReport(
                    status="started",
                    node_id=node_id,
                    original_message_count=len(messages),
                    compressed_message_count=len(messages),
                    token_estimate_before=token_before,
                    token_estimate_after=token_before,
                    token_count_method=count_before.method,
                    duration_ms=int((perf_counter() - started) * 1000),
                )
            )
        summary = _summarize_messages(compressible, max_summary_tokens=policy.max_summary_tokens)
        summary_message = SystemMessage(
            content=summary,
            additional_kwargs={
                "kind": "context_summary",
                "source": "runtime_context_compression",
                "compressed_message_count": len(compressible),
            },
            id=f"context-summary-{uuid4().hex}",
        )
        compressed_messages = [*protected, summary_message, *recent]
        missing = incomplete_tool_call_ids(compressed_messages)
        if missing:
            raise RuntimeError("compressed messages contain incomplete tool call history: " + ", ".join(missing))
        count_after = _count_messages(compressed_messages, token_counter=token_counter)
        token_after = count_after.token_count or 0
        return (
            compressed_messages,
            ContextCompressionReport(
                status="completed",
                node_id=node_id,
                original_message_count=len(messages),
                compressed_message_count=len(compressed_messages),
                token_estimate_before=token_before,
                token_estimate_after=token_after,
                token_count_method=count_after.method,
                token_count_error=count_after.error,
                summary_token_estimate=estimate_text_tokens(summary),
                duration_ms=int((perf_counter() - started) * 1000),
            ),
        )
    except Exception as exc:
        return (
            messages,
            ContextCompressionReport(
                status="failed",
                node_id=node_id,
                original_message_count=len(messages),
                compressed_message_count=len(messages),
                token_estimate_before=token_before,
                token_estimate_after=token_before,
                token_count_method=count_before.method,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=int((perf_counter() - started) * 1000),
            ),
        )


def _count_messages(
    messages: list[Any],
    *,
    token_counter: Callable[[list[Any]], TokenCountResult] | None,
) -> TokenCountResult:
    if token_counter is None:
        return TokenCountResult(token_count=estimate_messages_tokens(messages), method="legacy_approximation")
    return token_counter(messages)


def estimate_messages_tokens(messages: list[Any]) -> int:
    return sum(estimate_text_tokens(_message_text(message)) for message in messages)


def estimate_text_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def _partition_messages(messages: list[Any], *, keep_recent: int) -> tuple[list[Any], list[Any], list[Any]]:
    normalized = list(messages)
    protected: list[Any] = []
    cursor = 0
    while cursor < len(normalized) and _is_protected_message(normalized[cursor]):
        protected.append(normalized[cursor])
        cursor += 1
    tail_start = max(cursor, len(normalized) - keep_recent)
    while tail_start > cursor and _is_tool_message(normalized[tail_start]):
        tail_start -= 1
    compressible = normalized[cursor:tail_start]
    recent = normalized[tail_start:]
    return protected, compressible, recent


def _is_protected_message(message: Any) -> bool:
    if not isinstance(message, SystemMessage):
        return False
    metadata = dict(getattr(message, "additional_kwargs", {}) or {})
    return metadata.get("kind") != "context_summary"


def _is_tool_message(message: Any) -> bool:
    return isinstance(message, ToolMessage)


def _summarize_messages(messages: list[Any], *, max_summary_tokens: int) -> str:
    model = get_compression_model()
    settings = get_compression_model_settings()
    if model is None:
        raise RuntimeError("compression model is not configured")
    configured = model
    max_tokens = settings.max_tokens or max_summary_tokens
    if max_tokens is not None:
        configured = configured.bind(max_tokens=max_tokens)
    prompt = [
        SystemMessage(
            content=(
                "Summarize the conversation segment for continuing the same session. "
                "Preserve user goals, decisions, constraints, pending work, important tool results, and unresolved questions. "
                "Do not invent facts. Return only the summary text."
            )
        ),
        HumanMessage(content=_conversation_text(messages)),
    ]
    response = configured.invoke(prompt)
    content = getattr(response, "content", response)
    text = content if isinstance(content, str) else str(content)
    text = text.strip()
    if not text:
        raise RuntimeError("compression model returned empty summary")
    return text


def _conversation_text(messages: list[Any]) -> str:
    lines: list[str] = []
    for message in messages:
        role = _message_role(message)
        content = _message_text(message)
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _message_role(message: Any) -> str:
    if isinstance(message, HumanMessage):
        return "user"
    if isinstance(message, AIMessage):
        return "assistant"
    if isinstance(message, ToolMessage):
        return "tool"
    if isinstance(message, SystemMessage):
        return "system"
    return str(getattr(message, "type", "message"))


def _message_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    return str(content)
