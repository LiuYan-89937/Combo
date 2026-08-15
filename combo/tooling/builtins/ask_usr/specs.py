from __future__ import annotations

from combo.tooling.spec import ToolLoopPolicyConfig, ToolSpec


ASK_USR_TOOL_ID = "ask_usr"
ASK_USR_CAPABILITY_ID = f"tool://builtin/{ASK_USR_TOOL_ID}"


def get_ask_usr_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=ASK_USR_TOOL_ID,
            description=(
                "Ask the user one focused question when this temporary Agent cannot continue without missing "
                "information. The question is shown in the main conversation as a structured interaction card. "
                "Use choices for a small set of mutually exclusive options and allow_free_text when a written "
                "answer is useful. Do not use this tool for tool approvals or ordinary progress updates."
            ),
            entrypoint="combo.tooling.builtins.ask_usr.tool:run",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "question": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 2000,
                        "description": "The concise question the user must answer before this task can continue.",
                    },
                    "choices": {
                        "type": "array",
                        "maxItems": 12,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "value": {"type": "string", "minLength": 1, "maxLength": 200},
                                "label": {"type": "string", "minLength": 1, "maxLength": 200},
                                "description": {"type": "string", "maxLength": 500},
                            },
                            "required": ["value", "label"],
                        },
                        "default": [],
                        "description": "Optional structured options. Keep the list short and mutually exclusive.",
                    },
                    "allow_free_text": {
                        "type": "boolean",
                        "default": True,
                        "description": "Whether the user may enter an answer that is not one of the choices.",
                    },
                },
                "required": ["question"],
            },
            output_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "question_id": {"type": "string", "minLength": 1},
                    "answer": {"type": "string", "minLength": 1},
                },
                "required": ["question_id", "answer"],
            },
            risk_level="low",
            concurrent=False,
            max_parallel_calls=1,
            effects=["read"],
            read_only=True,
            system_available=False,
            loop_policy=ToolLoopPolicyConfig(max_calls=1),
        )
    ]
