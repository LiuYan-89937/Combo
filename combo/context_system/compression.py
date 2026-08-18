from __future__ import annotations

from time import perf_counter
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from combo.context_system.schema import CompressionDetail, CompressionPolicy, ContextCompressionReport
from combo.context_system.token_counter import TokenCountResult
from combo.context_system.token_estimation import estimate_messages_tokens, estimate_text_tokens
from combo.models import get_compression_model
from combo.runtime_protocol.messages import incomplete_tool_call_ids


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
    token_counter: Callable[[list[Any]], TokenCountResult] | None = None,
    trigger_count: TokenCountResult | None = None,
    on_start: Callable[[ContextCompressionReport], None] | None = None,
    force: bool = False,
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
    if not force and token_before < policy.trigger_token_threshold:
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
    protected, compressible, recent = _partition_messages(
        messages,
        keep_recent=policy.keep_recent_messages,
        minimum_token_reduction=(
            1
            if force
            else max(token_before - policy.trigger_token_threshold, 1)
        ),
    )
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
        compressed_messages = [
            _without_inline_image_payload(message)
            for message in [*protected, *summary_messages, *recent]
        ]
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
    minimum_token_reduction: int,
) -> tuple[list[Any], list[Any], list[Any]]:
    normalized = list(messages)
    protected: list[Any] = []
    cursor = 0
    while cursor < len(normalized) and _is_protected_message(normalized[cursor]):
        protected.append(normalized[cursor])
        cursor += 1
    history_count = len(normalized) - cursor
    if history_count <= keep_recent:
        return protected, [], normalized[cursor:]

    preferred_boundary = len(normalized) - keep_recent
    selected_boundary: int | None = None
    for boundary in range(preferred_boundary, cursor, -1):
        if boundary < len(normalized) and _is_tool_message(normalized[boundary]):
            continue
        candidate = normalized[cursor:boundary]
        recent_candidate = normalized[boundary:]
        if (
            not candidate
            or incomplete_tool_call_ids(candidate)
            or incomplete_tool_call_ids(recent_candidate)
        ):
            continue
        selected_boundary = boundary
        break
    if selected_boundary is None:
        return protected, [], normalized[cursor:]

    if estimate_messages_tokens(normalized[cursor:selected_boundary]) < minimum_token_reduction:
        return protected, [], normalized[cursor:]

    compressible = normalized[cursor:selected_boundary]
    recent = normalized[selected_boundary:]
    return protected, compressible, recent


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


def _is_tool_message(message: Any) -> bool:
    return isinstance(message, ToolMessage)


def _without_inline_image_payload(message: Any) -> Any:
    content = getattr(message, "content", None)
    if not isinstance(content, list) or not hasattr(message, "model_copy"):
        return message
    retained = [block for block in content if not _is_image_content_block(block)]
    if retained == content:
        return message
    normalized: str | list[Any]
    if len(retained) == 1 and isinstance(retained[0], dict) and retained[0].get("type") == "text":
        normalized = str(retained[0].get("text") or "")
    else:
        normalized = retained
    return message.model_copy(update={"content": normalized})


def _is_image_content_block(block: Any) -> bool:
    if not isinstance(block, dict):
        return False
    if str(block.get("type") or "").strip() in {"image", "image_url", "input_image"}:
        return True
    source = block.get("source")
    return isinstance(source, dict) and str(source.get("media_type") or "").startswith("image/")


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
) -> str:
    return _invoke_summary_model(
        system_prompt=(
            "You are incrementally compacting conversation history into private runtime state for a future agent turn. "
            "The input may contain an earlier conversation summary followed by newer messages. Merge them into one updated summary. "
            "Do not summarize tool payloads here; tool evidence is compacted independently.\n\n"
            "Return exactly this structure:\n"
            "<conversation_summary>\n"
            "  <user_intent>...</user_intent>\n"
            "  <key_facts>...</key_facts>\n"
            "  <completed_actions>...</completed_actions>\n"
            "  <active_state>...</active_state>\n"
            "  <continuation_instructions>...</continuation_instructions>\n"
            "</conversation_summary>\n\n"
            + _detail_instruction(detail)
            + "\nPreserve exact names, numbers, URLs, paths, IDs, decisions, constraints, failures, and pending work when they affect continuity. "
            "Remove greetings, repetition, and stale narration. If a section has no useful content, write 'None'. "
            "Do not invent facts and return only the tagged summary."
        ),
        input_text=conversation_input,
        expected_tag="conversation_summary",
        max_output_tokens=max_output_tokens,
    )


def _summarize_tool_results(
    tool_input: str,
    *,
    detail: CompressionDetail,
    max_output_tokens: int,
) -> str:
    return _invoke_summary_model(
        system_prompt=(
            "You are incrementally compacting tool and knowledge results into private runtime state for a future agent turn. "
            "The input may contain an earlier tool summary followed by newer tool calls and results. Merge them into one updated summary. "
            "The original payloads remain stored outside model context, so retain only evidence needed to continue without repeating completed work.\n\n"
            "Return exactly this structure:\n"
            "<tool_results_summary>\n"
            "  <confirmed_results>...</confirmed_results>\n"
            "  <artifacts_and_references>...</artifacts_and_references>\n"
            "  <errors_and_constraints>...</errors_and_constraints>\n"
            "  <repeat_avoidance>...</repeat_avoidance>\n"
            "</tool_results_summary>\n\n"
            + _detail_instruction(detail)
            + "\nPreserve tool names and exact result details only when they affect later decisions. Never paste large raw payloads. "
            "Distinguish confirmed output from inference. If a section has no useful content, write 'None'. "
            "Do not invent facts and return only the tagged summary."
        ),
        input_text=tool_input,
        expected_tag="tool_results_summary",
        max_output_tokens=max_output_tokens,
    )


def _invoke_summary_model(
    *,
    system_prompt: str,
    input_text: str,
    expected_tag: str,
    max_output_tokens: int,
) -> str:
    model = get_compression_model(max_output_tokens=max_output_tokens)
    if model is None:
        raise RuntimeError("compression model is not configured")
    prompt = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=input_text),
    ]
    response = model.invoke(prompt)
    text = _message_text(response).strip()
    if not text:
        raise RuntimeError("compression model returned empty summary")
    if not text.startswith(f"<{expected_tag}>") or not text.endswith(f"</{expected_tag}>"):
        raise RuntimeError(f"compression model returned invalid {expected_tag} structure")
    return text


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
