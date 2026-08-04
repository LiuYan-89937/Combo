from __future__ import annotations

from agent_factory.knowledge_system.schema import KnowledgeToolInput
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


def get_knowledge_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="knowledge",
            description=(
                "查询和管理当前 Agent 挂载的私有知识。"
                "当问题涉及内部文档、项目事实、产品参数、业务规则、操作流程、代码规范、历史资料，"
                "或用户明确要求根据知识库、文档、规范回答时，必须调用本工具，不得只凭模型记忆作答。"
                "检索时先使用 search（默认 mode=auto），命中后按需使用 open/read 获取完整内容；"
                "无结果时如实说明，不得伪造知识库内容或声称已经查询。"
                "新增知识源必须先 prepare_source 预览，再 confirm_source 确认。"
                "添加当前会话附件或工作区文件时，source.path 使用工作区相对路径或 /workdir 逻辑路径，"
                "不要拼接宿主机安装目录。"
            ),
            entrypoint="agent_factory.knowledge_system.tools:run",
            input_schema=_input_schema(),
            output_schema={"type": "object"},
            resources={
                "knowledge_runtime": "knowledge_runtime",
                "workspace_root": "workspace_root",
            },
            risk_level="medium",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.knowledge_system.tools:evaluate_risk",
            ),
            concurrent=False,
        )
    ]


def _input_schema() -> dict:
    schema = KnowledgeToolInput.model_json_schema()
    schema["oneOf"] = [
        {"properties": {"action": {"enum": ["list_sources"]}}, "required": ["action"]},
        {
            "properties": {
                "action": {"enum": ["prepare_source", "confirm_source"]},
                "source": {"$ref": "#/$defs/KnowledgeSourceInput"},
            },
            "required": ["action", "source"],
        },
        {"properties": {"action": {"enum": ["describe_source", "reindex", "remove_source"]}}, "required": ["action", "source_id"]},
        {"properties": {"action": {"const": "list_documents"}}, "required": ["action"]},
        {"properties": {"action": {"const": "search"}}, "required": ["action", "query"]},
        {"properties": {"action": {"enum": ["open", "read"]}}, "required": ["action"]},
    ]
    return schema
