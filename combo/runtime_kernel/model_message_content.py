from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from combo.model_image_inputs import is_image_content_block, tool_image_parts


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


def copy_human_message_with_content(
    message: HumanMessage,
    content: str | list[str | dict[str, Any]],
) -> HumanMessage:
    return message.model_copy(update={"content": content})


def project_model_message_content(
    messages: Sequence[BaseMessage], *, image_input_enabled: bool,
) -> list[BaseMessage]:
    """Keep image-message identities and boundaries stable after each tool reply group."""
    latest_ai_index = max(
        (index for index, message in enumerate(messages) if isinstance(message, AIMessage)),
        default=-1,
    )
    projected: list[BaseMessage] = []
    pending_tool_images: list[dict[str, Any]] = []
    image_tool_call_ids: list[str] = []

    def finish_tool_replies() -> None:
        if image_tool_call_ids:
            # Keep the same user boundary after image bytes become historical or
            # the selected model changes its image-input capability.
            text = "Tool images: " + ", ".join(image_tool_call_ids)
            blocks: list[str | dict[str, Any]] = [
                {"type": "text", "text": text}, *pending_tool_images,
            ]
            projected.append(
                HumanMessage(id=f"tool-images:{image_tool_call_ids[0]}", content=blocks)
            )
            pending_tool_images.clear()
            image_tool_call_ids.clear()

    for index, message in enumerate(messages):
        if not isinstance(message, ToolMessage):
            finish_tool_replies()
            projected.append(_without_historical_images(message))
            continue

        images = tool_image_parts(message)
        if images:
            image_tool_call_ids.append(message.tool_call_id)
            if image_input_enabled and index > latest_ai_index:
                pending_tool_images.extend(images)
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
