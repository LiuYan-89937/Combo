from __future__ import annotations

from combo.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


SCHEDULER_RUNTIME_RESOURCE = "scheduler_runtime"
RUNTIME_IDENTITY_RESOURCE = "runtime_identity"


def get_scheduler_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="scheduler",
            description=(
                "Create and manage scheduled tasks bound to the main Agent's current workspace. "
                "Only the main Agent can use this control-plane tool."
            ),
            entrypoint="combo.tooling.builtins.scheduler.tool:run",
            input_schema=_input_schema(),
            output_schema={"type": "object"},
            resources={
                SCHEDULER_RUNTIME_RESOURCE: SCHEDULER_RUNTIME_RESOURCE,
                RUNTIME_IDENTITY_RESOURCE: RUNTIME_IDENTITY_RESOURCE,
            },
            risk_level="medium",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="combo.tooling.builtins.scheduler.tool:evaluate_risk",
            ),
            concurrent=False,
            max_parallel_calls=1,
            effects=["read", "write", "delete"],
            system_available=True,
        )
    ]


def _input_schema() -> dict:
    job_id = {"type": "string", "minLength": 1, "description": "调度任务列表返回的真实 job_id。"}
    return {
        "oneOf": [
            {
                "type": "object",
                "properties": {"action": {"const": "list", "description": "列出当前工作区的定时任务。"}},
                "required": ["action"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {"action": {"const": "describe", "description": "查看一个定时任务的完整配置。"}, "job_id": job_id},
                "required": ["action", "job_id"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "action": {"const": "create", "description": "在当前工作区创建一个定时主 Agent 任务。"},
                    "task_content": {"type": "string", "minLength": 1, "description": "触发时作为用户任务提交给主 Agent 的完整说明。"},
                    "schedule_type": {"type": "string", "enum": ["cron", "interval", "date"], "description": "cron、固定间隔或单次日期触发。"},
                    "schedule_expr": {"type": "string", "minLength": 1, "description": "与 schedule_type 对应的 cron、间隔或日期表达式。"},
                    "timezone": {"type": "string", "minLength": 1, "description": "解释计划时间使用的 IANA 时区。"},
                    "strategy": {"type": "string", "enum": ["react", "plan_and_execute"], "default": "react", "description": "触发任务使用的执行图策略。"},
                    "approval_policy": {"type": "string", "enum": ["ask", "auto", "always_approval"], "default": "ask", "description": "无人值守执行时采用的工具审批策略。"},
                },
                "required": ["action", "task_content", "schedule_type", "schedule_expr", "timezone"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["pause", "resume", "delete"], "description": "暂停、恢复或删除指定定时任务。"},
                    "job_id": job_id,
                },
                "required": ["action", "job_id"],
                "additionalProperties": False,
            },
        ]
    }
