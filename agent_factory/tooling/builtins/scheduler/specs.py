from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


def get_scheduler_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="scheduler",
            description=(
                "创建、查看、暂停、恢复、删除或立即运行定时任务。"
                "定时脚本和工具调用会通过 AgentFactory 工具网关执行。"
                "创建任务时请填写 job.task_content，记录用户的自然语言任务意图，便于完成后统一总结反馈。"
            ),
            entrypoint="agent_factory.scheduler_system.tools:run",
            input_schema=_input_schema(),
            output_schema={"type": "object"},
            resources={
                "scheduler_runtime": "scheduler_runtime",
                "runtime_execution_config": "runtime_execution_config",
            },
            risk_level="medium",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.scheduler_system.tools:evaluate_risk",
            ),
            concurrent=False,
        )
    ]


def _input_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "list", "describe", "pause", "resume", "delete", "run_now"],
            },
            "job_id": {"type": "string"},
            "job": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "job_id": {"type": "string"},
                    "enabled": {"type": "boolean"},
                    "task_content": {
                        "type": "string",
                        "description": "用户原始定时任务意图，用于任务完成事件总结。",
                    },
                    "schedule_type": {
                        "type": "string",
                        "enum": ["cron", "interval", "date"],
                        "description": "cron 使用五段 crontab；interval 使用秒数；date 使用 ISO datetime。",
                    },
                    "schedule_expr": {
                        "type": "string",
                        "description": (
                            "调度表达式。cron: 五段 crontab；interval: 正整数秒或 seconds=<正整数>；"
                            "date: ISO datetime。不要使用 minutes=、hours= 等命名单位。"
                        ),
                    },
                    "timezone": {"type": "string"},
                    "feedback": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "enabled": {"type": "boolean"},
                            "mode": {"type": "string", "enum": ["llm_summary"]},
                        },
                    },
                    "target": _target_schema(),
                    "concurrency_policy": {"type": "string", "enum": ["skip", "queue", "replace"]},
                    "max_concurrent_runs": {"type": "integer", "minimum": 1},
                    "timeout_seconds": {"type": "integer", "minimum": 1},
                    "retry_policy": {"type": "object"},
                    "failure_policy": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "enabled": {"type": "boolean"},
                            "max_consecutive_failures": {"type": "integer", "minimum": 1},
                            "action": {"type": "string", "enum": ["pause"]},
                        },
                        "description": "失败治理策略。默认连续失败达到阈值后自动暂停任务。",
                    },
                    "unattended_policy": {
                        "type": "string",
                        "enum": ["deny_if_approval_required", "pause_and_wait_for_user", "allow_preapproved_only"],
                    },
                },
                "required": ["schedule_type", "schedule_expr", "target"],
                "allOf": [_interval_schedule_expr_rule()],
            },
        },
        "required": ["action"],
        "oneOf": [
            {"properties": {"action": {"const": "create"}}, "required": ["action", "job"]},
            {"properties": {"action": {"const": "list"}}, "required": ["action"]},
            {"properties": {"action": {"enum": ["describe", "pause", "resume", "delete", "run_now"]}}, "required": ["action", "job_id"]},
        ],
    }


def _interval_schedule_expr_rule() -> dict:
    return {
        "if": {
            "properties": {"schedule_type": {"const": "interval"}},
            "required": ["schedule_type"],
        },
        "then": {
            "properties": {
                "schedule_expr": {
                    "pattern": r"^(seconds=)?[1-9][0-9]*$",
                    "description": "interval 调度只接受正整数秒，或 seconds=<正整数>。",
                }
            }
        },
    }


def _target_schema() -> dict:
    return {
        "oneOf": [
            _graph_run_target_schema(),
            _script_run_target_schema(),
            _tool_call_target_schema(),
        ]
    }


def _graph_run_target_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "target_type": {"const": "graph_run"},
            "payload": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "message": {
                        "type": "string",
                        "minLength": 1,
                        "description": "定时触发时输入给 Agent Graph 的用户消息。",
                    },
                },
                "required": ["message"],
            },
        },
        "required": ["target_type", "payload"],
    }


def _script_run_target_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "target_type": {"const": "script_run"},
            "payload": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "command": {
                        "type": "string",
                        "minLength": 1,
                        "description": "交给当前平台 shell 工具执行的命令文本。",
                    },
                    "cwd": {"type": "string"},
                    "mode": {"type": "string", "enum": ["foreground", "background"]},
                    "wait_seconds": {"type": "integer", "minimum": 0, "maximum": 86400},
                    "max_output_chars": {"type": "integer", "minimum": 1, "maximum": 200000},
                },
                "required": ["command"],
            },
        },
        "required": ["target_type", "payload"],
    }


def _tool_call_target_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "target_type": {"const": "tool_call"},
            "payload": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "tool_id": {"type": "string", "minLength": 1},
                    "arguments": {
                        "type": "object",
                        "additionalProperties": True,
                        "description": "传递给目标工具的参数对象。",
                    },
                },
                "required": ["tool_id"],
            },
        },
        "required": ["target_type", "payload"],
    }
