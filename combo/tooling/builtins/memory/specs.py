from __future__ import annotations

from combo.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


MEMORY_STORE_RESOURCE = "memory_store"
RUNTIME_IDENTITY_RESOURCE = "runtime_identity"


def get_memory_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="memory",
            description=(
                "Persist one durable user or workspace memory when the current turn establishes a reusable "
                "constraint, preference, decision, fact, or artifact. Cross-session retrieval is supplied "
                "automatically by the context system; do not use this tool to search or list memories."
            ),
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
            effects=["write"],
            system_available=True,
        )
    ]


def _input_schema() -> dict:
    scope = {"type": "string", "enum": ["user", "workspace"], "description": "user 为用户全局记忆，workspace 为当前工作区记忆。"}
    return {
        "type": "object",
        "properties": {
            "action": {"const": "write", "description": "创建一条新的跨会话记忆 revision。"},
            "scope": scope,
            "kind": {
                "type": "string",
                "enum": ["constraint", "preference", "decision", "fact", "artifact"],
                "description": "记忆的语义类型。",
            },
            "content": {
                "type": "string",
                "minLength": 1,
                "description": "需要跨会话保留的独立、明确内容。",
            },
            "confidence": {
                "type": "number",
                "minimum": 0,
                "maximum": 1,
                "default": 1,
                "description": "对该记忆准确性的置信度。",
            },
        },
        "required": ["action", "scope", "kind", "content"],
        "additionalProperties": False,
    }
