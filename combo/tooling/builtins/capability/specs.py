from __future__ import annotations

from combo.tooling.builtins.capability.tool import CAPABILITY_CATALOG_RESOURCE
from combo.tooling.spec import ToolSpec


def get_capability_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="capability",
            description=(
                "Search the active Tool, MCP Server, and Skill catalog on demand. Use search for the top-level "
                "catalog. When an MCP Server is relevant, use search_mcp with that server name to search its "
                "Tool, Resource, Resource Template, and Prompt directory. Use describe only for an exact result "
                "before invoking or loading it. Results expose public names rather than internal runtime IDs."
            ),
            entrypoint="combo.tooling.builtins.capability.tool:run",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["search", "search_mcp", "describe", "list_active"],
                        "description": "检索一级能力、检索指定 MCP 的二级目录、查看准确描述，或列出一级能力。",
                    },
                    "query": {"type": "string", "description": "用自然语言描述需要完成的任务或所需能力。"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10, "description": "最多返回的能力数量。"},
                    "server_name": {
                        "type": "string",
                        "description": "一级结果中的 MCP Server 名称；用于限定二级检索或描述范围。",
                    },
                    "name": {"type": "string", "description": "describe 使用的准确公开名称。"},
                    "kind": {
                        "type": "string",
                        "enum": ["tool", "skill", "mcp_server", "mcp_tool", "mcp_resource", "mcp_resource_template", "mcp_prompt"],
                        "description": "describe 的可选类型限定。",
                    },
                    "kinds": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["mcp_tool", "mcp_resource", "mcp_resource_template", "mcp_prompt"],
                        },
                        "uniqueItems": True,
                        "description": "search_mcp 的可选二级对象类型过滤。",
                    },
                },
                "required": ["action"],
                "allOf": [
                    {
                        "if": {"properties": {"action": {"const": "search"}}, "required": ["action"]},
                        "then": {"required": ["query"]},
                    },
                    {
                        "if": {"properties": {"action": {"const": "search_mcp"}}, "required": ["action"]},
                        "then": {"required": ["server_name", "query"]},
                    },
                    {
                        "if": {"properties": {"action": {"const": "describe"}}, "required": ["action"]},
                        "then": {"required": ["name"]},
                    },
                ],
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
