from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


DELIVER_RESULT_TOOL_ID = "deliver_result"


def get_deliver_result_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=DELIVER_RESULT_TOOL_ID,
            description=(
                "正式向父 Agent 交付当前委派任务。仅在被父 Agent 委派的子运行中可用。"
                "任务结束前调用一次，提交真实状态、简明总结和当前工作区内需要交付的文件或目录。"
                "系统会验证来源、事务式传输产物并把结构化报告交给父 Agent；"
                "普通文字回复不等于正式交付。"
            ),
            entrypoint="agent_factory.tooling.builtins.deliver_result.tool:run",
            input_schema=_input_schema(),
            output_schema={"type": "object", "additionalProperties": True},
            resources={
                "background_task_root": "background_task_root",
                "runtime_execution_config": "runtime_execution_config",
                "workdir_root": "workdir_root",
            },
            risk_level="low",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.tooling.builtins.deliver_result.tool:evaluate_risk"
            ),
            concurrent=False,
        )
    ]


def _input_schema() -> dict:
    text_array = {"type": "array", "items": {"type": "string", "minLength": 1}}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "status": {"type": "string", "enum": ["completed", "partial", "blocked", "failed"]},
            "summary": {"type": "string", "minLength": 1},
            "artifacts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "path": {"type": "string", "minLength": 1},
                        "description": {"type": "string", "minLength": 1},
                    },
                    "required": ["path", "description"],
                },
            },
            "key_findings": text_array,
            "remaining_issues": text_array,
            "recommended_next_actions": text_array,
        },
        "required": ["status", "summary"],
    }
