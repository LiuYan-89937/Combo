from __future__ import annotations

from combo.runtime_defaults import DEFAULT_BUILTIN_WORKSPACE_ROOT
from combo.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec
from combo.tooling.builtins.filesystem.guidance import WRITE_STRATEGY_GUIDANCE


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
_FS_MODULE = "combo.tooling.builtins.filesystem"
_PATH_BOUNDARY_DESCRIPTION = (
    "路径受当前工具 workspace root 限制；优先使用相对路径，或使用位于 workspace root 内的绝对路径。"
    f"默认 sandbox workspace root 是 {DEFAULT_BUILTIN_WORKSPACE_ROOT}。"
    "不要使用 /tmp、宿主机路径或其他任意绝对路径，除非 runtime 显式允许外部路径。"
)
_READ_MISSING_GUIDANCE = (
    "如果 read 提示文件不存在或路径不确定，不要直接断定文件不可用；"
    "先调用 rg 的 files 操作查找父目录或相近路径，确认真实文件名、大小写、后缀或路径层级后再重试 read。"
)
_READ_PATH_DESCRIPTION = f"要读取的文件路径。{_PATH_BOUNDARY_DESCRIPTION}{_READ_MISSING_GUIDANCE}"
_WRITE_PATH_DESCRIPTION = (
    f"要写入的文件路径。{_PATH_BOUNDARY_DESCRIPTION}"
    "新生成的文件应直接写入工作区内，例如 report.md 或 "
    f"{DEFAULT_BUILTIN_WORKSPACE_ROOT}/report.md。"
)
_CONTEXT_LINE_SCHEMA = {
    "type": "object",
    "properties": {
        "line_number": _INTEGER,
        "text": _STRING,
        "text_truncated": _BOOLEAN,
    },
    "required": ["line_number", "text", "text_truncated"],
    "additionalProperties": False,
}

FILESYSTEM_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        id="read",
        description=(
            "读取 workspace 边界内的指定文本文件内容，按行号返回可控范围。"
            f"{_READ_MISSING_GUIDANCE}"
        ),
        entrypoint="combo.tooling.builtins.filesystem.read:run",
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
        entrypoint="combo.tooling.builtins.filesystem.write:run",
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
                        "create_dirs": {"type": "boolean", "default": True, "description": "目标父目录不存在时是否自动创建。"},
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
                        "create_dirs": {"type": "boolean", "default": True, "description": "目标父目录不存在时是否自动创建。"},
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
                        "write_id": {"type": "string", "description": "action=start 返回的 staged write 标识。"},
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
                        "write_id": {"type": "string", "description": "需要原子提交的 staged write 标识。"},
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
                        "write_id": {"type": "string", "description": "需要放弃的 staged write 标识。"},
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
        entrypoint="combo.tooling.builtins.filesystem.edit:run",
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
        id="rg",
        description=(
            "使用应用随包提供的 ripgrep 在 workspace 边界内查找文件或搜索内容。"
            "action=files 根据 glob 模式返回文件路径；action=search 返回带行号和上下文的文本或正则命中。"
            "搜索遵循 ignore 文件并默认排除隐藏目录、依赖目录和构建产物。"
        ),
        schema_error_guidance=(
            "查找文件时使用 action=files，并提供 pattern；搜索内容时使用 action=search，并提供 pattern。"
            "path、include、exclude、大小写、正则和上下文参数只能放在对应 action 的 schema 中。"
        ),
        entrypoint="combo.tooling.builtins.filesystem.rg:run",
        input_schema={
            "oneOf": [
                {
                    "type": "object",
                    "properties": {
                        "action": {"const": "files"},
                        "pattern": {
                            "type": "string",
                            "minLength": 1,
                            "description": "用于查找文件的 glob 模式，例如 **/*.py 或 src/**。",
                        },
                        "path": {
                            "type": "string",
                            "default": ".",
                            "description": f"查找根目录。{_PATH_BOUNDARY_DESCRIPTION}",
                        },
                        "exclude": {
                            "type": "array",
                            "items": _STRING,
                            "description": "额外排除的 glob 模式。",
                        },
                        "max_results": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 5000,
                            "default": 100,
                            "description": "最多返回的文件数量。",
                        },
                    },
                    "required": ["action", "pattern"],
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {
                        "action": {"const": "search"},
                        "pattern": {
                            "type": "string",
                            "minLength": 1,
                            "description": "要搜索的文本或正则表达式。",
                        },
                        "path": {
                            "type": "string",
                            "default": ".",
                            "description": f"要搜索的文件或目录。{_PATH_BOUNDARY_DESCRIPTION}",
                        },
                        "include": {
                            "type": "array",
                            "items": _STRING,
                            "description": "只搜索这些 glob 模式匹配的文件。",
                        },
                        "exclude": {
                            "type": "array",
                            "items": _STRING,
                            "description": "排除这些 glob 模式匹配的文件。",
                        },
                        "case_sensitive": {
                            "type": "boolean",
                            "default": True,
                            "description": "是否区分英文字母大小写。",
                        },
                        "regex": {
                            "type": "boolean",
                            "default": True,
                            "description": "是否将 pattern 解释为正则；false 时按普通文本搜索。",
                        },
                        "context_before": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 20,
                            "default": 0,
                            "description": "每个命中前返回的上下文行数。",
                        },
                        "context_after": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 20,
                            "default": 0,
                            "description": "每个命中后返回的上下文行数。",
                        },
                        "max_results": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 5000,
                            "default": 100,
                            "description": "最多返回的命中数量。",
                        },
                    },
                    "required": ["action", "pattern"],
                    "additionalProperties": False,
                },
            ]
        },
        output_schema={
            "oneOf": [
                {
                    "type": "object",
                    "properties": {
                        "files": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"path": _STRING},
                                "required": ["path"],
                                "additionalProperties": False,
                            },
                        },
                        "truncated": _BOOLEAN,
                    },
                    "required": ["files", "truncated"],
                    "additionalProperties": False,
                },
                {
                    "type": "object",
                    "properties": {
                        "matches": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "path": _STRING,
                                    "line_number": _INTEGER,
                                    "text": _STRING,
                                    "before": {"type": "array", "items": _CONTEXT_LINE_SCHEMA},
                                    "after": {"type": "array", "items": _CONTEXT_LINE_SCHEMA},
                                    "text_truncated": _BOOLEAN,
                                },
                                "required": [
                                    "path",
                                    "line_number",
                                    "text",
                                    "before",
                                    "after",
                                    "text_truncated",
                                ],
                                "additionalProperties": False,
                            },
                        },
                        "truncated": _BOOLEAN,
                    },
                    "required": ["matches", "truncated"],
                    "additionalProperties": False,
                },
            ]
        },
        resources=_FILESYSTEM_RESOURCE,
        effects=["read"],
        read_only=True,
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_FS_MODULE}.rg:evaluate_risk"),
        concurrent=True,
        max_parallel_calls=4,
        timeout_seconds=30.0,
    ),
]


def get_filesystem_tool_specs() -> list[ToolSpec]:
    return [
        tool.model_copy(update={"system_available": True}, deep=True)
        for tool in FILESYSTEM_TOOL_SPECS
    ]
