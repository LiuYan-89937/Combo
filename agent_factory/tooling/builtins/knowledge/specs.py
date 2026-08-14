from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


KNOWLEDGE_RUNTIME_RESOURCE = "knowledge_runtime"
RUNTIME_IDENTITY_RESOURCE = "runtime_identity"


def get_knowledge_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="knowledge",
            description=(
                "Search, inspect, add, and remove sources in the shared knowledge base. "
                "Use search before answering from internal documents. Only the main Agent can use this "
                "control-plane tool."
            ),
            entrypoint="agent_factory.tooling.builtins.knowledge.tool:run",
            input_schema=_input_schema(),
            output_schema={"type": "object"},
            resources={
                KNOWLEDGE_RUNTIME_RESOURCE: KNOWLEDGE_RUNTIME_RESOURCE,
                RUNTIME_IDENTITY_RESOURCE: RUNTIME_IDENTITY_RESOURCE,
            },
            risk_level="medium",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.tooling.builtins.knowledge.tool:evaluate_risk",
            ),
            concurrent=False,
            max_parallel_calls=1,
            effects=["read", "write", "delete"],
            system_available=True,
        )
    ]


def _input_schema() -> dict:
    return {
        "oneOf": [
            {
                "type": "object",
                "properties": {"action": {"const": "list_sources", "description": "列出共享知识库中的知识源。"}},
                "required": ["action"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "action": {"const": "search", "description": "检索共享知识库中的相关文档。"},
                    "query": {"type": "string", "minLength": 1, "description": "需要从内部资料中查找的问题或主题。"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50, "description": "可选；覆盖设置中的最终返回数量，但不会超过全局上限。"},
                },
                "required": ["action", "query"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "action": {"const": "list_documents", "description": "列出一个知识源中的文档。"},
                    "source_id": {"type": "string", "minLength": 1, "description": "list_sources 返回的真实知识源 ID。"},
                },
                "required": ["action", "source_id"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "action": {"const": "read", "description": "读取指定知识文档的正文。"},
                    "document_id": {"type": "string", "minLength": 1, "description": "搜索或文档列表返回的真实文档 ID。"},
                },
                "required": ["action", "document_id"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "action": {"const": "add_text_source", "description": "把一段用户授权文本添加为共享知识源。"},
                    "display_name": {"type": "string", "minLength": 1, "description": "知识源在管理页面显示的名称。"},
                    "content": {"type": "string", "minLength": 1, "description": "需要保存和建立索引的文本正文。"},
                    "mime_type": {"type": "string", "default": "text/plain", "description": "正文媒体类型，例如 text/plain 或 text/markdown。"},
                },
                "required": ["action", "display_name", "content"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "action": {"const": "remove_source", "description": "删除知识源及其关联文档。"},
                    "source_id": {"type": "string", "minLength": 1, "description": "要删除的真实知识源 ID。"},
                },
                "required": ["action", "source_id"],
                "additionalProperties": False,
            },
        ]
    }
