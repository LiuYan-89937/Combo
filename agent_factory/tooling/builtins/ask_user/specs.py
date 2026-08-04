from __future__ import annotations

from agent_factory.tooling.spec import ToolSpec


ASK_USER_TOOL_ID = "ask_user"


def get_ask_user_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=ASK_USER_TOOL_ID,
            description=(
                "暂停当前委派任务并向用户提出一个确实阻塞后续工作的具体问题。"
                "仅在无法从现有任务信息、文件或工具结果中确定答案时调用；"
                "可提供少量互斥选项，也可允许用户自由输入。用户回答后任务会从当前检查点继续。"
            ),
            entrypoint="agent_factory.tooling.builtins.ask_user.tool:run",
            input_schema=_input_schema(),
            output_schema={"type": "object", "additionalProperties": True},
            resources={"runtime_execution_config": "runtime_execution_config"},
            risk_level="low",
            concurrent=False,
        )
    ]


def _input_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "question": {"type": "string", "minLength": 1},
            "title": {"type": "string", "minLength": 1},
            "options": {
                "type": "array",
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "value": {"type": "string", "minLength": 1},
                        "label": {"type": "string", "minLength": 1},
                        "description": {"type": "string"},
                    },
                    "required": ["value", "label"],
                },
            },
            "allow_free_text": {"type": "boolean", "default": True},
        },
        "required": ["question"],
    }
