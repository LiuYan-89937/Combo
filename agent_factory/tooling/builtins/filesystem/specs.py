from __future__ import annotations

from agent_factory.runtime_defaults import DEFAULT_BUILTIN_WORKSPACE_ROOT
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec
from agent_factory.tooling.builtins.filesystem.guidance import WRITE_STRATEGY_GUIDANCE


_STRING = {"type": "string"}
_INTEGER = {"type": "integer"}
_BOOLEAN = {"type": "boolean"}
_CHANGE_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "before_bytes": _INTEGER,
        "after_bytes": _INTEGER,
        "before_lines": _INTEGER,
        "after_lines": _INTEGER,
        "added_lines": _INTEGER,
        "removed_lines": _INTEGER,
    },
    "required": [
        "before_bytes",
        "after_bytes",
        "before_lines",
        "after_lines",
        "added_lines",
        "removed_lines",
    ],
    "additionalProperties": False,
}
_FILESYSTEM_RESOURCE = {"filesystem": "filesystem"}
_FS_MODULE = "agent_factory.tooling.builtins.filesystem"
_PATH_BOUNDARY_DESCRIPTION = (
    "路径受当前工具 workspace root 限制；优先使用相对路径，或使用位于 workspace root 内的绝对路径。"
    f"默认 sandbox workspace root 是 {DEFAULT_BUILTIN_WORKSPACE_ROOT}。"
    "不要使用 /tmp、宿主机路径或其他任意绝对路径，除非 runtime 显式允许外部路径。"
)
_READ_MISSING_GUIDANCE = (
    "如果 read 提示文件不存在或路径不确定，不要直接断定文件不可用；"
    "先调用 ls 查看父目录或相近目录，确认真实文件名、大小写、后缀或路径层级后再重试 read。"
)
_READ_PATH_DESCRIPTION = f"要读取的文件路径。{_PATH_BOUNDARY_DESCRIPTION}{_READ_MISSING_GUIDANCE}"
_LS_PATH_DESCRIPTION = f"要列出的目录路径。{_PATH_BOUNDARY_DESCRIPTION}"
_WRITE_PATH_DESCRIPTION = (
    f"要写入的文件路径。{_PATH_BOUNDARY_DESCRIPTION}"
    "新生成的文件应直接写入工作区内，例如 report.md 或 "
    f"{DEFAULT_BUILTIN_WORKSPACE_ROOT}/report.md。"
)
_BASE_PATH_DESCRIPTION = f"可选搜索根目录。{_PATH_BOUNDARY_DESCRIPTION}"


FILESYSTEM_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        id="read",
        description=(
            "读取 workspace 边界内的指定文本文件内容，按行号返回可控范围。"
            f"{_READ_MISSING_GUIDANCE}"
        ),
        entrypoint="agent_factory.tooling.builtins.filesystem.read:run",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": _READ_PATH_DESCRIPTION},
                "start_line": {"type": "integer", "minimum": 1, "default": 1, "description": "起始行号，从 1 开始。"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 200, "description": "最多读取多少行。"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "path": _STRING,
                "content": _STRING,
                "start_line": _INTEGER,
                "end_line": _INTEGER,
                "total_lines": _INTEGER,
                "truncated": _BOOLEAN,
                "content_hash": _STRING,
            },
            "required": ["path", "content", "start_line", "end_line", "total_lines", "truncated", "content_hash"],
            "additionalProperties": False,
        },
        resources=_FILESYSTEM_RESOURCE,
        effects=["read"],
        read_only=True,
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_FS_MODULE}.read:evaluate_risk"),
        concurrent=True,
        max_parallel_calls=4,
    ),
    ToolSpec(
        id="write",
        description=(
            "在 workspace 边界内创建或整体替换指定文本文件。"
            f"{WRITE_STRATEGY_GUIDANCE}"
            "分段提交会复核开始时的目标快照并原子替换目标；失败不会留下半写目标。工具不会自动读取 assistant 消息中的正文。"
        ),
        schema_error_guidance=(
            "必须显式选择写入策略。一次性写入使用 action=write_once，并同时提供 path 和完整 content；"
            "分段写入只接受以下顺序："
            "action=start 提供 path；action=append 提供真实 write_id 和 content；"
            "action=commit 或 action=abort 提供真实 write_id。不要编造或跨 workspace 复用 write_id。"
        ),
        entrypoint="agent_factory.tooling.builtins.filesystem.write:run",
        input_schema={
            "oneOf": [
                {
                    "type": "object",
                    "properties": {
                        "action": {
                            "const": "write_once",
                            "description": "单个文件的完整最终正文已经成型，并能在本次调用中可靠提供全部内容时选择；会整体替换目标文件。",
                        },
                        "path": {"type": "string", "description": _WRITE_PATH_DESCRIPTION},
                        "content": {
                            "type": "string",
                            "description": "已经完整成型、可在本次调用中可靠提供的全部正文。",
                        },
                        "create_dirs": {"type": "boolean", "default": True},
                    },
                    "required": ["action", "path", "content"],
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {
                        "action": {
                            "const": "start",
                            "description": "正文需要分章节或模块渐进生成、一次调用存在截断风险，或需要保留中间进度时选择。",
                        },
                        "path": {"type": "string", "description": _WRITE_PATH_DESCRIPTION},
                        "expected_hash": {
                            "type": "string",
                            "description": "可选的当前目标 SHA-256；不匹配时拒绝开始。",
                        },
                        "create_dirs": {"type": "boolean", "default": True},
                    },
                    "required": ["action", "path"],
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {
                        "action": {
                            "const": "append",
                            "description": "向同一个 staged write 按顺序追加一个完整语义块；不要拆成随机 token 或零散行。",
                        },
                        "write_id": {"type": "string"},
                        "content": {
                            "type": "string",
                            "description": "本次按顺序追加的一个完整语义块，例如一个章节、组件或代码模块。",
                        },
                    },
                    "required": ["action", "write_id", "content"],
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {
                        "action": {
                            "const": "commit",
                            "description": "所有语义块追加完成后仅提交一次，原子替换目标文件。",
                        },
                        "write_id": {"type": "string"},
                    },
                    "required": ["action", "write_id"],
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {
                        "action": {
                            "const": "abort",
                            "description": "放弃当前 staged write 或无法继续生成时调用，不会修改目标文件。",
                        },
                        "write_id": {"type": "string"},
                    },
                    "required": ["action", "write_id"],
                    "additionalProperties": False,
                },
            ],
        },
        output_schema={"type": "object"},
        resources=_FILESYSTEM_RESOURCE,
        effects=["write"],
        risk_level="medium",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_FS_MODULE}.write:evaluate_risk"),
        concurrent=False,
        max_parallel_calls=1,
    ),
    ToolSpec(
        id="edit",
        description="对 workspace 边界内的单个 UTF-8 文件执行精确文本替换。",
        schema_error_guidance=(
            "提供 path、old_text 和 new_text。old_text 默认必须只匹配一处；"
            "需要替换全部匹配时显式设置 replace_all=true。"
        ),
        entrypoint="agent_factory.tooling.builtins.filesystem.edit:run",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": _WRITE_PATH_DESCRIPTION},
                "old_text": {"type": "string", "description": "需要被替换的完整原文本。"},
                "new_text": {"type": "string", "description": "替换后的文本，可为空字符串。"},
                "replace_all": {
                    "type": "boolean",
                    "default": False,
                    "description": "是否替换全部匹配项。",
                },
            },
            "required": ["path", "old_text", "new_text"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "path": _STRING,
                "replacements": _INTEGER,
                "before_hash": _STRING,
                "after_hash": _STRING,
                "change_summary": _CHANGE_SUMMARY_SCHEMA,
            },
            "required": ["path", "replacements", "before_hash", "after_hash", "change_summary"],
            "additionalProperties": False,
        },
        resources=_FILESYSTEM_RESOURCE,
        effects=["write"],
        risk_level="medium",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_FS_MODULE}.edit:evaluate_risk"),
        concurrent=False,
        max_parallel_calls=1,
    ),
    ToolSpec(
        id="glob",
        description="在 workspace 边界内基于 glob 模式查找文件路径。",
        entrypoint="agent_factory.tooling.builtins.filesystem.glob:run",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "glob 匹配模式。"},
                "base_path": {"type": "string", "default": ".", "description": _BASE_PATH_DESCRIPTION},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 100, "description": "可选最大返回数量。"},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "matches": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": _STRING,
                            "name": _STRING,
                            "type": {"type": "string", "enum": ["file", "directory", "other"]},
                            "size_bytes": {"type": ["integer", "null"]},
                            "modified_at": _STRING,
                        },
                        "required": ["path", "name", "type", "size_bytes", "modified_at"],
                        "additionalProperties": False,
                    },
                },
                "truncated": _BOOLEAN,
            },
            "required": ["matches", "truncated"],
            "additionalProperties": False,
        },
        resources=_FILESYSTEM_RESOURCE,
        effects=["read"],
        read_only=True,
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_FS_MODULE}.glob:evaluate_risk"),
        concurrent=True,
        max_parallel_calls=4,
    ),
    ToolSpec(
        id="grep",
        description="在 workspace 边界内的文件内容中搜索文本或正则模式。",
        entrypoint="agent_factory.tooling.builtins.filesystem.grep:run",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "搜索文本或正则。"},
                "base_path": {"type": "string", "default": ".", "description": _BASE_PATH_DESCRIPTION},
                "include": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": _STRING},
                    ],
                    "description": "可选文件匹配模式或模式列表。",
                },
                "exclude": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": _STRING},
                    ],
                    "description": "可选排除文件模式或模式列表。",
                },
                "case_sensitive": {"type": "boolean", "default": True},
                "regex": {"type": "boolean", "default": True},
                "context_before": {"type": "integer", "minimum": 0, "maximum": 20, "default": 0},
                "context_after": {"type": "integer", "minimum": 0, "maximum": 20, "default": 0},
                "max_file_bytes": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20000000,
                    "default": 2000000,
                },
                "max_results": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 100},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "matches": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": _STRING,
                            "line": _STRING,
                            "line_number": _INTEGER,
                            "before": {"type": "array", "items": _STRING},
                            "after": {"type": "array", "items": _STRING},
                        },
                        "required": ["path", "line", "line_number", "before", "after"],
                        "additionalProperties": False,
                    },
                },
                "truncated": _BOOLEAN,
                "files_searched": _INTEGER,
            },
            "required": ["matches", "truncated", "files_searched"],
            "additionalProperties": False,
        },
        resources=_FILESYSTEM_RESOURCE,
        effects=["read"],
        read_only=True,
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_FS_MODULE}.grep:evaluate_risk"),
        concurrent=True,
        max_parallel_calls=4,
    ),
    ToolSpec(
        id="ls",
        description="列出 workspace 边界内的指定目录内容。",
        entrypoint="agent_factory.tooling.builtins.filesystem.ls:run",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": _LS_PATH_DESCRIPTION},
                "recursive": {"type": "boolean", "default": False},
                "max_entries": {"type": "integer", "minimum": 1, "maximum": 5000, "default": 200},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "entries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": _STRING,
                            "name": _STRING,
                            "type": {"type": "string", "enum": ["file", "directory", "other"]},
                            "size_bytes": {"type": ["integer", "null"]},
                            "modified_at": _STRING,
                        },
                        "required": ["path", "name", "type", "size_bytes", "modified_at"],
                        "additionalProperties": False,
                    },
                },
                "truncated": _BOOLEAN,
            },
            "required": ["entries", "truncated"],
            "additionalProperties": False,
        },
        resources=_FILESYSTEM_RESOURCE,
        effects=["read"],
        read_only=True,
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_FS_MODULE}.ls:evaluate_risk"),
        concurrent=True,
        max_parallel_calls=4,
    ),
]


def get_filesystem_tool_specs() -> list[ToolSpec]:
    return [
        tool.model_copy(update={"system_available": True}, deep=True)
        for tool in FILESYSTEM_TOOL_SPECS
    ]
