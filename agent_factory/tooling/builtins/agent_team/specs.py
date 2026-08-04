from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


AGENT_TEAM_TOOL_ID = "agent_team"


def get_agent_team_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=AGENT_TEAM_TOOL_ID,
            description=(
                "将一个目标拆给多个已发布 Agent 并行或按依赖顺序执行。"
                "每个成员保留独立会话和工作区，并通过 deliver_result 把结果送回当前工作区。"
                "先用 agent_search 确认每个 package_id；启动后不要轮询，成员状态变化会主动唤醒当前会话。"
            ),
            entrypoint="agent_factory.tooling.builtins.agent_team.tool:run",
            input_schema=_input_schema(),
            output_schema={"type": "object", "additionalProperties": True},
            resources={
                "background_task_root": "background_task_root",
                "runtime_execution_config": "runtime_execution_config",
                "workdir_root": "workdir_root",
            },
            risk_level="medium",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.tooling.builtins.agent_team.tool:evaluate_risk"
            ),
            concurrent=False,
        )
    ]


def _input_schema() -> dict:
    task = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "task_key": {"type": "string", "minLength": 1},
            "package_id": {"type": "string", "minLength": 1},
            "task": {"type": "string", "minLength": 1},
            "acceptance_criteria": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,
            },
            "depends_on": {"type": "array", "items": {"type": "string", "minLength": 1}},
            "expected_artifacts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "description": {"type": "string", "minLength": 1},
                        "suggested_name": {"type": "string", "minLength": 1},
                    },
                    "required": ["description"],
                },
            },
            "context": {"type": "object", "additionalProperties": True},
        },
        "required": ["task_key", "package_id", "task", "acceptance_criteria"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": ["start", "cancel"]},
            "title": {"type": "string", "minLength": 1},
            "tasks": {"type": "array", "items": task, "minItems": 2, "maxItems": 12},
            "task_ids": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1
            },
            "reason": {"type": "string"},
        },
        "required": ["action"],
        "allOf": [
            {
                "if": {"properties": {"action": {"const": "start"}}, "required": ["action"]},
                "then": {"required": ["title", "tasks"]},
            },
            {
                "if": {"properties": {"action": {"const": "cancel"}}, "required": ["action"]},
                "then": {"required": ["task_ids"]},
            },
        ],
    }
