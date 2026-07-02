from __future__ import annotations

from agent_factory.tooling.skillhub.constants import SKILLHUB_RUNTIME_RESOURCE
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


def get_skillhub_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="skillhub",
            description=(
                "Search SkillHUB, check the global SkillHUB CLI, or install a SkillHUB skill into "
                "this agent's active skills extension directory and enable it."
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
                "description": "Search terms for action=search.",
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
            "cli_path": {"type": ["string", "null"]},
            "cli_version": {"type": "string"},
            "extension_root": {"type": "string"},
            "skills_dir": {"type": "string"},
            "items": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
            "raw_output": {"type": "string"},
            "installed_skill": {"type": ["object", "null"], "additionalProperties": True},
            "restart_required": {"type": "boolean"},
        },
    }
