from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


def get_knowledge_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="knowledge",
            description=(
                "管理和检索当前 Agent 显式挂载的知识源。"
                "已有知识使用 list/search/open/read；新增知识源必须先 prepare_source 预览，再 confirm_source 确认。"
            ),
            entrypoint="agent_factory.knowledge_system.tools:run",
            input_schema=_input_schema(),
            output_schema={"type": "object"},
            resources={"knowledge_runtime": "knowledge_runtime"},
            risk_level="medium",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.knowledge_system.tools:evaluate_risk",
            ),
            concurrent=False,
        )
    ]


def _input_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "list_sources",
                    "describe_source",
                    "prepare_source",
                    "confirm_source",
                    "list_documents",
                    "search",
                    "open",
                    "read",
                    "reindex",
                    "remove_source",
                ],
            },
            "source_id": {"type": "string"},
            "document_id": {"type": "string"},
            "chunk_id": {"type": "string"},
            "query": {"type": "string"},
            "mode": {"type": "string", "enum": ["auto", "keyword", "semantic", "hybrid", "readable"]},
            "top_k": {"type": "integer", "minimum": 1, "maximum": 100},
            "filters": {"type": "object", "additionalProperties": True},
            "include_content": {"type": "boolean"},
            "source": {
                "type": "object",
                "additionalProperties": True,
                "properties": {
                    "source_id": {"type": "string"},
                    "source_type": {
                        "type": "string",
                        "enum": [
                            "filesystem",
                            "codebase",
                            "web_snapshot",
                            "database",
                            "mcp",
                            "skill",
                            "artifact_report",
                            "manual_note",
                        ],
                    },
                    "display_name": {"type": "string"},
                    "mount_mode": {"type": "string", "enum": ["index_only", "rag"]},
                    "uri": {"type": "string"},
                    "path": {"type": "string"},
                    "url": {"type": "string"},
                    "metadata": {"type": "object", "additionalProperties": True},
                },
            },
        },
        "required": ["action"],
        "oneOf": [
            {"properties": {"action": {"enum": ["list_sources"]}}, "required": ["action"]},
            {"properties": {"action": {"enum": ["prepare_source", "confirm_source"]}}, "required": ["action", "source"]},
            {"properties": {"action": {"enum": ["describe_source", "reindex", "remove_source"]}}, "required": ["action", "source_id"]},
            {"properties": {"action": {"const": "list_documents"}}, "required": ["action"]},
            {"properties": {"action": {"const": "search"}}, "required": ["action", "query"]},
            {"properties": {"action": {"enum": ["open", "read"]}}, "required": ["action"]},
        ],
    }
