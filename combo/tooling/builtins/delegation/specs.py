from __future__ import annotations

from combo.tooling.spec import ToolLoopPolicyConfig, ToolSpec


DELEGATION_RUNTIME_RESOURCE = "delegation_runtime"
DELEGATION_TOOL_IDS = frozenset({"delegate", "delegation_status"})
DELEGATION_CAPABILITY_IDS = frozenset(
    f"tool://builtin/{tool_id}" for tool_id in DELEGATION_TOOL_IDS
)


def get_delegation_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="delegate",
            description=(
                "Start one non-blocking temporary agent task. Give the child a concise user-facing role name, "
                "then describe its role and objective and select its execution graph. Delegate independent work "
                "even when capability search returns no optional match; in that case pass an empty capabilities "
                "array and the child receives its stable built-in runtime tools. When search does return useful "
                "Tool, MCP, or Skill matches, pass only their exact public names. Runtime policy "
                "supplies the shared workspace scope, selects and freezes a suitable enabled model-pool profile, "
                "and owns approvals and internal identities. Once accepted, "
                "do not immediately inspect status, sleep, wait, or poll; task events report subsequent changes."
            ),
            entrypoint="combo.tooling.builtins.delegation.tool:run",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "agent_name": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 40,
                        "description": (
                            "A concise task-specific role name shown in the task capsule, such as Researcher "
                            "or Presentation Designer. Never use a generic Temporary Agent label."
                        ),
                    },
                    "strategy": {
                        "type": "string",
                        "enum": ["react", "plan_and_execute"],
                        "description": "Execution graph selected by the main agent for this child task.",
                    },
                    "system_prompt": {"type": "string", "minLength": 1, "description": "该临时 Agent 的职责、边界和工作方式，不要重复用户全部上下文。"},
                    "objective": {"type": "string", "minLength": 1, "description": "需要临时 Agent 独立完成的具体目标和预期交付物。"},
                    "capabilities": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "description": (
                                "An exact public Tool, MCP, or Skill name returned by capability search. "
                                "Never provide IDs, revisions, digests, evidence, or generated handles."
                            ),
                        },
                        "uniqueItems": True,
                        "default": [],
                        "description": (
                            "Optional public capability names selected from capability search. Use an empty array "
                            "when no optional match is needed; stable built-in tools remain available."
                        ),
                    },
                    "acceptance_criteria": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "uniqueItems": True,
                        "default": [],
                        "description": "判断临时任务是否完成的可验证条件。",
                    },
                },
                "required": ["agent_name", "strategy", "system_prompt", "objective", "capabilities"],
            },
            output_schema={"type": "object"},
            resources={DELEGATION_RUNTIME_RESOURCE: DELEGATION_RUNTIME_RESOURCE},
            risk_level="medium",
            concurrent=True,
            max_parallel_calls=8,
            effects=["external_side_effect"],
            system_available=True,
            loop_policy=ToolLoopPolicyConfig(max_calls=20, max_identical_calls=1),
        ),
        ToolSpec(
            id="delegation_status",
            description=(
                "Inspect all temporary agent tasks in the current conversation. No internal task or runtime "
                "identifier is required; match tasks by their objective and returned order. Use this for an "
                "explicit progress request or after a completion notification, not as a polling loop."
            ),
            entrypoint="combo.tooling.builtins.delegation.tool:status",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            },
            output_schema={"type": "object"},
            resources={DELEGATION_RUNTIME_RESOURCE: DELEGATION_RUNTIME_RESOURCE},
            risk_level="low",
            concurrent=True,
            max_parallel_calls=8,
            effects=["read"],
            read_only=True,
            system_available=True,
            loop_policy=ToolLoopPolicyConfig(max_calls=50, max_identical_calls=1),
        ),
    ]
