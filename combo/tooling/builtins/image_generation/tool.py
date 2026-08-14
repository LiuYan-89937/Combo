from __future__ import annotations

from typing import Any

from combo.dynamic_runtime.image_generation_runtime import ImageGenerationRuntime
from combo.tooling.builtins.image_generation.specs import IMAGE_GENERATION_RUNTIME_RESOURCE
from combo.tooling.envelope import tool_envelope


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    runtime = resources.get(IMAGE_GENERATION_RUNTIME_RESOURCE)
    if not isinstance(runtime, ImageGenerationRuntime):
        raise RuntimeError("image generation runtime is not configured")
    assets = runtime.generate(arguments)
    output: dict[str, Any] = {"assets": assets}
    if assets:
        output["model_image"] = {
            "path": assets[0]["path"],
            "mime_type": assets[0]["mime_type"],
        }
    return tool_envelope(output, summary=f"Generated {len(assets)} image asset(s)")
