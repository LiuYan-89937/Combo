from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


_STRING = {"type": "string"}
_INTEGER = {"type": "integer"}
_BOOLEAN = {"type": "boolean"}
_FILESYSTEM_RESOURCE = {"filesystem": "filesystem"}
_FS_MODULE = "agent_factory.tooling.builtins.filesystem"


FILESYSTEM_TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        id="read",
        description="读取指定文本文件内容，按行号返回可控范围。",
        entrypoint="agent_factory.tooling.builtins.filesystem.read:run",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要读取的文件路径。"},
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
        description="创建或覆盖指定文件内容。",
        entrypoint="agent_factory.tooling.builtins.filesystem.write:run",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要写入的文件路径。"},
                "content": {"type": "string", "description": "完整文件内容。"},
                "create_dirs": {"type": "boolean", "default": True, "description": "是否创建缺失父目录；默认创建。"},
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
        description="对单个文件执行一次有针对性的文本替换。",
        entrypoint="agent_factory.tooling.builtins.filesystem.edit:run",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要编辑的文件路径。"},
                "old_text": {"type": "string", "description": "需要被替换的原文本。"},
                "new_text": {"type": "string", "description": "替换后的文本。"},
                "replace_all": {"type": "boolean", "default": False, "description": "是否替换全部匹配项。"},
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
        description="在单个文件中原子执行多次文本替换。",
        entrypoint="agent_factory.tooling.builtins.filesystem.multi_edit:run",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要编辑的文件路径。"},
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
        description="基于 glob 模式查找文件路径。",
        entrypoint="agent_factory.tooling.builtins.filesystem.glob:run",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "glob 匹配模式。"},
                "base_path": {"type": "string", "default": ".", "description": "可选搜索根目录。"},
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
        description="在文件内容中搜索文本或正则模式。",
        entrypoint="agent_factory.tooling.builtins.filesystem.grep:run",
        input_schema={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "搜索文本或正则。"},
                "base_path": {"type": "string", "default": ".", "description": "可选搜索根目录或单个文件。"},
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
        description="列出指定目录内容。",
        entrypoint="agent_factory.tooling.builtins.filesystem.ls:run",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "要列出的目录路径。"},
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
