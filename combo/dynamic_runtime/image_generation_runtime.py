from __future__ import annotations

from pathlib import Path
from typing import Any

from combo.artifact_system import ArtifactStore
from combo.model_pool import ModelPoolStore, ModelToolBinding
from combo.model_pool.resolver import resolve_image_generation_binding
from combo.models.image_generation import ImageGenerationRequest
from combo.models.image_generation.service import image_input_from_path


class ImageGenerationRuntime:
    """Workspace-scoped facade for the image model bound in the model pool."""

    def __init__(self, workspace_root: Path) -> None:
        self._workspace_root = workspace_root.expanduser().resolve()

    def generate(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        store = ModelPoolStore(setup=False)
        profile_id = store.image_generation_binding()
        if not profile_id:
            raise RuntimeError("default image generation model is not configured")
        artifact_store = ArtifactStore(root=self._workspace_root, allowed_kinds=("artifact",))
        resolved = resolve_image_generation_binding(
            ModelToolBinding(
                profile_id=profile_id,
                capability="image_output",
                selection_source="manual",
                reason="Generate an image for the current conversation",
            ),
            artifact_store=artifact_store,
            store=store,
        )
        if resolved is None:
            raise RuntimeError("default image generation model is unavailable")
        operation = str(arguments.get("operation") or "text_to_image")
        if operation not in {"text_to_image", "image_to_image", "edit"}:
            raise ValueError("operation must be text_to_image, image_to_image, or edit")
        input_images = tuple(
            image_input_from_path(self._resolve_workspace_path(value))
            for value in _string_list(arguments.get("input_images"))
        )
        if operation != "text_to_image" and not input_images:
            raise ValueError(f"{operation} requires at least one input_images path")
        request = ImageGenerationRequest(
            operation=operation,
            prompt=_required(arguments, "prompt"),
            input_images=input_images,
            size=_optional(arguments, "size"),
            aspect_ratio=_optional(arguments, "aspect_ratio"),
            count=int(arguments.get("count") or 1),
            seed=_optional_int(arguments, "seed"),
            negative_prompt=_optional(arguments, "negative_prompt"),
        )
        return [asset.model_payload() for asset in resolved.service.generate(request)]

    def _resolve_workspace_path(self, value: str) -> Path:
        candidate = (self._workspace_root / value).resolve()
        if candidate != self._workspace_root and self._workspace_root not in candidate.parents:
            raise ValueError("input image path escapes the conversation workspace")
        return candidate


def _required(arguments: dict[str, Any], name: str) -> str:
    value = str(arguments.get(name) or "").strip()
    if not value:
        raise ValueError(f"{name} must not be empty")
    return value


def _optional(arguments: dict[str, Any], name: str) -> str | None:
    value = str(arguments.get(name) or "").strip()
    return value or None


def _optional_int(arguments: dict[str, Any], name: str) -> int | None:
    value = arguments.get(name)
    return int(value) if value is not None else None


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("input_images must be an array of workspace-relative paths")
    return [str(item).strip() for item in value if str(item).strip()]
