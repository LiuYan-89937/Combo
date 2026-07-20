from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agent_factory.tooling.spec import ToolSpec


MODEL_TOOL_RUNTIME_RESOURCE = "model_tool_runtime"


def get_model_tool_specs(runtime_tools: Mapping[str, Any] | None) -> list[ToolSpec]:
    specs: list[ToolSpec] = []
    for tool_id, runtime_tool in sorted((runtime_tools or {}).items()):
        capability = str(runtime_tool.get("capability") or "")
        if capability not in {"image_input", "image_output", "image_edit", "audio_input"}:
            raise ValueError(f"unsupported local model tool capability: {capability}")
        tool_resources = {"model_tool": f"{MODEL_TOOL_RUNTIME_RESOURCE}.{tool_id}"}
        if capability in {"image_output", "image_edit"}:
            tool_resources["workspace_root"] = "workspace_root"
        specs.append(
            ToolSpec(
                id=tool_id,
                description=str(runtime_tool.get("description") or _description(capability)),
                entrypoint="agent_factory.tooling.builtins.model_tools.model_tool:run",
                input_schema=_input_schema(capability),
                output_schema=_output_schema(capability),
                resources=tool_resources,
                risk_level="low",
                concurrent=True,
                permission_scope="model",
            )
        )
    return specs


def _description(capability: str) -> str:
    if capability == "image_output":
        return "调用已配置的本地生图模型，根据文本需求生成图片并保存到当前 Workspace。"
    if capability == "image_edit":
        return "调用已配置的本地生图模型编辑图片并保存到当前 Workspace。"
    if capability == "image_input":
        return "调用本地辅助视觉模型理解图片，并返回文本。"
    return "调用本地辅助音频模型理解音频，并返回文本。"


def _input_schema(capability: str) -> dict[str, Any]:
    if capability == "image_output":
        return {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "prompt": {"type": "string"},
                "size": {"type": "string", "pattern": "^[0-9]+x[0-9]+$"},
                "count": {"type": "integer", "minimum": 1, "maximum": 1},
                "seed": {"type": "integer"},
                "negative_prompt": {"type": "string"},
                "provider_options": {"type": "object", "additionalProperties": True},
            },
            "required": ["prompt"],
        }
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


def _output_schema(capability: str) -> dict[str, Any]:
    if capability in {"image_output", "image_edit"}:
        return {
            "type": "object",
            "additionalProperties": True,
            "properties": {
                "capability": {"type": "string"},
                "profile_id": {"type": "string"},
                "assets": {"type": "array", "items": {"type": "object", "additionalProperties": True}, "minItems": 1},
                "metadata": {"type": "object", "additionalProperties": True},
            },
            "required": ["capability", "profile_id", "assets", "metadata"],
        }
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
