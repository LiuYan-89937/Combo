"""LLM-based tool output compression.

When a tool output exceeds the model-visible character limit, this module
calls the configured compression model to produce a semantically faithful
summary that retains file paths, data structures, and error messages.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage


DEFAULT_COMPRESSION_MAX_CHARS = 6000

COMPRESSION_SYSTEM_PROMPT = (
    "You are a tool-output compressor for an autonomous coding agent. "
    "Your job is to condense the raw tool output below into a concise summary "
    "that the agent can use to continue its work WITHOUT re-calling the tool.\n\n"
    "Rules:\n"
    "- Preserve ALL file paths, directory names, and package-relative paths verbatim.\n"
    "- Preserve ALL error messages, exception types, and stack traces.\n"
    "- Preserve data structure keys, schemas, and contract identifiers.\n"
    "- Preserve numeric counts (number of files, entries, etc.).\n"
    "- Remove redundant formatting, repeated patterns, and verbose boilerplate.\n"
    "- Use compact notation: list items as comma-separated when possible.\n"
    "- If the output is a file listing, output paths one per line without extra metadata.\n"
    "- Do NOT add commentary, interpretation, or suggestions.\n"
    "- Output plain text only, no markdown fences."
)


@dataclass(frozen=True, slots=True)
class ToolOutputCompression:
    compressed_text: str
    compressed: bool
    original_chars: int
    compressed_chars: int


def compress_tool_output(
    output: dict[str, Any],
    *,
    tool_id: str,
    arguments: dict[str, Any],
    max_chars: int = DEFAULT_COMPRESSION_MAX_CHARS,
    model: BaseChatModel | None = None,
) -> ToolOutputCompression:
    """Compress tool output using the compression model.

    If the model is unavailable or compression fails, returns the output
    truncated to max_chars with a truncation marker.
    """
    raw_text = json.dumps(output, ensure_ascii=False, sort_keys=True, default=str)
    original_chars = len(raw_text)

    if original_chars <= max_chars:
        return ToolOutputCompression(
            compressed_text=raw_text,
            compressed=False,
            original_chars=original_chars,
            compressed_chars=original_chars,
        )

    if model is None:
        return _fallback_truncation(raw_text, max_chars=max_chars, original_chars=original_chars)

    try:
        compressed = _invoke_compression(
            model=model,
            raw_text=raw_text,
            tool_id=tool_id,
            arguments=arguments,
            max_chars=max_chars,
        )
        return ToolOutputCompression(
            compressed_text=compressed,
            compressed=True,
            original_chars=original_chars,
            compressed_chars=len(compressed),
        )
    except Exception:
        return _fallback_truncation(raw_text, max_chars=max_chars, original_chars=original_chars)


def _invoke_compression(
    *,
    model: BaseChatModel,
    raw_text: str,
    tool_id: str,
    arguments: dict[str, Any],
    max_chars: int,
) -> str:
    args_summary = json.dumps(arguments, ensure_ascii=False, default=str)[:200]
    user_content = (
        f"Tool: {tool_id}\n"
        f"Arguments: {args_summary}\n"
        f"Target compressed length: ≤{max_chars} characters\n"
        f"Original length: {len(raw_text)} characters\n\n"
        f"--- RAW OUTPUT START ---\n{raw_text}\n--- RAW OUTPUT END ---"
    )
    messages = [
        SystemMessage(content=COMPRESSION_SYSTEM_PROMPT),
        HumanMessage(content=user_content),
    ]
    response = model.invoke(messages)
    text = str(response.content or "").strip()
    if not text:
        raise ValueError("compression model returned empty response")
    # If the model output still exceeds budget, hard-truncate the tail
    if len(text) > max_chars:
        text = text[:max_chars]
    return text


def _fallback_truncation(raw_text: str, *, max_chars: int, original_chars: int) -> ToolOutputCompression:
    half = max(200, (max_chars - 100) // 2)
    truncated = f"{raw_text[:half]}\n... [truncated {original_chars - 2 * half} chars] ...\n{raw_text[-half:]}"
    if len(truncated) > max_chars:
        truncated = raw_text[:max_chars - 50] + f"\n... [truncated, total {original_chars} chars]"
    return ToolOutputCompression(
        compressed_text=truncated,
        compressed=True,
        original_chars=original_chars,
        compressed_chars=len(truncated),
    )
