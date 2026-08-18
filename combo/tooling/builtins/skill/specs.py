from __future__ import annotations

from combo.tooling.spec import ToolSpec


SKILL_RUNTIME_RESOURCE = "skill_runtime"


def get_skill_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="skill",
            description=(
                "Progressively load Skills available to this runtime. The main Agent may load an active Skill "
                "returned by capability search; temporary Agents may load only Skills selected in their immutable "
                "snapshot. Before loading a searched Skill, inspect that exact Skill with capability describe; for "
                "a Skill already listed in the runtime snapshot, use this tool's describe action. Load only the "
                "relevant SKILL.md, and read_resource only for a resource listed by describe or load. Skill loading "
                "affects this runtime only."
            ),
            entrypoint="combo.tooling.builtins.skill.tool:run",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["list", "describe", "load", "read_resource"]},
                    "name": {"type": "string", "description": "Exact Skill name from the short catalog or list result."},
                    "path": {"type": "string", "description": "Exact resource path returned by describe or load."},
                    "reason": {"type": "string", "description": "Why the full Skill instructions are needed now."},
                },
                "required": ["action"],
                "oneOf": [
                    {"properties": {"action": {"const": "list"}}, "required": ["action"]},
                    {"properties": {"action": {"const": "describe"}}, "required": ["action", "name"]},
                    {"properties": {"action": {"const": "load"}}, "required": ["action", "name", "reason"]},
                    {"properties": {"action": {"const": "read_resource"}}, "required": ["action", "name", "path"]},
                ],
            },
            output_schema={"type": "object"},
            resources={SKILL_RUNTIME_RESOURCE: SKILL_RUNTIME_RESOURCE},
            risk_level="low",
            concurrent=True,
            max_parallel_calls=4,
            effects=["read"],
            read_only=True,
            system_available=True,
        )
    ]
