from __future__ import annotations

from combo.tooling.spec import ToolSpec


IMAGE_GENERATION_RUNTIME_RESOURCE = "image_generation_runtime"


def get_image_generation_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="generate_image",
            description=(
                "Generate image assets with the default image-generation model configured in the model pool. "
                "Use it for original visual material; generated files are saved in the current conversation workspace."
            ),
            entrypoint="combo.tooling.builtins.image_generation.tool:run",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "prompt": {"type": "string", "minLength": 1, "description": "Complete visual description."},
                    "operation": {
                        "type": "string",
                        "enum": ["text_to_image", "image_to_image", "edit"],
                        "default": "text_to_image",
                        "description": "Choose text_to_image without inputs, or image_to_image/edit with input_images.",
                    },
                    "input_images": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 8,
                        "description": "Workspace-relative source image paths for image-to-image, editing, or multiple references.",
                    },
                    "negative_prompt": {"type": "string"},
                    "size": {"type": "string", "description": "Provider-supported pixel size, for example 1024x1024."},
                    "aspect_ratio": {"type": "string", "description": "Provider-supported ratio, for example 16:9."},
                    "count": {"type": "integer", "minimum": 1, "maximum": 4, "default": 1},
                    "seed": {"type": "integer"},
                },
                "required": ["prompt"],
            },
            output_schema={"type": "object"},
            resources={IMAGE_GENERATION_RUNTIME_RESOURCE: IMAGE_GENERATION_RUNTIME_RESOURCE},
            risk_level="medium",
            concurrent=False,
            max_parallel_calls=1,
            effects=["write", "network", "external_side_effect"],
            system_available=True,
        )
    ]
