from __future__ import annotations

from combo.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec
from combo.runtime_protocol.memory_operations import (
    MEMORY_WRITING_INSTRUCTIONS, DeleteMemory, MemoryDraft, MemorySelector,
    MergeMemories, UpdateMemory, WriteMemory,
)


MEMORY_STORE_RESOURCE = "memory_store"
RUNTIME_IDENTITY_RESOURCE = "runtime_identity"
MEMORY_TOOL_DESCRIPTION = (
    "Search or list memories visible to the current workspace and session; read a selected entry. "
    "Use write, update, merge, or delete to maintain them. " + MEMORY_WRITING_INSTRUCTIONS
)


def get_memory_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="memory",
            description=MEMORY_TOOL_DESCRIPTION,
            entrypoint="combo.tooling.builtins.memory.tool:run",
            input_schema=_input_schema(),
            output_schema={"type": "object"},
            resources={
                MEMORY_STORE_RESOURCE: MEMORY_STORE_RESOURCE,
                RUNTIME_IDENTITY_RESOURCE: RUNTIME_IDENTITY_RESOURCE,
            },
            risk_level="medium",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="combo.tooling.builtins.memory.tool:evaluate_risk"
            ),
            concurrent=False,
            max_parallel_calls=1,
            effects=["read", "write"],
            output_projection="passthrough",
            system_available=True,
        )
    ]


def _input_schema() -> dict:
    selector = MemorySelector.model_json_schema()
    branches = [
        {
            "type": "object", "additionalProperties": False,
            "properties": {
                "action": {"const": "search"},
                "query": {"type": "string", "minLength": 1,
                          "description": "The missing prior conclusion; do not copy tool output."},
                "scope": {"type": "string", "enum": ["workspace", "session"]},
                "kind": MemoryDraft.model_json_schema()["properties"]["kind"],
            },
            "required": ["action", "query"],
        },
        {
            "type": "object", "additionalProperties": False,
            "properties": {
                "action": {"const": "list"},
                "scope": {"type": "string", "enum": ["workspace", "session"]},
                "kind": MemoryDraft.model_json_schema()["properties"]["kind"],
                "offset": {"type": "integer", "minimum": 0},
            },
            "required": ["action"],
        },
        {
            "type": "object", "additionalProperties": False,
            "properties": {"action": {"const": "read"}, "memory": selector},
            "required": ["action", "memory"],
        },
    ]
    definitions = {}
    for model in (WriteMemory, UpdateMemory, MergeMemories, DeleteMemory):
        schema = model.model_json_schema()
        definitions.update(schema.pop("$defs", {}))
        schema["required"] = list(dict.fromkeys(["action", *schema.get("required", [])]))
        branches.append(schema)
    return {"oneOf": branches, "$defs": definitions}
