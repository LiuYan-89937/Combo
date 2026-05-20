from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


def get_scheduler_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="scheduler",
            description=(
                "Create, inspect, pause, resume, delete, or run scheduled graph/script/tool jobs. "
                "Scheduled scripts and tool calls execute through the AgentFactory tool gateway."
            ),
            entrypoint="agent_factory.scheduler_system.tools:run",
            input_schema=_input_schema(),
            output_schema={"type": "object"},
            resources={"scheduler_runtime": "scheduler_runtime"},
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
                "additionalProperties": True,
                "properties": {
                    "job_id": {"type": "string"},
                    "enabled": {"type": "boolean"},
                    "schedule_type": {"type": "string", "enum": ["cron", "interval", "date"]},
                    "schedule_expr": {"type": "string"},
                    "timezone": {"type": "string"},
                    "target": {
                        "type": "object",
                        "additionalProperties": True,
                        "properties": {
                            "target_type": {"type": "string", "enum": ["graph_run", "script_run", "tool_call"]},
                            "payload": {"type": "object"},
                        },
                        "required": ["target_type", "payload"],
                    },
                    "concurrency_policy": {"type": "string", "enum": ["skip", "queue", "replace"]},
                    "max_concurrent_runs": {"type": "integer", "minimum": 1},
                    "timeout_seconds": {"type": "integer", "minimum": 1},
                    "retry_policy": {"type": "object"},
                    "unattended_policy": {
                        "type": "string",
                        "enum": ["deny_if_approval_required", "pause_and_wait_for_user", "allow_preapproved_only"],
                    },
                },
                "required": ["schedule_type", "schedule_expr", "target"],
            },
        },
        "required": ["action"],
        "oneOf": [
            {"properties": {"action": {"const": "create"}}, "required": ["action", "job"]},
            {"properties": {"action": {"const": "list"}}, "required": ["action"]},
            {"properties": {"action": {"enum": ["describe", "pause", "resume", "delete", "run_now"]}}, "required": ["action", "job_id"]},
        ],
    }
