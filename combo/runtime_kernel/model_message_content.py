from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, TypeGuard

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from combo.runtime_attachments import image_attachment_content_parts


def message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                value = item.get("text") or item.get("content")
                if value:
                    parts.append(str(value))
        return "\n".join(parts)
    return str(content)


def is_image_content_block(block: Any) -> TypeGuard[dict[str, Any]]:
    if not isinstance(block, dict):
        return False
    block_type = str(block.get("type") or "").strip()
    if block_type in {"image", "image_url", "input_image"}:
        return True
    source = block.get("source")
    return isinstance(source, dict) and str(source.get("media_type") or "").startswith("image/")


def message_image_parts(message: BaseMessage) -> list[dict[str, Any]]:
    content = message.content
    if not isinstance(content, list):
        return []
    return [item for item in content if is_image_content_block(item)]


def copy_human_message_with_content(
    message: HumanMessage,
    content: str | list[str | dict[str, Any]],
) -> HumanMessage:
    return message.model_copy(update={"content": content})


def project_model_message_content(
    messages: Sequence[BaseMessage], *, image_input_enabled: bool,
) -> list[BaseMessage]:
    """Keep tool replies textual and place live tool images after the full reply group."""
    latest_ai_index = max(
        (index for index, message in enumerate(messages) if isinstance(message, AIMessage)),
        default=-1,
    )
    projected: list[BaseMessage] = []
    pending_tool_images: list[dict[str, Any]] = []

    def finish_tool_replies() -> None:
        if pending_tool_images:
            blocks: list[str | dict[str, Any]] = list(pending_tool_images)
            projected.append(HumanMessage(content=blocks))
            pending_tool_images.clear()

    for index, message in enumerate(messages):
        if not isinstance(message, ToolMessage):
            finish_tool_replies()
            projected.append(_without_historical_images(message))
            continue

        if image_input_enabled and index > latest_ai_index:
            inline_images = message_image_parts(message)
            pending_tool_images.extend(inline_images or _tool_metadata_image_parts(message))
        projected.append(message.model_copy(update={"content": _tool_text_content(message.content)}))

    finish_tool_replies()
    return projected


def _without_historical_images(message: BaseMessage) -> BaseMessage:
    content = message.content
    if not isinstance(content, list):
        return message
    retained = [block for block in content if not is_image_content_block(block)]
    if not retained:
        normalized: str | list[Any] = ""
    elif len(retained) == 1 and isinstance(retained[0], dict) and retained[0].get("type") == "text":
        normalized = str(retained[0].get("text") or "")
    else:
        normalized = retained
    return message.model_copy(update={"content": normalized})


def _tool_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False, default=str)
    if not isinstance(content, list):
        return str(content)
    text_parts: list[str] = []
    for block in content:
        if is_image_content_block(block):
            continue
        if isinstance(block, str):
            text_parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(str(block.get("text") or ""))
        else:
            text_parts.append(json.dumps(block, ensure_ascii=False, default=str))
    return "\n".join(text_parts)


def _tool_metadata_image_parts(message: ToolMessage) -> list[dict[str, Any]]:
    metadata = dict(message.additional_kwargs or {}).get("combo_tool_image")
    if not isinstance(metadata, dict):
        return []
    path = str(metadata.get("path") or "").strip()
    mime_type = str(metadata.get("mime_type") or "").strip()
    if not path or not mime_type.startswith("image/"):
        raise ValueError("tool image metadata requires an image path and MIME type")
    return image_attachment_content_parts([{"path": path, "mime_type": mime_type}])
