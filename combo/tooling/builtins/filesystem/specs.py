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
FILESYSTEM_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        id="read",
        description=(
            "读取 workspace 边界内的指定文本文件内容，按行号返回可控范围。"
            "offset 是从 1 开始的起始行号，limit 是最多返回的行数。"
            f"{_READ_MISSING_GUIDANCE}"
        ),
        entrypoint="combo.tooling.builtins.filesystem.read:run",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": _READ_PATH_DESCRIPTION},
                "offset": {"type": "integer", "minimum": 1, "default": 1, "description": "起始行号，从 1 开始，默认 1；不是字节偏移量。"},
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
            },
            "required": ["path", "content", "start_line", "end_line", "total_lines", "truncated"],
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
            "action=commit 或 action=abort 提供真实 write_id。append/commit/abort 不接受 path。"
            "不要编造或跨 workspace 复用 write_id。"
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
        description=(
            "对 workspace 边界内的单个 UTF-8 文件执行精确文本替换。先读取同一路径的当前内容，"
            "从中原样复制 old_text，保留缩进、空格和换行；不要套用另一文件或旧版本中的文本。"
            "未匹配时文件不会修改，应重新读取目标或用 rg 定位原文，不要直接改成整体覆盖。"
        ),
        schema_error_guidance=(
            "提供 path、old_text 和 new_text。old_text 默认必须只匹配一处；"
            "需要替换全部匹配时显式设置 replace_all=true。"
        ),
        entrypoint="combo.tooling.builtins.filesystem.edit:run",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": _WRITE_PATH_DESCRIPTION},
                "old_text": {"type": "string", "minLength": 1, "description": "从同一路径当前内容原样复制的非空原文本，包含准确的空白与换行。"},
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
            "在 workspace 内查找路径或搜索文件内容时使用本工具，包括按名称、扩展名、目录结构、文本或正则定位代码。"
            "文件发现和内容检索不要通过 shell 调用 grep、find 或 ls。"
            "始终传 action、pattern；path 可省略。"
            "查找文件示例：{\"action\":\"files\",\"pattern\":\"**/*.py\"}。"
            "搜索内容示例：{\"action\":\"search\",\"pattern\":\"ModelPool\",\"path\":\"combo\"}。"
            "默认遵循 ignore 文件，并排除依赖目录和构建产物。"
        ),
        schema_error_guidance=(
            "参数固定为 action、pattern、path、max_results；其中 action 和 pattern 必填。"
        ),
        entrypoint="combo.tooling.builtins.filesystem.rg:run",
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["files", "search"],
                    "description": "files 查找路径，search 搜索文件内容。",
                },
                "pattern": {
                    "type": "string",
                    "minLength": 1,
                    "description": "files 时为 glob；search 时为文本或正则表达式。",
                },
                "path": {
                    "type": "string",
                    "default": ".",
                    "description": f"搜索起点，可以是文件或目录。{_PATH_BOUNDARY_DESCRIPTION}",
                },
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5000,
                    "default": 100,
                    "description": "最多返回的路径或命中数量。",
                },
            },
            "required": ["action", "pattern"],
            "additionalProperties": False,
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
                                    "text_truncated": _BOOLEAN,
                                },
                                "required": [
                                    "path",
                                    "line_number",
                                    "text",
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
