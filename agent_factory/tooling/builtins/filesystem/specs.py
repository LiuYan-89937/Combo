from __future__ import annotations

from agent_factory.runtime_defaults import DEFAULT_BUILTIN_WORKSPACE_ROOT
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


_STRING = {"type": "string"}
_INTEGER = {"type": "integer"}
_BOOLEAN = {"type": "boolean"}
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
    "新生成的文件应写入工作区内，例如 output/report.md 或 "
    f"{DEFAULT_BUILTIN_WORKSPACE_ROOT}/output/report.md。"
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
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_FS_MODULE}.read:evaluate_risk"),
        concurrent=True,
    ),
    ToolSpec(
        id="write",
        description=(
            "在 workspace 边界内创建或覆盖指定文件内容。"
            "调用 write 时必须把要写入文件的完整正文放入 content 参数；"
            "不要先在 assistant 消息里输出正文后只传 path，也不要假设 write 会自动读取上一段回复内容。"
        ),
        schema_error_guidance=(
            "write 调用必须同时提供 path 和 content。content 必须是要写入目标文件的完整文本内容；"
            "如果你刚刚在消息中生成了报告或文档，请重新调用 write，并把那份完整内容放进 content 字段。"
        ),
        entrypoint="agent_factory.tooling.builtins.filesystem.write:run",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": _WRITE_PATH_DESCRIPTION},
                "content": {
                    "type": "string",
                    "description": (
                        "要写入文件的完整正文内容。长报告、Markdown 文档、代码或配置都必须完整放在这里；"
                        "工具不会自动使用 assistant 刚刚输出过的文本。"
                    ),
                },
                "create_dirs": {"type": "boolean", "default": True, "description": "是否创建缺失父目录；默认创建。"},
                "fallback_reason": {
                    "type": "string",
                    "description": "executor 节点调用时必填：说明为什么当前可用的 package/runtime 工具无法完成此计划步骤，必须退回通用写文件能力。",
                },
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "path": _STRING,
                "created": _BOOLEAN,
                "bytes_written": _INTEGER,
                "before_hash": {"type": ["string", "null"]},
                "after_hash": _STRING,
            },
            "required": ["path", "created", "bytes_written", "before_hash", "after_hash"],
            "additionalProperties": False,
        },
        resources=_FILESYSTEM_RESOURCE,
        risk_level="medium",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_FS_MODULE}.write:evaluate_risk"),
        concurrent=False,
    ),
    ToolSpec(
        id="edit",
        description="对 workspace 边界内的单个文件执行一次有针对性的文本替换。",
        entrypoint="agent_factory.tooling.builtins.filesystem.edit:run",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": _WRITE_PATH_DESCRIPTION},
                "old_text": {"type": "string", "description": "需要被替换的原文本。"},
                "new_text": {"type": "string", "description": "替换后的文本。"},
                "replace_all": {"type": "boolean", "default": False, "description": "是否替换全部匹配项。"},
                "fallback_reason": {
                    "type": "string",
                    "description": "executor 节点调用时必填：说明为什么当前可用的 package/runtime 工具无法完成此计划步骤，必须退回通用编辑能力。",
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
            },
            "required": ["path", "replacements", "before_hash", "after_hash"],
            "additionalProperties": False,
        },
        resources=_FILESYSTEM_RESOURCE,
        risk_level="medium",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_FS_MODULE}.edit:evaluate_risk"),
        concurrent=False,
    ),
    ToolSpec(
        id="multi_edit",
        description="在 workspace 边界内的单个文件中原子执行多次文本替换。",
        entrypoint="agent_factory.tooling.builtins.filesystem.multi_edit:run",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": _WRITE_PATH_DESCRIPTION},
                "edits": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "old_text": _STRING,
                            "new_text": _STRING,
                            "replace_all": {"type": "boolean", "default": False},
                        },
                        "required": ["old_text", "new_text"],
                        "additionalProperties": False,
                    },
                },
                "fallback_reason": {
                    "type": "string",
                    "description": "executor 节点调用时必填：说明为什么当前可用的 package/runtime 工具无法完成此计划步骤，必须退回通用编辑能力。",
                },
            },
            "required": ["path", "edits"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {
                "path": _STRING,
                "replacements": _INTEGER,
                "edit_results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "index": _INTEGER,
                            "replacements": _INTEGER,
                        },
                        "required": ["index", "replacements"],
                        "additionalProperties": False,
                    },
                },
                "before_hash": _STRING,
                "after_hash": _STRING,
            },
            "required": ["path", "replacements", "edit_results", "before_hash", "after_hash"],
            "additionalProperties": False,
        },
        resources=_FILESYSTEM_RESOURCE,
        risk_level="medium",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_FS_MODULE}.multi_edit:evaluate_risk"),
        concurrent=False,
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
                        },
                        "required": ["path", "name", "type"],
                        "additionalProperties": False,
                    },
                },
                "truncated": _BOOLEAN,
            },
            "required": ["matches", "truncated"],
            "additionalProperties": False,
        },
        resources=_FILESYSTEM_RESOURCE,
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_FS_MODULE}.glob:evaluate_risk"),
        concurrent=True,
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
                "include": {"type": "string", "description": "可选文件匹配模式。"},
                "case_sensitive": {"type": "boolean", "default": True},
                "regex": {"type": "boolean", "default": True},
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
                        },
                        "required": ["path", "line", "line_number"],
                        "additionalProperties": False,
                    },
                },
                "truncated": _BOOLEAN,
            },
            "required": ["matches", "truncated"],
            "additionalProperties": False,
        },
        resources=_FILESYSTEM_RESOURCE,
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_FS_MODULE}.grep:evaluate_risk"),
        concurrent=True,
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
                        },
                        "required": ["path", "name", "type"],
                        "additionalProperties": False,
                    },
                },
                "truncated": _BOOLEAN,
            },
            "required": ["entries", "truncated"],
            "additionalProperties": False,
        },
        resources=_FILESYSTEM_RESOURCE,
        risk_level="low",
        risk_evaluator=ToolRiskEvaluatorConfig(hard=f"{_FS_MODULE}.ls:evaluate_risk"),
        concurrent=True,
    ),
]


def get_filesystem_tool_specs() -> list[ToolSpec]:
    return [tool.model_copy(deep=True) for tool in FILESYSTEM_TOOL_SPECS]
