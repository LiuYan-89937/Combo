from __future__ import annotations

from agent_factory.tooling.builtins.process.runtime import host_shell_display_name
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


_STRING = {"type": "string"}
_INTEGER = {"type": "integer"}
_BOOLEAN = {"type": "boolean"}
_PROCESS_RESOURCE = {"process_runtime": "process_runtime"}
_PROCESS_MODULE = "agent_factory.tooling.builtins.process"
_CWD_BOUNDARY_DESCRIPTION = (
    "可选工作目录。默认值 . 就是当前会话工作区根目录，通常无需提供 cwd 或在 command 中先执行 cd；"
    "访问工作区文件时直接使用相对路径。指定 cwd 时优先使用工作区内的相对子目录；"
    "不要在 Shell 命令中使用文件工具的逻辑沙箱根目录别名，也不要使用 /tmp、宿主机路径或其他任意绝对路径，"
    "除非 runtime 显式允许外部路径。"
)

_PROCESS_STATUS_VALUES = ["running", "completed", "failed", "stopped"]
_PROCESS_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "process_id": _STRING,
        "status": {"type": "string", "enum": _PROCESS_STATUS_VALUES},
        "command": _STRING,
        "shell": _STRING,
        "shell_executable": _STRING,
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
        "shell",
        "shell_executable",
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
        id="shell",
        description=(
            f"在 workspace 边界内通过当前平台的 {host_shell_display_name()} 启动命令，"
            "子进程默认已位于当前会话工作区根目录，命令应直接使用相对路径，无需先执行 cd。"
            "支持前台等待或后台运行；wait 超时只返回状态，不自动终止进程。"
        ),
        entrypoint="agent_factory.tooling.builtins.process.shell:run",
        input_schema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        f"要交给当前平台 {host_shell_display_name()} 执行的命令文本。"
                    ),
                },
                "cwd": {"type": "string", "default": ".", "description": _CWD_BOUNDARY_DESCRIPTION},
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
                "fallback_reason": {
                    "type": "string",
                    "description": (
                        "executor 节点调用时必填：说明为什么当前可用的 package/runtime "
                        "工具无法完成此计划步骤，必须退回平台 Shell。"
                    ),
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        output_schema=_PROCESS_OUTPUT_SCHEMA,
        resources=_PROCESS_RESOURCE,
        risk_level="high",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_PROCESS_MODULE}.shell:evaluate_risk"),
        concurrent=False,
    ),
    ToolSpec(
        id="shell_status",
        description="查看由 shell 工具启动的进程状态和已收集输出。",
        entrypoint="agent_factory.tooling.builtins.process.shell_status:run",
        input_schema={
            "type": "object",
            "properties": {
                "process_id": {"type": "string", "description": "shell 返回的 process_id。"},
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
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_PROCESS_MODULE}.shell_status:evaluate_risk"),
        concurrent=True,
    ),
    ToolSpec(
        id="shell_stop",
        description="终止由 shell 工具启动的进程树，并返回最终状态和输出。",
        entrypoint="agent_factory.tooling.builtins.process.shell_stop:run",
        input_schema={
            "type": "object",
            "properties": {
                "process_id": {"type": "string", "description": "shell 返回的 process_id。"},
                "grace_seconds": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 300,
                    "default": 2,
                    "description": "请求进程树终止后等待多少秒再强制终止。",
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
        risk_level="medium",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_PROCESS_MODULE}.shell_stop:evaluate_risk"),
        concurrent=False,
    ),
]


def get_process_tool_specs() -> list[ToolSpec]:
    return [tool.model_copy(deep=True) for tool in PROCESS_TOOL_SPECS]
