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
                "share_files/ 是 worker 工作区中的只读上游材料目录，只接收系统复制的前置产物；不要要求 worker 把交付物写入 share_files/。"
                "worker 交付物应写入当前工作区普通路径，宿主会自动收集为 artifact_refs。visible_context 只表示文本上下文，不授权文件读取。"
                "inspect 是状态同步动作；只有运行中任务且没有 submitted/blocked/failed 时，inspect 会返回轻量 deferred，主 Agent 应等待状态变化而不是连续查看。"
                "验收 worker 交付物时使用 read_task_artifacts 并传 task_id，由宿主解析权威 artifact_refs；"
                "read_shared 仅用于读取已知的普通共享路径。验收后 update_task 为 completed 或 revision_requested。"
                "需要重跑 failed/revision_requested/cancelled 任务时必须使用 retry_task；宿主会原子替换旧任务并清理旧 worker 会话，禁止另行 create_task。"
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
                    "artifacts": {
                        "type": "array",
                        "items": {"type": "object", "additionalProperties": True},
                    },
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
    flexible_object = {"type": "object", "additionalProperties": True}
    delivery_standard = {
        "type": "object",
        "description": (
            "可执行的交付契约。至少提供 output_path 或非空 output_paths；路径必须是 worker 工作区内的安全相对路径，"
            "且不得位于 share_files/。runtime 正常结束后，指定文件必须由本轮新建或修改。"
        ),
        "properties": {
            "format": {"type": "string"},
            "output_path": {"type": "string", "minLength": 1},
            "output_paths": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
            "required_fields": {
                "type": "array",
                "description": (
                    "对真实交付文件执行的字段验收规则。文本报告使用 markdown_section，JSON 使用 json_pointer；"
                    "需要数值、列表或表格数据时必须选择对应 value_type 并设置 minimum_items，不能只声明标题。"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "minLength": 1},
                        "path": {"type": "string", "minLength": 1},
                        "selector": {
                            "type": "string",
                            "enum": ["document", "markdown_section", "json_pointer"],
                        },
                        "selector_value": {"type": "string", "minLength": 1},
                        "value_type": {
                            "type": "string",
                            "enum": ["text", "number", "list", "table", "object"],
                        },
                        "minimum_chars": {"type": "integer", "minimum": 1},
                        "minimum_items": {"type": "integer", "minimum": 1},
                        "contains_all": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                        },
                        "contains_any": {
                            "type": "array",
                            "items": {"type": "string", "minLength": 1},
                        },
                    },
                    "required": ["name", "selector", "value_type"],
                    "additionalProperties": False,
                },
            },
            "require_visible_result": {"type": "boolean"},
            "minimum_visible_chars": {"type": "integer", "minimum": 1},
        },
        "additionalProperties": False,
    }
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
    actions = [
        "inspect",
        "create_task",
        "update_task",
        "retry_task",
        "cancel_task",
        "read_shared",
        "read_task_artifacts",
        "write_shared",
        "complete_session",
    ]
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": actions},
            "collaboration_id": {"type": "string"},
            "assignee_package_id": {"type": "string"},
            "task_text": {"type": "string"},
            "depends_on": {"type": "array", "items": {"type": "string"}},
            "delivery_standard": delivery_standard,
            "visible_context": flexible_object,
            "input_artifacts": artifact_array,
            "task_id": {"type": "string"},
            "status": task_status,
            "result_summary": {"type": "string"},
            "review_notes": {"type": "string"},
            "retry_guidance": {"type": "string"},
            "artifact_refs": artifact_array,
            "path": {"type": "string"},
            "max_chars": {"type": "integer", "minimum": 1, "maximum": 1000000},
            "content": {"type": "string"},
        },
        "required": ["action", "collaboration_id"],
        "allOf": [
            _action_requirements(
                "create_task",
                ["assignee_package_id", "task_text", "delivery_standard"],
            ),
            _action_requirements("update_task", ["task_id"]),
            _action_requirements("retry_task", ["task_id"]),
            _action_requirements("cancel_task", ["task_id"]),
            _action_requirements("read_shared", ["path"]),
            _action_requirements("read_task_artifacts", ["task_id"]),
            _action_requirements("write_shared", ["path", "content"]),
            _action_requirements("complete_session", ["content"]),
        ],
        "additionalProperties": False,
    }


def _action_requirements(action: str, required: list[str]) -> dict:
    return {
        "if": {
            "properties": {"action": {"const": action}},
            "required": ["action"],
        },
        "then": {"required": required},
    }
