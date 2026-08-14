from __future__ import annotations

from typing import Any


def estimate_messages_tokens(messages: list[Any]) -> int:
    return sum(estimate_text_tokens(message_text(message)) for message in messages)


def estimate_text_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


def message_text(message: Any) -> str:
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
                parts.append("[image]")
                continue
            value = block.get("text") or block.get("content")
            if isinstance(value, str):
                parts.append(value)
        return "\n".join(parts)
    return str(content)
