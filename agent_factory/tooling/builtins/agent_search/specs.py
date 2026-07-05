from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


AGENT_SEARCH_TOOL_ID = "agent_search"


def get_agent_search_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=AGENT_SEARCH_TOOL_ID,
            description=(
                "按任务需求检索已经发布的可用子 Agent。"
                "在多 Agent 协作中，创建子任务前必须先用本工具查找候选 Agent；"
                "只能使用返回 candidates 中的 package_id 分配任务。"
                "本工具只查询现有 Agent，不制造 Agent；当 status 为 no_suitable_agent，"
                "可根据 manufacturing_recommendation 由主 Agent 另行委托制造 Agent。"
            ),
            entrypoint="agent_factory.tooling.builtins.agent_search.tool:run",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "自然语言任务需求或子任务描述。不要拆成能力标签。",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                    },
                },
                "required": ["query"],
            },
            output_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "status": {"type": "string", "enum": ["matched", "no_suitable_agent"]},
                    "query": {"type": "string"},
                    "candidates": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                    "manufacturing_recommendation": {"type": "object", "additionalProperties": True},
                    "embedding_used": {"type": "boolean"},
                    "message": {"type": "string"},
                },
                "required": ["status", "query", "candidates", "embedding_used", "message"],
            },
            risk_level="low",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.tooling.builtins.agent_search.tool:evaluate_risk",
            ),
            concurrent=True,
        )
    ]
