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
                "Invoke one exact Tool or MCP Tool returned by capability search. Do not call this gateway unless "
                "capability describe output for this same public name, kind, and MCP Server is already present in "
                "the current context. A search summary or another target's description is insufficient. Construct "
                "arguments strictly from that target's input schema, including exact names, required fields, and "
                "types; never guess parameters or probe them through validation failures. The selected target "
                "retains its own validation, approval, concurrency, timeout, resource, and output policies."
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
                        "description": "Arguments copied from the exact target input schema returned by capability describe.",
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
