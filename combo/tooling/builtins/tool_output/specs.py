from __future__ import annotations

from combo.tooling.output_store import TOOL_OUTPUT_STORE_RESOURCE
from combo.tooling.spec import ToolSpec


def get_tool_output_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="tool_output",
            description=(
                "查看保存在模型上下文之外的完整工具输出。"
                "除非当前提示明确给出真实 output_id，否则先使用 action=list。"
                "不要编造 output_id；describe/read 只接受 list 返回或 output_ref 中展示的 ID。"
            ),
            entrypoint="combo.tooling.output_store:run_tool_output",
            input_schema=_input_schema(),
            output_schema={"type": "object"},
            resources={TOOL_OUTPUT_STORE_RESOURCE: TOOL_OUTPUT_STORE_RESOURCE},
            effects=["read"],
            read_only=True,
            system_available=True,
            risk_level="low",
            concurrent=True,
            max_parallel_calls=4,
            output_projection="passthrough",
        )
    ]


def _input_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": ["list", "describe", "read"], "description": "list 列出输出，describe 查看结构，read 分段读取内容。"},
            "output_id": {
                "type": "string",
                "description": "A real output_id returned by action=list or shown in a compacted tool observation output_ref.",
            },
            "path": {
                "type": "string",
                "description": "Optional dot path into the stored output, for example stdout or items.0.",
            },
            "offset": {"type": "integer", "minimum": 0, "default": 0, "description": "分段读取的起始字符偏移。"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200000, "default": 12000, "description": "本次最多读取的字符数。"},
        },
        "oneOf": [
            {"properties": {"action": {"const": "list", "description": "列出当前会话可读取的完整工具输出。"}}, "required": ["action"]},
            {"properties": {"action": {"const": "describe", "description": "查看指定输出的结构与大小。"}}, "required": ["action", "output_id"]},
            {"properties": {"action": {"const": "read", "description": "按路径和偏移分段读取指定输出。"}}, "required": ["action", "output_id"]},
        ],
    }
