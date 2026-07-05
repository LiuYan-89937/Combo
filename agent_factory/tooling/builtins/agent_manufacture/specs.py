from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


AGENT_MANUFACTURE_TOOL_ID = "agent_manufacture"


def get_agent_manufacture_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=AGENT_MANUFACTURE_TOOL_ID,
            description=(
                "多 Agent 协作中的新 Agent 制造委托工具。仅当 agent_search 没有返回可复用候选，"
                "且现有 Agent 不足以完成任务时使用。"
                "本工具只登记制造请求并交给宿主制造服务执行；不会检索 Agent。"
                "协作主 Agent 代理制造通过 full_static 后会自动物理发布 package；发布成功后 Agent Registry 会刷新，"
                "主 Agent 必须再次调用 agent_search 确认可用 package_id 后再创建子任务。"
            ),
            entrypoint="agent_factory.tooling.builtins.agent_manufacture.tool:run",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "collaboration_id": {"type": "string", "description": "当前协作会话 ID。"},
                    "agent_name": {"type": "string", "description": "希望制造的新 Agent 名称。"},
                    "purpose": {"type": "string", "description": "新 Agent 的清晰用途。"},
                    "target_tasks": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "新 Agent 需要承担的任务类型。",
                    },
                    "delivery_standards": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "可验收的交付标准。",
                    },
                    "reason_existing_agents_insufficient": {
                        "type": "string",
                        "description": "现有 Agent 不足的具体原因，必须来自 agent_search 结果判断。",
                    },
                    "preferred_pattern": {
                        "type": "string",
                        "enum": ["react_agent", "plan_and_execute"],
                        "description": "偏好的运行模式。",
                    },
                    "constraints": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "边界、限制或禁止事项。",
                    },
                    "source_agent_search": {
                        "type": "object",
                        "additionalProperties": True,
                        "description": "触发制造前的 agent_search 摘要，例如 query、status、候选不足原因。",
                    },
                },
                "required": [
                    "collaboration_id",
                    "agent_name",
                    "purpose",
                    "delivery_standards",
                    "reason_existing_agents_insufficient",
                ],
            },
            output_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "status": {"type": "string", "enum": ["requested", "running", "ready_for_publish", "failed"]},
                    "request_id": {"type": "string"},
                    "collaboration_id": {"type": "string"},
                    "create_agent_session_id": {"type": ["string", "null"]},
                    "message": {"type": "string"},
                    "next_step": {"type": "string"},
                },
                "required": ["status", "request_id", "collaboration_id", "message", "next_step"],
            },
            resources={"collaboration_root": "collaboration_root"},
            risk_level="medium",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.tooling.builtins.agent_manufacture.tool:evaluate_risk"
            ),
            concurrent=False,
        )
    ]
