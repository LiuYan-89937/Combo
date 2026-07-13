from __future__ import annotations

from pathlib import Path
import mimetypes
from typing import Any
from uuid import uuid4

import httpx

from agent_factory.artifact_system import ArtifactStore
from agent_factory.models.image_generation.adapters import adapter_for_image_provider
from agent_factory.models.image_generation.protocol import (
    GeneratedAsset,
    ImageGenerationRequest,
    ImageGenerationSettings,
    ImageInput,
)


class ImageGenerationService:
    def __init__(self, *, settings: ImageGenerationSettings, artifact_store: ArtifactStore) -> None:
        self.settings = settings
        self.artifact_store = artifact_store
        self.adapter = adapter_for_image_provider(settings)

    def generate(self, request: ImageGenerationRequest) -> list[GeneratedAsset]:
        sources = self.adapter.generate(request)
        assets: list[GeneratedAsset] = []
        for index, source in enumerate(sources, start=1):
            image_bytes = source.data if source.data is not None else _download(source.url, timeout=self.settings.timeout_seconds)
            mime_type = source.mime_type or _mime_type_from_url(source.url) or "image/png"
            suffix = _extension_for_mime(mime_type)
            relative_path = f"images/{uuid4().hex}_{index}{suffix}"
            record = self.artifact_store.write_bytes(
                kind="artifact",
                relative_path=relative_path,
                content=image_bytes,
                metadata={
                    "artifact_type": "generated_image",
                    "provider": self.settings.provider,
                    "model": self.settings.model,
                    "profile_id": self.settings.profile_id,
                    "model_source": self.settings.source,
                    "prompt": request.prompt,
                    "operation": request.operation,
                    "input_attachment_ids": [
                        image.attachment_id for image in request.input_images if image.attachment_id
                    ],
                    "provider_metadata": dict(source.provider_metadata),
                },
            )
            assets.append(
                GeneratedAsset(
                    asset_id=str(record.get("artifact_id") or uuid4().hex),
                    path=str(record.get("path") or ""),
                    relative_path=str(record.get("relative_path") or relative_path),
                    mime_type=mime_type,
                    provider=self.settings.provider,
                    model=self.settings.model,
                    prompt=request.prompt,
                    input_attachment_ids=tuple(
                        image.attachment_id for image in request.input_images if image.attachment_id
                    ),
                    provider_request_id=_metadata_text(source.provider_metadata, "id", "request_id"),
                    provider_task_id=_metadata_text(source.provider_metadata, "task_id"),
                    metadata=dict(source.provider_metadata),
                )
            )
        return assets


def image_input_from_path(path: str | Path, *, attachment_id: str | None = None) -> ImageInput:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise ValueError(f"image input file does not exist: {path}")
    data = target.read_bytes()
    mime_type = mimetypes.guess_type(str(target))[0] or "image/png"
    if not mime_type.startswith("image/"):
        raise ValueError(f"image input is not an image: {path}")
    return ImageInput(
        source=str(target),
        mime_type=mime_type,
        data=data,
        filename=target.name,
        attachment_id=attachment_id,
    )


def _download(url: str | None, *, timeout: float | None) -> bytes:
    if not url:
        raise ValueError("generated image source has no bytes or url")
    response = httpx.get(url, timeout=float(timeout or 120.0), follow_redirects=True)
    response.raise_for_status()
    return response.content


def _mime_type_from_url(url: str | None) -> str | None:
    if not url:
        return None
    mime_type = mimetypes.guess_type(url.split("?", 1)[0])[0]
    return mime_type if mime_type and mime_type.startswith("image/") else None


def _extension_for_mime(mime_type: str) -> str:
    extension = mimetypes.guess_extension(mime_type) or ".png"
    return ".jpg" if extension == ".jpe" else extension


def _metadata_text(metadata: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
