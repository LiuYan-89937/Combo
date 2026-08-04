from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


AGENT_DELEGATE_TOOL_ID = "agent_delegate"


def get_agent_delegate_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=AGENT_DELEGATE_TOOL_ID,
            description=(
                "将一个边界清晰的任务异步委派给已发布的子 Agent。"
                "先用 agent_search 获取真实 package_id，再用 action=start 启动。"
                "子 Agent 保留独立会话和工作区，完成后必须通过 deliver_result 正式交付；"
                "系统会把产物事务式传入当前工作区并自动唤醒你验收、整合和向用户汇报。"
                "启动成功后先向用户简要总结任务与分工，再结束当前回复并等待主动更新；"
                "不要查询任务进度。action=cancel 用于停止未完成任务。"
            ),
            entrypoint="agent_factory.tooling.builtins.agent_delegate.tool:run",
            input_schema=_input_schema(),
            output_schema={"type": "object", "additionalProperties": True},
            resources={
                "background_task_root": "background_task_root",
                "runtime_execution_config": "runtime_execution_config",
                "workdir_root": "workdir_root",
            },
            risk_level="medium",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.tooling.builtins.agent_delegate.tool:evaluate_risk"
            ),
            concurrent=False,
        )
    ]


def _input_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": ["start", "cancel"]},
            "package_id": {"type": "string", "minLength": 1},
            "task": {"type": "string", "minLength": 1},
            "acceptance_criteria": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "minItems": 1,
            },
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
            "task_id": {"type": "string", "minLength": 1},
            "reason": {"type": "string"},
        },
        "required": ["action"],
        "allOf": [
            {
                "if": {"properties": {"action": {"const": "start"}}, "required": ["action"]},
                "then": {"required": ["package_id", "task", "acceptance_criteria"]},
            },
            {
                "if": {"properties": {"action": {"const": "cancel"}}, "required": ["action"]},
                "then": {"required": ["task_id"]},
            },
        ],
    }
