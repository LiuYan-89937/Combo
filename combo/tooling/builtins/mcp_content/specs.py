from __future__ import annotations

from combo.tooling.spec import ToolSpec


MCP_CONTENT_RUNTIME_RESOURCE = "mcp_content_runtime"


def get_mcp_content_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="mcp_content",
            description=(
                "Load an exact Resource or Prompt returned by the capability catalog for an enabled MCP "
                "server. MCP content is never injected automatically. Search the selected server's second-level "
                "catalog first, then call capability describe for this exact Resource or Prompt before use. Read "
                "only the returned URI or expand the Prompt with exactly its declared arguments; another MCP "
                "object's description is not interchangeable."
            ),
            entrypoint="combo.tooling.builtins.mcp_content.tool:run",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["read_resource", "get_prompt"]},
                    "server_name": {"type": "string", "description": "Exact public MCP Server name returned by capability search."},
                    "uri": {"type": "string", "description": "Exact Resource URI returned by capability describe."},
                    "name": {"type": "string", "description": "Exact Prompt name returned by capability describe."},
                    "arguments": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "Prompt arguments declared by the MCP server.",
                    },
                },
                "required": ["action"],
                "allOf": [
                    {
                        "if": {"properties": {"action": {"const": "read_resource"}}, "required": ["action"]},
                        "then": {"required": ["server_name", "uri"]},
                    },
                    {
                        "if": {"properties": {"action": {"const": "get_prompt"}}, "required": ["action"]},
                        "then": {"required": ["server_name", "name"]},
                    },
                ],
            },
            output_schema={"type": "object"},
            resources={MCP_CONTENT_RUNTIME_RESOURCE: MCP_CONTENT_RUNTIME_RESOURCE},
            risk_level="low",
            concurrent=True,
            max_parallel_calls=4,
            effects=["read", "network"],
            read_only=False,
            system_available=True,
        )
    ]
