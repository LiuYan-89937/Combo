from __future__ import annotations

from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


COLLABORATION_TOOL_ID = "collaboration"


def get_collaboration_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id=COLLABORATION_TOOL_ID,
            description=(
                "多 Agent 协作工具。仅在用户消息提供 collaboration_id 的协作会话中使用。"
                "主 Agent 用它创建/更新/停止子任务、查看任务状态、读写协作共享工作区。"
                "create_task/update_task 声明 depends_on 后，系统会自动把前置任务 artifact_refs 授权给子 Agent，不需要手抄 input_artifacts。"
                "inspect 是状态同步动作；只有运行中任务且没有 submitted/blocked/failed 时，inspect 会返回轻量 deferred，主 Agent 应等待状态变化而不是连续查看。"
                "验收 worker 交付物时先 read_shared 读取 artifact_refs，再 update_task 为 completed 或 revision_requested。"
                "所有任务验收完成并形成最终答复后，用 complete_session 写入最终交付并结束协作会话。"
                "不要用它代替普通业务工具；启动 worker 由宿主协作调度器根据任务状态执行。"
            ),
            entrypoint="agent_factory.tooling.builtins.collaboration.tool:run",
            input_schema=_collaboration_input_schema(),
            output_schema={
                "type": "object",
                "properties": {
                    "action": {"type": "string"},
                    "status": {"type": "string"},
                    "message": {"type": "string"},
                    "session": {"type": "object", "additionalProperties": True},
                    "task": {"type": "object", "additionalProperties": True},
                    "active_tasks": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
                    "updated_at": {"type": "string"},
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "dispatch_hint": {"type": "string"},
                },
                "required": ["action", "status", "message"],
                "additionalProperties": False,
            },
            resources={"collaboration_root": "collaboration_root"},
            risk_level="medium",
            risk_evaluator=ToolRiskEvaluatorConfig(
                hard="agent_factory.tooling.builtins.collaboration.tool:evaluate_risk"
            ),
            concurrent=False,
        )
    ]


def _collaboration_input_schema() -> dict:
    common = {"collaboration_id": {"type": "string"}}
    flexible_object = {"type": "object", "additionalProperties": True}
    artifact_array = {
        "type": "array",
        "items": {
            "anyOf": [
                {"type": "string"},
                {"type": "object", "additionalProperties": True},
            ]
        },
    }
    task_status = {
        "type": "string",
        "enum": [
            "assigned",
            "queued",
            "accepted",
            "planning",
            "working",
            "blocked",
            "submitted",
            "revision_requested",
            "completed",
            "failed",
            "cancelled",
        ],
    }
    return {
        "oneOf": [
            _action_schema("inspect", common),
            _action_schema(
                "create_task",
                {
                    **common,
                    "assignee_package_id": {"type": "string"},
                    "task_text": {"type": "string"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "delivery_standard": flexible_object,
                    "visible_context": flexible_object,
                    "input_artifacts": artifact_array,
                },
                required=["assignee_package_id", "task_text", "delivery_standard"],
            ),
            _action_schema(
                "update_task",
                {
                    **common,
                    "task_id": {"type": "string"},
                    "status": task_status,
                    "task_text": {"type": "string"},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "delivery_standard": flexible_object,
                    "visible_context": flexible_object,
                    "input_artifacts": artifact_array,
                    "result_summary": {"type": "string"},
                    "review_notes": {"type": "string"},
                    "artifact_refs": artifact_array,
                },
                required=["task_id"],
            ),
            _action_schema(
                "cancel_task",
                {
                    **common,
                    "task_id": {"type": "string"},
                    "review_notes": {"type": "string"},
                    "result_summary": {"type": "string"},
                },
                required=["task_id"],
            ),
            _action_schema(
                "read_shared",
                {
                    **common,
                    "path": {"type": "string"},
                    "max_chars": {"type": "integer", "minimum": 1, "maximum": 1000000},
                },
                required=["path"],
            ),
            _action_schema(
                "write_shared",
                {
                    **common,
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                required=["path", "content"],
            ),
            _action_schema(
                "complete_session",
                {
                    **common,
                    "content": {"type": "string"},
                },
                required=["content"],
            ),
        ]
    }


def _action_schema(action: str, properties: dict, *, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": [action]},
            **properties,
        },
        "required": ["action", "collaboration_id", *(required or [])],
        "additionalProperties": False,
    }
