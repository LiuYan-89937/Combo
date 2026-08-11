from __future__ import annotations

from agent_factory.tooling.skillhub.search_query import (
    SKILLHUB_SEARCH_QUERY_MAX_CHARS,
    SKILLHUB_SEARCH_QUERY_PATTERN,
)
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


SKILLHUB_RUNTIME_RESOURCE = "skillhub_runtime"
RUNTIME_IDENTITY_RESOURCE = "runtime_identity"


def get_skillhub_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="skillhub",
            description=(
                "Search SkillHub and install or remove Skills in the unified Skill pool. "
                "Only the main Agent can use this capability-management tool."
            ),
            entrypoint="agent_factory.tooling.builtins.skillhub.tool:run",
            input_schema=_input_schema(),
            output_schema={"type": "object"},
            resources={
                SKILLHUB_RUNTIME_RESOURCE: SKILLHUB_RUNTIME_RESOURCE,
                RUNTIME_IDENTITY_RESOURCE: RUNTIME_IDENTITY_RESOURCE,
            },
            risk_level="high",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.tooling.builtins.skillhub.tool:evaluate_risk",
            ),
            concurrent=False,
            max_parallel_calls=1,
            effects=["read", "write", "delete", "network", "process", "external_side_effect"],
            system_available=True,
        )
    ]


def _input_schema() -> dict:
    return {
        "oneOf": [
            {
                "type": "object",
                "properties": {"action": {"const": "status", "description": "检查 SkillHub CLI 是否可用。"}},
                "required": ["action"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "action": {"const": "search", "description": "在 SkillHub 中搜索可安装 Skill。"},
                    "query": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": SKILLHUB_SEARCH_QUERY_MAX_CHARS,
                        "pattern": SKILLHUB_SEARCH_QUERY_PATTERN,
                        "description": "用于 SkillHub 搜索的简短能力关键词。",
                    },
                },
                "required": ["action", "query"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["install", "remove"], "description": "安装 SkillHub Skill 或从统一 Skill 池移除它。"},
                    "skill": {"type": "string", "minLength": 1, "description": "搜索结果返回的 install_name 或已安装 Skill 标识。"},
                },
                "required": ["action", "skill"],
                "additionalProperties": False,
            },
        ]
    }
