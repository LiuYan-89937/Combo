from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


MEMORY_STORE_RESOURCE = "memory_store"
RUNTIME_IDENTITY_RESOURCE = "runtime_identity"


def get_memory_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="memory",
            description=(
                "Search or list the current principal's user/workspace memories. "
                "The main runtime may also persist or delete a memory revision; temporary runtimes are read-only."
            ),
            entrypoint="agent_factory.tooling.builtins.memory.tool:run",
            input_schema=_input_schema(),
            output_schema={"type": "object"},
            resources={
                MEMORY_STORE_RESOURCE: MEMORY_STORE_RESOURCE,
                RUNTIME_IDENTITY_RESOURCE: RUNTIME_IDENTITY_RESOURCE,
            },
            risk_level="medium",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.tooling.builtins.memory.tool:evaluate_risk"
            ),
            concurrent=False,
            max_parallel_calls=1,
            effects=["read", "write", "delete"],
            system_available=True,
        )
    ]


def _input_schema() -> dict:
    scope = {"type": "string", "enum": ["user", "workspace"]}
    limit = {"type": "integer", "minimum": 1, "maximum": 100, "default": 20}
    return {
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "action": {"const": "search"},
                    "query": {"type": "string", "minLength": 1},
                    "limit": limit,
                },
                "required": ["action", "query"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "action": {"const": "list"},
                    "scope": scope,
                    "limit": limit,
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "action": {"const": "write"},
                    "scope": scope,
                    "kind": {
                        "type": "string",
                        "enum": ["constraint", "preference", "decision", "fact", "artifact"],
                    },
                    "content": {"type": "string", "minLength": 1},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 1},
                },
                "required": ["action", "scope", "kind", "content"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "action": {"const": "delete"},
                    "memory_id": {"type": "string", "minLength": 1},
                    "expected_revision": {"type": "integer", "minimum": 1},
                },
                "required": ["action", "memory_id", "expected_revision"],
                "additionalProperties": False,
            },
        ]
    }
