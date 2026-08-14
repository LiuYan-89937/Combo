from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage


LOCAL_IMAGE_SOURCE_TYPE = "combo_local_path"


def local_image_content_block(*, path: str | Path, mime_type: str) -> dict[str, Any]:
    return {
        "type": "image",
        "source_type": LOCAL_IMAGE_SOURCE_TYPE,
        "path": str(Path(path)),
        "mime_type": mime_type,
    }


def materialize_local_image_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    materialized: list[BaseMessage] = []
    for message in messages:
        content = getattr(message, "content", None)
        if not isinstance(content, list):
            materialized.append(message)
            continue
        changed = False
        blocks: list[Any] = []
        for block in content:
            if not is_local_image_content_block(block):
                blocks.append(block)
                continue
            blocks.append(_materialize_local_image_block(block))
            changed = True
        materialized.append(message.model_copy(update={"content": blocks}) if changed else message)
    return materialized


def is_local_image_content_block(block: Any) -> bool:
    return (
        isinstance(block, dict)
        and str(block.get("type") or "").strip() == "image"
        and str(block.get("source_type") or "").strip() == LOCAL_IMAGE_SOURCE_TYPE
    )


def _materialize_local_image_block(block: dict[str, Any]) -> dict[str, Any]:
    path = Path(str(block.get("path") or "")).expanduser()
    mime_type = str(block.get("mime_type") or "").strip()
    if not path.is_file():
        raise FileNotFoundError(f"model image input does not exist: {path}")
    if not mime_type.startswith("image/"):
        raise ValueError(f"model image input has an invalid MIME type: {mime_type or '<empty>'}")
    return {
        "type": "image",
        "source_type": "base64",
        "mime_type": mime_type,
        "data": base64.b64encode(path.read_bytes()).decode("ascii"),
    }
