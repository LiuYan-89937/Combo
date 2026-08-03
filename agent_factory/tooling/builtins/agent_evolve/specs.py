from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


AGENT_EVOLVE_TOOL_ID = "agent_evolve"


def get_agent_evolve_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=AGENT_EVOLVE_TOOL_ID,
            description=(
                "异步进化一个已发布 Agent。action=start 启动后不要轮询，进化完成、失败或需要补充信息时会主动回到当前会话。"
                "action=respond 用于回答进化 Agent 的问题或处理工具批准，必须延续原 request_id；"
                "用 background_tasks 读取统一任务详情，action=cancel 取消并回滚未完成进化。"
            ),
            entrypoint="agent_factory.tooling.builtins.agent_evolve.tool:run",
            input_schema=_input_schema(),
            output_schema={"type": "object", "additionalProperties": True},
            resources={
                "background_task_root": "background_task_root",
                "runtime_execution_config": "runtime_execution_config",
                "workdir_root": "workdir_root",
            },
            risk_level="medium",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.tooling.builtins.agent_evolve.tool:evaluate_risk"
            ),
            concurrent=False,
        )
    ]


def _input_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": ["start", "respond", "cancel"]},
            "package_id": {"type": "string", "minLength": 1},
            "goal": {"type": "string", "minLength": 1},
            "constraints": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "task_id": {"type": "string", "minLength": 1},
            "response": {"type": "string"},
            "decision": {"type": "string", "enum": ["approve", "deny", "revise"]},
            "reason": {"type": "string"},
        },
        "required": ["action"],
        "allOf": [
            {
                "if": {"properties": {"action": {"const": "start"}}, "required": ["action"]},
                "then": {"required": ["package_id", "goal"]},
            },
            {
                "if": {
                    "properties": {"action": {"enum": ["respond", "cancel"]}},
                    "required": ["action"],
                },
                "then": {"required": ["task_id"]},
            },
        ],
    }
