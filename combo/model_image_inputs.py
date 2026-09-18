from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage
from PIL import Image, ImageOps, ImageSequence


LOCAL_IMAGE_SOURCE_TYPE = "combo_local_path"
MODEL_IMAGE_MAX_SIZE = (4096, 4096)


def local_image_content_block(*, path: str | Path, mime_type: str) -> dict[str, Any]:
    return {
        "type": "image",
        "source_type": LOCAL_IMAGE_SOURCE_TYPE,
        "path": str(Path(path)),
        "mime_type": mime_type,
    }


def prepare_model_image_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    materialized: list[BaseMessage] = []
    for message in messages:
        content = getattr(message, "content", None)
        if not isinstance(content, list):
            materialized.append(message)
            continue
        changed = False
        blocks: list[Any] = []
        for block in content:
            prepared = _prepare_image_block(block)
            blocks.append(prepared)
            changed = changed or prepared is not block
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
    data, mime_type = prepare_model_image(path.read_bytes())
    return {
        "type": "image",
        "source_type": "base64",
        "mime_type": mime_type,
        "data": base64.b64encode(data).decode("ascii"),
    }


def prepare_model_image(data: bytes) -> tuple[bytes, str]:
    """Bound model inputs in memory without changing the source file."""
    with Image.open(BytesIO(data)) as source:
        image_format = source.format
        mime_type = Image.MIME.get(image_format or "")
        if mime_type is None:
            raise ValueError("model image input has an unknown image format")
        if source.width <= MODEL_IMAGE_MAX_SIZE[0] and source.height <= MODEL_IMAGE_MAX_SIZE[1]:
            return data, mime_type
        frames = []
        durations = []
        for frame in ImageSequence.Iterator(source):
            mode = "RGBA" if "A" in frame.getbands() or "transparency" in frame.info else "RGB"
            resized = ImageOps.exif_transpose(frame).convert(mode)
            resized.thumbnail(MODEL_IMAGE_MAX_SIZE, Image.Resampling.LANCZOS)
            frames.append(resized)
            durations.append(frame.info.get("duration", 0))
        output = BytesIO()
        if len(frames) > 1:
            frames[0].save(
                output, format=image_format, save_all=True, append_images=frames[1:],
                duration=durations,
                **({"loop": source.info["loop"]} if "loop" in source.info else {}),
            )
        else:
            frames[0].save(output, format="PNG")
            mime_type = "image/png"
        return output.getvalue(), mime_type


def _prepare_image_block(block: Any) -> Any:
    if is_local_image_content_block(block):
        return _materialize_local_image_block(block)
    if not isinstance(block, dict):
        return block
    if block.get("type") == "image" and block.get("source_type") == "base64":
        data, mime_type = prepare_model_image(base64.b64decode(block["data"], validate=True))
        return {**block, "mime_type": mime_type, "data": base64.b64encode(data).decode("ascii")}
    if block.get("type") == "image_url":
        reference = block.get("image_url")
        url = reference.get("url") if isinstance(reference, dict) else reference
        if isinstance(url, str) and url.startswith("data:image/"):
            header, separator, encoded = url.partition(",")
            if not separator or not header.endswith(";base64"):
                raise ValueError("inline model images must use base64 data URLs")
            data, mime_type = prepare_model_image(base64.b64decode(encoded, validate=True))
            prepared_url = f"data:{mime_type};base64,{base64.b64encode(data).decode('ascii')}"
            prepared_reference = (
                {**reference, "url": prepared_url} if isinstance(reference, dict) else prepared_url
            )
            return {**block, "image_url": prepared_reference}
    return block
