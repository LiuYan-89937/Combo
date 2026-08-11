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
    scope = {"type": "string", "enum": ["user", "workspace"], "description": "user 为用户全局记忆，workspace 为当前工作区记忆。"}
    limit = {"type": "integer", "minimum": 1, "maximum": 100, "default": 20, "description": "最多返回的记忆数量。"}
    return {
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "action": {"const": "search", "description": "按自然语言查询相关记忆。"},
                    "query": {"type": "string", "minLength": 1, "description": "需要检索的事实、偏好或决策。"},
                    "limit": limit,
                },
                "required": ["action", "query"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "action": {"const": "list", "description": "列出指定范围内的最新记忆。"},
                    "scope": scope,
                    "limit": limit,
                },
                "required": ["action"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "action": {"const": "write", "description": "创建一条新的跨会话记忆 revision。"},
                    "scope": scope,
                    "kind": {
                        "type": "string",
                        "enum": ["constraint", "preference", "decision", "fact", "artifact"],
                        "description": "记忆的语义类型。",
                    },
                    "content": {"type": "string", "minLength": 1, "description": "需要跨会话保留的独立、明确内容。"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1, "default": 1, "description": "对该记忆准确性的置信度。"},
                },
                "required": ["action", "scope", "kind", "content"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "action": {"const": "delete", "description": "按 revision 乐观锁删除指定记忆。"},
                    "memory_id": {"type": "string", "minLength": 1, "description": "要删除的真实 memory_id。"},
                    "expected_revision": {"type": "integer", "minimum": 1, "description": "调用方已读取的当前 revision，防止并发覆盖。"},
                },
                "required": ["action", "memory_id", "expected_revision"],
                "additionalProperties": False,
            },
        ]
    }
