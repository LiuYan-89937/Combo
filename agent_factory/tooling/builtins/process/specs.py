from __future__ import annotations

from agent_factory.tooling.spec import ToolSpec


_STRING = {"type": "string"}
_INTEGER = {"type": "integer"}
_BOOLEAN = {"type": "boolean"}
_PROCESS_RESOURCE = {"process_runtime": "process_runtime"}

_COMMAND_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": "命令与参数数组。",
        },
        "cwd": {"type": "string", "description": "可选工作目录。"},
        "timeout_seconds": {"type": "integer", "minimum": 1, "description": "可选超时时间。"},
    },
    "required": ["command"],
    "additionalProperties": False,
}

_COMMAND_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "exit_code": _INTEGER,
        "stdout": _STRING,
        "stderr": _STRING,
        "timed_out": _BOOLEAN,
    },
    "required": ["exit_code", "stdout", "stderr", "timed_out"],
    "additionalProperties": False,
}


PROCESS_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        id="bash",
        description="在本地环境执行 Bash shell 命令。",
        entrypoint="agent_factory.tooling.builtins.process.bash:run",
        input_schema=_COMMAND_INPUT_SCHEMA,
        output_schema=_COMMAND_OUTPUT_SCHEMA,
        resources=_PROCESS_RESOURCE,
        approval_required=True,
        concurrent=False,
    ),
    ToolSpec(
        id="powershell",
        description="在本地环境执行 PowerShell 命令。",
        entrypoint="agent_factory.tooling.builtins.process.powershell:run",
        input_schema=_COMMAND_INPUT_SCHEMA,
        output_schema=_COMMAND_OUTPUT_SCHEMA,
        resources=_PROCESS_RESOURCE,
        approval_required=True,
        concurrent=False,
    ),
]


def get_process_tool_specs() -> list[ToolSpec]:
    return [tool.model_copy(deep=True) for tool in PROCESS_TOOL_SPECS]
