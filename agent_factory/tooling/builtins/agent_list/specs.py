from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


AGENT_LIST_TOOL_ID = "agent_list"


def get_agent_list_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=AGENT_LIST_TOOL_ID,
            description=(
                "列出已经发布且可分配的 Agent，作为 agent_search 召回不足时的只读兜底。"
                "本工具不做语义排序、不制造 Agent；返回的 package_id 可用于人工核对，"
                "协作主 Agent 在创建任务前仍应优先使用 agent_search 的候选结果。"
            ),
            entrypoint="agent_factory.tooling.builtins.agent_list.tool:run",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 100,
                        "description": "最多返回多少个 Agent。",
                    }
                },
            },
            output_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "status": {"type": "string", "enum": ["completed"]},
                    "agents": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                    "count": {"type": "integer"},
                    "message": {"type": "string"},
                },
                "required": ["status", "agents", "count", "message"],
            },
            risk_level="low",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.tooling.builtins.agent_list.tool:evaluate_risk",
            ),
            concurrent=True,
        )
    ]
