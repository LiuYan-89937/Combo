from __future__ import annotations

from agent_factory.tooling.spec import ToolSpec


BACKGROUND_TASKS_TOOL_ID = "background_tasks"


def get_background_tasks_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=BACKGROUND_TASKS_TOOL_ID,
            description=(
                "统一查看当前对话启动的制造、进化、单 Agent 委派和多 Agent 团队后台任务。"
                "action=list 返回任务摘要；action=get 返回指定任务的阶段、成员、子任务、活动、产物、待处理事项和错误。"
                "任务状态会主动更新，除非用户明确询问，否则不要高频轮询。"
            ),
            entrypoint="agent_factory.tooling.builtins.background_tasks.tool:run",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["list", "get"]},
                    "background_task_id": {"type": "string", "minLength": 1},
                },
                "required": ["action"],
                "allOf": [
                    {
                        "if": {"properties": {"action": {"const": "get"}}, "required": ["action"]},
                        "then": {"required": ["background_task_id"]},
                    }
                ],
            },
            output_schema={"type": "object", "additionalProperties": True},
            resources={
                "collaboration_root": "collaboration_root",
                "runtime_execution_config": "runtime_execution_config",
                "workdir_root": "workdir_root",
            },
            risk_level="low",
            concurrent=False,
        )
    ]
