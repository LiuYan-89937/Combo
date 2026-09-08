from __future__ import annotations

from combo.tooling.spec import ToolSpec

COMPUTER_USE_RUNTIME_RESOURCE = "computer_use_runtime"


def get_computer_use_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="computer_use",
            description=(
                "Operate a native application through the desktop host. "
                "It is independent from the "
                "browser_* built-in tools. Pass the user's complete desktop objective in one call: the runtime already "
                "uses the integrated open-computer-use engine inside its own model loop. "
                "The engine returns indexed accessibility text and screenshots after operations. Final assessment belongs to the model. "
                "Do not split setup, navigation, and the final action into separate calls. "
                "Further calls may continue unfinished work or handle another objective. "
                "Use the previous result to avoid repeating actions whose effects are already verified or uncertain."
            ),
            entrypoint="combo.tooling.builtins.computer_use.tool:run",
            input_schema={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "minLength": 1,
                        "description": "A concise, complete desktop task objective for the accessibility loop.",
                    }
                },
                "required": ["goal"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["finished"],
                    },
                    "summary": {"type": "string"},
                    "steps": {"type": "integer"},
                    "model_calls": {"type": "integer"},
                    "total_tokens": {"type": "integer"},
                    "verification": {
                        "type": "string",
                        "enum": ["model_assessed"],
                    },
                },
                "required": [
                    "status",
                    "summary",
                    "steps",
                    "model_calls",
                    "total_tokens",
                    "verification",
                ],
                "additionalProperties": False,
            },
            resources={"computer_use_runtime": COMPUTER_USE_RUNTIME_RESOURCE},
            risk_level="high",
            concurrent=False,
            timeout_seconds=None,
            max_parallel_calls=1,
            output_projection="passthrough",
            effects=["external_side_effect"],
            read_only=False,
            system_available=True,
        )
    ]
