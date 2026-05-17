from __future__ import annotations

from agent_factory.tooling.spec import ToolSpec


_STRING = {"type": "string"}
_INTEGER = {"type": "integer"}
_BOOLEAN = {"type": "boolean"}
_PROCESS_RESOURCE = {"process_runtime": "process_runtime"}

_PROCESS_STATUS_VALUES = ["running", "completed", "failed", "stopped"]
_PROCESS_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "process_id": _STRING,
        "status": {"type": "string", "enum": _PROCESS_STATUS_VALUES},
        "command": _STRING,
        "cwd": _STRING,
        "exit_code": {"type": ["integer", "null"]},
        "stdout": _STRING,
        "stderr": _STRING,
        "stdout_truncated": _BOOLEAN,
        "stderr_truncated": _BOOLEAN,
        "duration_ms": _INTEGER,
    },
    "required": [
        "process_id",
        "status",
        "command",
        "cwd",
        "exit_code",
        "stdout",
        "stderr",
        "stdout_truncated",
        "stderr_truncated",
        "duration_ms",
    ],
    "additionalProperties": False,
}


PROCESS_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        id="bash",
        description="在本地环境启动 Bash 命令，支持前台等待或后台运行；wait 超时只返回状态，不自动终止进程。",
        entrypoint="agent_factory.tooling.builtins.process.bash:run",
        input_schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的 Bash 命令文本。"},
                "cwd": {"type": "string", "default": ".", "description": "可选工作目录。"},
                "mode": {
                    "type": "string",
                    "enum": ["foreground", "background"],
                    "default": "foreground",
                    "description": "foreground 会等待 wait_seconds；background 会立即返回进程状态。",
                },
                "wait_seconds": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 86400,
                    "default": 30,
                    "description": "foreground 模式最多等待多少秒返回；超时不杀进程。",
                },
                "max_output_chars": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200000,
                    "default": 12000,
                    "description": "本次返回的 stdout/stderr 尾部最大字符数。",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        output_schema=_PROCESS_OUTPUT_SCHEMA,
        resources=_PROCESS_RESOURCE,
        approval_required=True,
        concurrent=False,
    ),
    ToolSpec(
        id="bash_status",
        description="查看由 bash 工具启动的进程状态和已收集输出。",
        entrypoint="agent_factory.tooling.builtins.process.bash_status:run",
        input_schema={
            "type": "object",
            "properties": {
                "process_id": {"type": "string", "description": "bash 返回的 process_id。"},
                "max_output_chars": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200000,
                    "default": 12000,
                    "description": "本次返回的 stdout/stderr 尾部最大字符数。",
                },
            },
            "required": ["process_id"],
            "additionalProperties": False,
        },
        output_schema=_PROCESS_OUTPUT_SCHEMA,
        resources=_PROCESS_RESOURCE,
        approval_required=False,
        concurrent=True,
    ),
    ToolSpec(
        id="bash_stop",
        description="终止由 bash 工具启动的进程，并返回最终状态和输出。",
        entrypoint="agent_factory.tooling.builtins.process.bash_stop:run",
        input_schema={
            "type": "object",
            "properties": {
                "process_id": {"type": "string", "description": "bash 返回的 process_id。"},
                "grace_seconds": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 300,
                    "default": 2,
                    "description": "SIGTERM 后等待多少秒再强制终止。",
                },
                "max_output_chars": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200000,
                    "default": 12000,
                    "description": "本次返回的 stdout/stderr 尾部最大字符数。",
                },
            },
            "required": ["process_id"],
            "additionalProperties": False,
        },
        output_schema=_PROCESS_OUTPUT_SCHEMA,
        resources=_PROCESS_RESOURCE,
        approval_required=True,
        concurrent=False,
    ),
]


def get_process_tool_specs() -> list[ToolSpec]:
    return [tool.model_copy(deep=True) for tool in PROCESS_TOOL_SPECS]
