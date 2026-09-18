from __future__ import annotations

from combo.tooling.spec import ToolSpec


SKILL_RUNTIME_RESOURCE = "skill_runtime"
SKILL_TOOL_DESCRIPTION = (
    "Load relevant Skills on demand. For a Skill already named in the selected capability catalog or skill list, "
    "call action=load with its exact name directly; list and describe are optional metadata inspection, "
    "not prerequisites. For a Skill discovered through capability search, use capability action=describe "
    "to obtain its exact definition before loading, unless that definition is already in context. "
    "load returns the SKILL.md body; read_resource only reads a path listed by describe or load. "
    "Do not reload instructions already present in the current context. Main Agents may load active searched "
    "Skills; child Agents may load only Skills selected for their runtime. Loading affects this runtime only."
)


def get_skill_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="skill",
            description=SKILL_TOOL_DESCRIPTION,
            entrypoint="combo.tooling.builtins.skill.tool:run",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "action": {"type": "string", "enum": ["list", "describe", "load", "read_resource"]},
                    "name": {"type": "string", "description": "Exact Skill name from the short catalog or list result."},
                    "path": {"type": "string", "description": "Exact resource path returned by describe or load."},
                },
                "required": ["action"],
                "oneOf": [
                    {"properties": {"action": {"const": "list"}}, "required": ["action"]},
                    {"properties": {"action": {"const": "describe"}}, "required": ["action", "name"]},
                    {"properties": {"action": {"const": "load"}}, "required": ["action", "name"]},
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
