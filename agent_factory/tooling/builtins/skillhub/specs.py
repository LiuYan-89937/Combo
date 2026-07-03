from __future__ import annotations

from agent_factory.tooling.skillhub.constants import SKILLHUB_RUNTIME_RESOURCE
from agent_factory.tooling.skillhub.search_query import (
    SKILLHUB_SEARCH_QUERY_MAX_CHARS,
    SKILLHUB_SEARCH_QUERY_PATTERN,
)
from agent_factory.tooling.spec import ToolOutputCompressionActionConfig, ToolOutputCompressionConfig, ToolRiskEvaluatorConfig, ToolSpec


def get_skillhub_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="skillhub",
            description=(
                "搜索 SkillHUB、检查全局 SkillHUB CLI 状态，或将 SkillHUB 技能安装到当前 Agent 的技能扩展目录并启用。"
            ),
            entrypoint="agent_factory.tooling.builtins.skillhub.skillhub:run",
            input_schema=_input_schema(),
            output_schema=_output_schema(),
            resources={"skillhub": SKILLHUB_RUNTIME_RESOURCE},
            risk_level="high",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.tooling.builtins.skillhub.skillhub:evaluate_risk",
            ),
            concurrent=False,
            output_compression=_output_compression(),
        )
    ]


def _input_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": ["status", "search", "install"]},
            "query": {
                "type": "string",
                "minLength": 1,
                "maxLength": SKILLHUB_SEARCH_QUERY_MAX_CHARS,
                "pattern": SKILLHUB_SEARCH_QUERY_PATTERN,
                "description": (
                    "仅用于 action=search。必须是 1 到 3 个短关键词或精确技能名，不能是长句、"
                    "需求描述、或大量中英同义词堆叠。宽泛探索时拆成多次 search，每次只放少量高信号词；"
                    "例如：frontend、design、frontend design、ppt、web、网页。"
                ),
                "examples": ["frontend", "design", "frontend design", "ppt", "web", "网页"],
            },
            "skill": {
                "type": "string",
                "description": "SkillHUB skill name to install for action=install.",
            },
        },
        "required": ["action"],
        "oneOf": [
            {"properties": {"action": {"const": "status"}}, "required": ["action"]},
            {"properties": {"action": {"const": "search"}}, "required": ["action", "query"]},
            {"properties": {"action": {"const": "install"}}, "required": ["action", "skill"]},
        ],
    }


def _output_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": True,
        "properties": {
            "action": {"type": "string"},
            "status": {"type": "string"},
            "message": {"type": "string"},
            "cli_available": {"type": "boolean"},
            "cli_path": {"type": "string"},
            "cli_version": {"type": "string"},
            "extension_root": {"type": "string"},
            "skills_dir": {"type": "string"},
            "items": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "raw_output": {"type": "string"},
            "installed_skill": {"type": ["object", "null"], "additionalProperties": True},
            "restart_required": {"type": "boolean"},
        },
    }


def _output_compression() -> ToolOutputCompressionConfig:
    return ToolOutputCompressionConfig(
        action_argument="action",
        actions={
            "status": ToolOutputCompressionActionConfig(
                schema=_status_compression_schema(),
                prompt=_skillhub_action_prompt("Keep CLI availability, path, version, extension root, and skills directory."),
            ),
            "search": ToolOutputCompressionActionConfig(
                schema=_search_compression_schema(),
                prompt=_skillhub_action_prompt(
                    "Compress SkillHUB search results into candidates. Preserve every candidate install_name exactly. "
                    "Do not merge install_name with version, title, summary, or punctuation. "
                    "Keep the highest-signal candidates for the query and include their version and short summary."
                ),
            ),
            "install": ToolOutputCompressionActionConfig(
                schema=_install_compression_schema(),
                prompt=_skillhub_action_prompt(
                    "Compress SkillHUB install output. Preserve installed_skill.skill_id and path exactly. "
                    "If installation failed, preserve the exact error text."
                ),
            ),
        },
    )


def _skillhub_action_prompt(action_prompt: str) -> str:
    return (
        "This is SkillHUB output. Preserve machine-installable skill names exactly. "
        "Never concatenate a skill name with its version. If a search candidate has install_name, "
        "copy that install_name verbatim and use it as the only value to pass to action=install. "
        + action_prompt
    )


def _status_compression_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "cli_available": {"type": "boolean"},
            "cli_path": {"type": "string"},
            "cli_version": {"type": "string"},
            "extension_root": {"type": "string"},
            "skills_dir": {"type": "string"},
            "insufficient": {"type": "boolean"},
            "read_original_reason": {"type": "string"},
        },
        "required": [
            "summary",
            "cli_available",
            "cli_path",
            "cli_version",
            "extension_root",
            "skills_dir",
            "insufficient",
            "read_original_reason",
        ],
    }


def _search_compression_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "query": {"type": "string"},
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "install_name": {"type": "string"},
                        "name": {"type": "string"},
                        "version": {"type": "string"},
                        "summary": {"type": "string"},
                        "score": {"type": "integer"},
                    },
                    "required": ["install_name", "name", "version", "summary", "score"],
                },
            },
            "selection_guidance": {"type": "string"},
            "insufficient": {"type": "boolean"},
            "read_original_reason": {"type": "string"},
        },
        "required": [
            "summary",
            "query",
            "candidates",
            "selection_guidance",
            "insufficient",
            "read_original_reason",
        ],
    }


def _install_compression_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "installed": {"type": "boolean"},
            "installed_skill_id": {"type": "string"},
            "installed_skill_path": {"type": "string"},
            "restart_required": {"type": "boolean"},
            "errors": {"type": "array", "items": {"type": "string"}},
            "insufficient": {"type": "boolean"},
            "read_original_reason": {"type": "string"},
        },
        "required": [
            "summary",
            "installed",
            "installed_skill_id",
            "installed_skill_path",
            "restart_required",
            "errors",
            "insufficient",
            "read_original_reason",
        ],
    }
