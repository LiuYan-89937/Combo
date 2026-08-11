from __future__ import annotations

from agent_factory.tooling.builtins.capability.tool import CAPABILITY_CATALOG_RESOURCE
from agent_factory.tooling.spec import ToolSpec


def get_capability_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="capability",
            description=(
                "Search or list the active Tool, MCP, and Skill catalog before delegation. Returns only "
                "public capability names, kinds, and descriptions. Pass the selected names to delegate; "
                "delegate performs validation, dependency closure, and snapshot assembly internally."
            ),
            entrypoint="agent_factory.tooling.builtins.capability.tool:run",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["search", "list_active"],
                    },
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
                },
                "required": ["action"],
            },
            output_schema={"type": "object"},
            resources={CAPABILITY_CATALOG_RESOURCE: CAPABILITY_CATALOG_RESOURCE},
            risk_level="low",
            concurrent=True,
            max_parallel_calls=4,
            effects=["read"],
            read_only=True,
            system_available=True,
        )
    ]
