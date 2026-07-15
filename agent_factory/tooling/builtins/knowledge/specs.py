from __future__ import annotations

from agent_factory.knowledge_system.prompting import KNOWLEDGE_TOOL_ID
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


def get_knowledge_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=KNOWLEDGE_TOOL_ID,
            description=(
                "查询和管理当前 Agent 挂载的私有知识。"
                "当用户问题涉及内部文档、项目内容、业务规则、产品参数、代码规范、历史资料，"
                "或用户明确要求根据知识库回答时，必须调用本工具，不得仅凭模型记忆回答。"
                "推荐先用 search 进行 auto 或 hybrid 检索，再对相关结果使用 open/read 获取完整内容，"
                "根据检索结果回答并标明来源；没有结果时如实说明。"
                "用户询问有哪些资料，或不知道应查询哪个知识源时使用 list_sources。"
                "未经实际检索，不得声称“根据知识库”。"
                "新增知识源必须先 prepare_source 预览，再 confirm_source 确认。"
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
                "description": "search 是默认检索入口；open/read 用于读取命中内容；list_sources 用于查看可用资料。",
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
            "mode": {
                "type": "string",
                "enum": ["auto", "keyword", "semantic", "hybrid", "readable"],
                "default": "auto",
                "description": "search 默认使用 auto；需要同时结合关键词与语义检索时使用 hybrid。",
            },
            "top_k": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "default": 5,
                "description": "search 默认返回 5 个结果。",
            },
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
