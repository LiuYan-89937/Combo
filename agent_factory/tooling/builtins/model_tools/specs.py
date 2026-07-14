from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent_factory.tooling.spec import ToolSpec


MODEL_TOOL_RUNTIME_RESOURCE = "model_tool_runtime"


def get_model_tool_specs(runtime_tools: Mapping[str, Any] | None) -> list[ToolSpec]:
    specs: list[ToolSpec] = []
    for tool_id, runtime_tool in sorted((runtime_tools or {}).items()):
        capability = str(runtime_tool.get("capability") or "")
        if capability not in {"image_input", "audio_input"}:
            raise ValueError(f"unsupported local model tool capability: {capability}")
        specs.append(
            ToolSpec(
                id=tool_id,
                description=str(runtime_tool.get("description") or _description(capability)),
                entrypoint="agent_factory.tooling.builtins.model_tools.model_tool:run",
                input_schema=_input_schema(capability),
                output_schema=_output_schema(),
                resources={"model_tool": f"{MODEL_TOOL_RUNTIME_RESOURCE}.{tool_id}"},
                risk_level="low",
                concurrent=True,
                permission_scope="model",
            )
        )
    return specs


def _description(capability: str) -> str:
    if capability == "image_input":
        return "调用本地辅助视觉模型理解图片，并返回文本。"
    return "调用本地辅助音频模型理解音频，并返回文本。"


def _input_schema(capability: str) -> dict[str, Any]:
    if capability == "image_input":
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "prompt": {"type": "string"},
                "input_attachment_ids": {"type": "array", "items": {"type": "string"}},
                "input_paths": {"type": "array", "items": {"type": "string"}},
                "image_base64": {"type": "string"},
                "mime_type": {"type": "string"},
            },
            "required": ["prompt"],
            "anyOf": [
                {"required": ["input_attachment_ids"]},
                {"required": ["input_paths"]},
                {"required": ["image_base64"]},
            ],
        }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "prompt": {"type": "string"},
            "audio_base64": {"type": "string"},
            "mime_type": {"type": "string"},
            "language": {"type": "string"},
        },
        "required": ["prompt", "audio_base64"],
    }


def _output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "capability": {"type": "string"},
            "profile_id": {"type": "string"},
            "content": {"type": "string"},
            "artifacts": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "raw_content": {},
            "metadata": {"type": "object", "additionalProperties": True},
        },
        "required": ["capability", "profile_id", "content", "artifacts", "metadata"],
    }
