from __future__ import annotations

from agent_factory.tooling.output_store import TOOL_OUTPUT_STORE_RESOURCE
from agent_factory.tooling.spec import ToolSpec


def get_tool_output_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="tool_output",
            description=(
                "Inspect full tool outputs stored outside model context. "
                "Use action=list first unless the current prompt explicitly lists a real output_id. "
                "Never invent output_id values; describe/read only accept ids returned by list or shown in an output_ref."
            ),
            entrypoint="agent_factory.tooling.output_store:run_tool_output",
            input_schema=_input_schema(),
            output_schema={"type": "object"},
            resources={TOOL_OUTPUT_STORE_RESOURCE: TOOL_OUTPUT_STORE_RESOURCE},
            risk_level="low",
            concurrent=True,
        )
    ]


def _input_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": ["list", "describe", "read"]},
            "output_id": {
                "type": "string",
                "description": "A real output_id returned by action=list or shown in a compacted tool observation output_ref.",
            },
            "path": {
                "type": "string",
                "description": "Optional dot path into the stored output, for example stdout or items.0.",
            },
            "offset": {"type": "integer", "minimum": 0, "default": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200000, "default": 12000},
        },
        "oneOf": [
            {"properties": {"action": {"const": "list"}}, "required": ["action"]},
            {"properties": {"action": {"const": "describe"}}, "required": ["action", "output_id"]},
            {"properties": {"action": {"const": "read"}}, "required": ["action", "output_id"]},
        ],
    }
