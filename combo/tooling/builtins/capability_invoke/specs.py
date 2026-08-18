from __future__ import annotations

from combo.tooling.builtins.capability_invoke.tool import (
    CAPABILITY_INVOCATION_RUNTIME_RESOURCE,
)
from combo.tooling.spec import ToolSpec


def get_capability_invoke_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="capability_invoke",
            description=(
                "Invoke one exact Tool or MCP Tool returned by capability search. Search the top-level "
                "catalog first, search inside an MCP Server when needed, and inspect the exact target schema "
                "before calling. The selected target retains its own validation, approval, concurrency, "
                "timeout, resource, and output policies."
            ),
            entrypoint="combo.tooling.builtins.capability_invoke.tool:run",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "kind": {"type": "string", "enum": ["tool", "mcp_tool"]},
                    "name": {"type": "string", "minLength": 1},
                    "server_name": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Required for MCP Tool targets.",
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Arguments validated by the selected target Tool schema.",
                    },
                },
                "required": ["kind", "name", "arguments"],
                "allOf": [
                    {
                        "if": {"properties": {"kind": {"const": "mcp_tool"}}, "required": ["kind"]},
                        "then": {"required": ["server_name"]},
                    }
                ],
            },
            output_schema={"type": "object"},
            resources={
                CAPABILITY_INVOCATION_RUNTIME_RESOURCE: CAPABILITY_INVOCATION_RUNTIME_RESOURCE,
            },
            risk_level="high",
            concurrent=True,
            max_parallel_calls=4,
            effects=["external_side_effect"],
            read_only=False,
            system_available=True,
            execution_mode="delegated",
        )
    ]
