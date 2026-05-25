from __future__ import annotations

from agent_factory.tooling.output_store import TOOL_OUTPUT_STORE_RESOURCE
from agent_factory.tooling.spec import ToolSpec


def get_tool_output_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="tool_output",
            description=(
                "Read a full tool output by output_id when a prior tool observation says its output was compacted. "
                "Use describe for metadata and read for a selected range or nested dot path."
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
            "action": {"type": "string", "enum": ["describe", "read"]},
            "output_id": {
                "type": "string",
                "pattern": r"^toolout_[a-f0-9]{32}$",
                "description": "The output_id from a compacted tool observation.",
            },
            "path": {
                "type": "string",
                "description": "Optional dot path into the stored output, for example stdout or items.0.",
            },
            "offset": {"type": "integer", "minimum": 0, "default": 0},
            "limit": {"type": "integer", "minimum": 1, "maximum": 200000, "default": 12000},
        },
        "required": ["action", "output_id"],
    }
