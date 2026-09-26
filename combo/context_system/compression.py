from __future__ import annotations

from time import perf_counter
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel

from combo.context_system.memory_context import project_memory_tool_messages
from combo.context_system.schema import (
    CompressionDetail,
    CompressionPolicy,
    ContextCompressionReport,
    ConversationCompressionSummary,
    ToolResultsCompressionSummary,
)
from combo.context_system.token_counter import TokenCountResult
from combo.context_system.token_estimation import estimate_messages_tokens, estimate_text_tokens
from combo.runtime_protocol.messages import has_complete_tool_call_history, represented_input_message_ids
from combo.model_invocation.structured_output import (
    execute_structured_output_invocation,
    prepare_structured_output_invocation,
)


LEGACY_CONTEXT_SUMMARY_KIND = "context_summary"
CONVERSATION_SUMMARY_KIND = "context_conversation_summary"
TOOL_SUMMARY_KIND = "context_tool_summary"
CONTEXT_SUMMARY_KINDS = frozenset({
    LEGACY_CONTEXT_SUMMARY_KIND,
    CONVERSATION_SUMMARY_KIND,
    TOOL_SUMMARY_KIND,
})
MAX_SUMMARY_OUTPUT_NUMERATOR = 2
MAX_SUMMARY_OUTPUT_DENOMINATOR = 5


def maybe_compress_messages(
    *,
    messages: list[Any],
    policy: CompressionPolicy,
    node_id: str,
    summary_model: Any,
    summary_model_max_output_tokens: int | None,
    summary_model_metadata: dict[str, Any] | None = None,
    protected_message_ids: tuple[str, ...] = (),
    token_counter: Callable[[list[Any]], TokenCountResult] | None = None,
    trigger_count: TokenCountResult | None = None,
    on_start: Callable[[ContextCompressionReport], None] | None = None,
    force: bool = False,
) -> tuple[list[Any], ContextCompressionReport]:
    started = perf_counter()
    if not policy.enabled:
        return messages, ContextCompressionReport(status="skipped", node_id=node_id, reason="disabled")
    threshold = policy.trigger_token_threshold
    if threshold is None:
        raise RuntimeError("compression trigger token threshold is unavailable")
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
                reason="token_count_unavailable",
                duration_ms=int((perf_counter() - started) * 1000),
            ),
        )
    token_before = count_before.token_count
    if not force and token_before < threshold:
        return (
            messages,
            ContextCompressionReport(
                status="skipped",
                node_id=node_id,
                reason="below_threshold",
                original_message_count=len(messages),
                compressed_message_count=len(messages),
                token_estimate_before=token_before,
                token_estimate_after=token_before,
                token_count_method=count_before.method,
                duration_ms=int((perf_counter() - started) * 1000),
            ),
        )
    protected, compressible, recent = _partition_messages(
        messages,
        keep_recent=policy.keep_recent_messages,
        protected_message_ids=protected_message_ids,
    )
    if not compressible:
        return (
            messages,
            ContextCompressionReport(
                status="skipped",
                node_id=node_id,
                reason="no_compressible_history",
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
                    compacted_message_count=len(compressible),
                    token_estimate_before=token_before,
                    token_estimate_after=token_before,
                    token_count_method=count_before.method,
                    duration_ms=int((perf_counter() - started) * 1000),
                )
            )
        summary_output_token_limit = _summary_output_token_limit(policy)
        conversation_input = _conversation_text(compressible)
        tool_input = _tool_results_text(compressible)
        conversation_limit, tool_limit = _allocate_summary_output(
            conversation_input=conversation_input,
            tool_input=tool_input,
            total_limit=summary_output_token_limit,
        )
        summary_messages: list[SystemMessage] = []
        conversation_summary = ""
        tool_summary = ""
        if conversation_input:
            conversation_summary = _summarize_conversation(
                conversation_input,
                detail=policy.detail,
                max_output_tokens=conversation_limit,
                model=summary_model,
                model_max_output_tokens=summary_model_max_output_tokens,
                model_metadata=summary_model_metadata,
            )
            summary_messages.append(
                _summary_message(
                    content=conversation_summary,
                    kind=CONVERSATION_SUMMARY_KIND,
                    compacted_message_count=len(compressible),
                    detail=policy.detail,
                    summary_output_token_limit=summary_output_token_limit,
                )
            )
        if tool_input:
            tool_summary = _summarize_tool_results(
                tool_input,
                detail=policy.detail,
                max_output_tokens=tool_limit,
                model=summary_model,
                model_max_output_tokens=summary_model_max_output_tokens,
                model_metadata=summary_model_metadata,
            )
            summary_messages.append(
                _summary_message(
                    content=tool_summary,
                    kind=TOOL_SUMMARY_KIND,
                    compacted_message_count=len(compressible),
                    detail=policy.detail,
                    summary_output_token_limit=summary_output_token_limit,
                )
            )
        if not summary_messages:
            raise RuntimeError("compression input contains no summarizable content")
        compacted_input_ids = sorted(represented_input_message_ids(compressible))
        for message in summary_messages:
            message.additional_kwargs["compacted_input_message_ids"] = compacted_input_ids
        compressed_messages = [*protected, *summary_messages, *recent]
        if not has_complete_tool_call_history(compressed_messages):
            raise RuntimeError("compressed messages contain an invalid tool call history")
        # Compare like-for-like estimates. Provider usage can include tool
        # schemas and other overhead that is not part of the compressible text.
        if estimate_messages_tokens(summary_messages) >= estimate_messages_tokens(compressible):
            return messages, ContextCompressionReport(
                status="skipped",
                reason="no_token_reduction",
                node_id=node_id,
                original_message_count=len(messages),
                compressed_message_count=len(messages),
                token_estimate_before=token_before,
                token_estimate_after=token_before,
                token_count_method=count_before.method,
                duration_ms=int((perf_counter() - started) * 1000),
            )
        count_after = _count_messages(compressed_messages, token_counter=token_counter)
        token_after = count_after.token_count or 0
        return (
            compressed_messages,
            ContextCompressionReport(
                status="completed",
                node_id=node_id,
                original_message_count=len(messages),
                compressed_message_count=len(compressed_messages),
                compacted_message_count=len(compressible),
                token_estimate_before=token_before,
                token_estimate_after=token_after,
                token_count_method=count_after.method,
                token_count_error=count_after.error,
                summary_token_estimate=(
                    estimate_text_tokens(conversation_summary)
                    + estimate_text_tokens(tool_summary)
                ),
                conversation_summary_token_estimate=estimate_text_tokens(conversation_summary),
                tool_summary_token_estimate=estimate_text_tokens(tool_summary),
                summary_output_token_limit=summary_output_token_limit,
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
        return TokenCountResult(token_count=estimate_messages_tokens(messages), method="text_estimation")
    return token_counter(messages)


def _partition_messages(
    messages: list[Any],
    *,
    keep_recent: int,
    protected_message_ids: tuple[str, ...],
) -> tuple[list[Any], list[Any], list[Any]]:
    """Retain individual instructions and a complete recent tool exchange.

    The current user message is a projection anchor, not the beginning of an
    immutable tail. Completed exchanges after it can be summarized in this turn.
    """
    required_ids = set(protected_message_ids)
    present_ids = {str(getattr(message, "id", "") or "") for message in messages}
    missing_ids = required_ids - present_ids
    if missing_ids:
        raise ValueError("protected compression messages are missing: " + ", ".join(sorted(missing_ids)))
    latest_instruction = next((
        message for message in reversed(messages)
        if isinstance(message, HumanMessage)
        and message.additional_kwargs.get("updates_current_user_input", True)
    ), None)

    # Move the boundary backwards until both halves contain complete exchanges.
    # Incomplete exchanges defer compression; no result is orphaned.
    for boundary in range(max(0, len(messages) - keep_recent), 0, -1):
        prefix, recent = messages[:boundary], messages[boundary:]
        if not has_complete_tool_call_history(prefix) or not has_complete_tool_call_history(recent):
            continue
        protected, compressible = [], []
        for message in prefix:
            retained = (
                _is_protected_message(message)
                or str(getattr(message, "id", "") or "") in required_ids
                or message is latest_instruction
            )
            (protected if retained else compressible).append(message)
        # Existing summaries alone are not new history to compact on every call.
        if not any(not is_context_summary_message(message) for message in compressible):
            return list(messages), [], []
        if has_complete_tool_call_history(compressible):
            return protected, compressible, recent
    return list(messages), [], []


def _is_protected_message(message: Any) -> bool:
    if not isinstance(message, SystemMessage):
        return False
    metadata = dict(getattr(message, "additional_kwargs", {}) or {})
    return metadata.get("kind") not in CONTEXT_SUMMARY_KINDS


def is_context_summary_message(message: Any) -> bool:
    if not isinstance(message, SystemMessage):
        return False
    metadata = dict(getattr(message, "additional_kwargs", {}) or {})
    return metadata.get("kind") in CONTEXT_SUMMARY_KINDS


def _summary_output_token_limit(policy: CompressionPolicy) -> int:
    threshold = policy.trigger_token_threshold
    if threshold is None:
        raise RuntimeError("compression trigger token threshold is unavailable")
    return max(
        1,
        threshold * MAX_SUMMARY_OUTPUT_NUMERATOR // MAX_SUMMARY_OUTPUT_DENOMINATOR,
    )


def _allocate_summary_output(
    *,
    conversation_input: str,
    tool_input: str,
    total_limit: int,
) -> tuple[int, int]:
    if not conversation_input:
        return 0, total_limit
    if not tool_input:
        return total_limit, 0
    conversation_weight = max(1, estimate_text_tokens(conversation_input))
    tool_weight = max(1, estimate_text_tokens(tool_input))
    conversation_limit = max(
        1,
        total_limit * conversation_weight // (conversation_weight + tool_weight),
    )
    tool_limit = max(1, total_limit - conversation_limit)
    if conversation_limit + tool_limit > total_limit:
        conversation_limit = total_limit - tool_limit
    return conversation_limit, tool_limit


def _summary_message(
    *,
    content: str,
    kind: str,
    compacted_message_count: int,
    detail: CompressionDetail,
    summary_output_token_limit: int,
) -> SystemMessage:
    return SystemMessage(
        content=content,
        additional_kwargs={
            "kind": kind,
            "source": "runtime_context_compression",
            "compressed_message_count": compacted_message_count,
            "compression_detail": detail,
            "summary_output_token_limit": summary_output_token_limit,
        },
        id=f"context-summary-{uuid4().hex}",
    )


def _summarize_conversation(
    conversation_input: str,
    *,
    detail: CompressionDetail,
    max_output_tokens: int,
    model: Any | None,
    model_max_output_tokens: int | None,
    model_metadata: dict[str, Any] | None,
) -> str:
    return _invoke_summary_model(
        system_prompt=(
            "You are incrementally compacting conversation history into private runtime state for a future agent turn. "
            "The input may contain an earlier conversation summary followed by newer messages. Merge them into one updated summary. "
            "Do not summarize tool payloads here; tool evidence is compacted independently.\n\n"
            "Return one JSON object matching the requested structured output fields. "
            "Do not include markdown fences or explanatory text.\n\n"
            + _detail_instruction(detail)
            + "\nPreserve exact names, numbers, URLs, paths, IDs, decisions, constraints, failures, and pending work when they affect continuity. "
            "Remove greetings, repetition, and stale narration. If a field has no useful content, write 'None'. "
            "Do not invent facts."
        ),
        input_text=conversation_input,
        output_model=ConversationCompressionSummary,
        max_output_tokens=max_output_tokens,
        model=model,
        model_max_output_tokens=model_max_output_tokens,
        model_metadata=model_metadata,
    )


def _summarize_tool_results(
    tool_input: str,
    *,
    detail: CompressionDetail,
    max_output_tokens: int,
    model: Any | None,
    model_max_output_tokens: int | None,
    model_metadata: dict[str, Any] | None,
) -> str:
    return _invoke_summary_model(
        system_prompt=(
            "You are incrementally compacting tool and knowledge results into private runtime state for a future agent turn. "
            "The input may contain an earlier tool summary followed by newer tool calls and results. Merge them into one updated summary. "
            "The original payloads remain stored outside model context, so retain only evidence needed to continue without repeating completed work.\n\n"
            "Return one JSON object matching the requested structured output fields. "
            "Do not include markdown fences or explanatory text.\n\n"
            + _detail_instruction(detail)
            + "\nPreserve tool names and exact result details only when they affect later decisions. Never paste large raw payloads. "
            "Distinguish confirmed output from inference. If a field has no useful content, write 'None'. "
            "Do not invent facts."
        ),
        input_text=tool_input,
        output_model=ToolResultsCompressionSummary,
        max_output_tokens=max_output_tokens,
        model=model,
        model_max_output_tokens=model_max_output_tokens,
        model_metadata=model_metadata,
    )


def _invoke_summary_model(
    *,
    system_prompt: str,
    input_text: str,
    output_model: type[BaseModel],
    max_output_tokens: int,
    model: Any | None,
    model_max_output_tokens: int | None,
    model_metadata: dict[str, Any] | None,
) -> str:
    if model is None:
        raise RuntimeError("compression requires the active runtime model")
    prompt = [SystemMessage(content=system_prompt), HumanMessage(content=input_text)]
    effective_max_output_tokens = (
        min(max_output_tokens, model_max_output_tokens)
        if model_max_output_tokens is not None
        else max_output_tokens
    )
    invocation = prepare_structured_output_invocation(
        model=model,
        output_model=output_model,
        messages=prompt,
        model_metadata=dict(model_metadata or {}),
        config_tags=["context-compression", output_model.__name__],
    )
    execution = execute_structured_output_invocation(
        invocation,
        invoke_model=lambda structured_model, attempt_messages, _attempt: structured_model.invoke(
            list(attempt_messages),
            max_tokens=effective_max_output_tokens,
        ),
    )
    return execution.value.model_dump_json()


def _conversation_text(messages: list[Any]) -> str:
    lines: list[str] = []
    for message in messages:
        if isinstance(message, ToolMessage) or _summary_kind(message) == TOOL_SUMMARY_KIND:
            continue
        role = _message_role(message)
        content = _message_text(message)
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _tool_results_text(messages: list[Any]) -> str:
    # Keep memory provenance as tool history, while its content remains in the
    # replaceable runtime snapshot instead of becoming a second system summary.
    messages = project_memory_tool_messages(messages, selected_ids=set())
    tool_calls: dict[str, tuple[str, Any]] = {}
    for message in messages:
        if not isinstance(message, AIMessage):
            continue
        for call in list(getattr(message, "tool_calls", []) or []):
            if not isinstance(call, dict):
                continue
            call_id = str(call.get("id") or "").strip()
            if call_id:
                tool_calls[call_id] = (
                    str(call.get("name") or "tool").strip() or "tool",
                    call.get("args"),
                )
    sections: list[str] = []
    for message in messages:
        if _summary_kind(message) == TOOL_SUMMARY_KIND:
            content = _message_text(message)
            if content:
                sections.append("previous_tool_summary:\n" + content)
            continue
        if not isinstance(message, ToolMessage):
            continue
        call_id = str(getattr(message, "tool_call_id", "") or "").strip()
        name, arguments = tool_calls.get(call_id, ("tool", None))
        block = [f"tool: {name}"]
        if call_id:
            block.append(f"tool_call_id: {call_id}")
        if arguments not in (None, {}, []):
            block.append(f"arguments: {arguments}")
        block.append("result: " + _message_text(message))
        sections.append("\n".join(block))
    return "\n\n".join(sections)


def _summary_kind(message: Any) -> str:
    if not isinstance(message, SystemMessage):
        return ""
    return str(dict(getattr(message, "additional_kwargs", {}) or {}).get("kind") or "")


def _detail_instruction(detail: CompressionDetail) -> str:
    if detail == "concise":
        return "Be concise: retain only binding user intent, decisive facts, current state, confirmed outcomes, and the next required action."
    if detail == "detailed":
        return "Be detailed: retain all actionable facts, decisions, dependencies, exact identifiers, completed changes, failures, and unresolved branches."
    return "Use standard detail: preserve facts and outcomes needed for reliable continuation without retaining incidental narration."


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
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type") or "").strip()
            if block_type in {"image", "image_url", "input_image"}:
                parts.append("[image omitted from context summary]")
                continue
            value = block.get("text") or block.get("content")
            if isinstance(value, str):
                parts.append(value)
        return "\n".join(parts)
    return str(content)
