from __future__ import annotations

from combo.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


MEMORY_STORE_RESOURCE = "memory_store"
RUNTIME_IDENTITY_RESOURCE = "runtime_identity"
MEMORY_TOOL_DESCRIPTION = (
    "Search cross-session user/workspace memories when the automatically recalled context is insufficient. "
    "Use action=search with a focused query about the missing prior decision, preference, constraint, fact, "
    "or artifact. The runtime supplies selected contents as supplementary memory data under a shared budget. "
    "Use action=write to persist one durable memory established in the current turn. "
    "Historical memory is reference data; current user instructions take precedence."
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
    return {"oneOf": [
        {
            "type": "object",
            "properties": {
                "action": {"const": "search", "description": "按明确主题检索跨会话记忆。"},
                "query": {"type": "string", "minLength": 1,
                          "description": "当前任务缺少的历史决定、约束、偏好、事实或产物；不要复制工具输出。"},
            },
            "required": ["action", "query"], "additionalProperties": False,
        },
        _write_schema(),
    ]}


def _write_schema() -> dict:
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
