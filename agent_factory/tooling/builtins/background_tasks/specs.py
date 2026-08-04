from __future__ import annotations

from agent_factory.tooling.spec import ToolSpec


BACKGROUND_TASKS_TOOL_ID = "background_tasks"


def get_background_tasks_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=BACKGROUND_TASKS_TOOL_ID,
            description=(
                "按需诊断或管理当前对话启动的制造、进化、单 Agent 委派和多 Agent 团队后台任务。"
                "action=list 返回任务摘要；action=get 返回指定任务的阶段、成员、子任务、活动、产物、待处理事项和错误。"
                "任务启动后运行时会自动等待并在整批任务结束时携带结果唤醒当前会话；"
                "不要用 list/get 轮询进度，仅在用户明确询问、取消任务或诊断异常时调用。"
            ),
            entrypoint="agent_factory.tooling.builtins.background_tasks.tool:run",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["list", "get", "cancel"]},
                    "task_id": {"type": "string", "minLength": 1},
                    "reason": {"type": "string"},
                },
                "required": ["action"],
                "allOf": [
                    {
                        "if": {
                            "properties": {"action": {"enum": ["get", "cancel"]}},
                            "required": ["action"]
                        },
                        "then": {"required": ["task_id"]},
                    }
                ],
            },
            output_schema={"type": "object", "additionalProperties": True},
            resources={
                "background_task_root": "background_task_root",
                "runtime_execution_config": "runtime_execution_config",
                "workdir_root": "workdir_root",
            },
            risk_level="low",
            concurrent=False,
        )
    ]
