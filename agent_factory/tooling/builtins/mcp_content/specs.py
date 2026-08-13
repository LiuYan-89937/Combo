from __future__ import annotations

from agent_factory.tooling.spec import ToolSpec


MCP_CONTENT_RUNTIME_RESOURCE = "mcp_content_runtime"


def get_mcp_content_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="mcp_content",
            description=(
                "Search and load Resources or Prompts exposed by enabled MCP servers. MCP content is not "
                "injected automatically: search the short directory for the current task, then read an exact "
                "resource URI or load an exact prompt with its declared arguments."
            ),
            entrypoint="agent_factory.tooling.builtins.mcp_content.tool:run",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["search", "list", "read_resource", "get_prompt"]},
                    "query": {"type": "string", "description": "Task-oriented query for MCP Resources and Prompts."},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                    "server_id": {"type": "string", "description": "Exact server_id returned by search or list."},
                    "uri": {"type": "string", "description": "Exact resource URI returned by search or list."},
                    "name": {"type": "string", "description": "Exact prompt name returned by search or list."},
                    "arguments": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                        "description": "Prompt arguments declared by the MCP server.",
                    },
                },
                "required": ["action"],
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
