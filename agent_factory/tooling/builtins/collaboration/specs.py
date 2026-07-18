from __future__ import annotations

from agent_factory.collaboration_system.activity import (
    MAX_INSPECT_ACTIVITY_LIMIT,
    MAX_INSPECT_ACTIVITY_MAX_CHARS,
    MIN_INSPECT_ACTIVITY_LIMIT,
    MIN_INSPECT_ACTIVITY_MAX_CHARS,
)
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
                "delivery_standard 由主 Agent 根据子 Agent 能力动态声明产物路径和语义验收标准；宿主只验证文件确由本轮产生且非空，内容是否达标由主 Agent 读取产物后决定。"
                "share_files/ 是 worker 工作区中的只读上游材料目录，只接收系统复制的前置产物；不要要求 worker 把交付物写入 share_files/。"
                "worker 交付物应写入当前工作区普通路径，宿主会自动收集为 artifact_refs。visible_context 只表示文本上下文，不授权文件读取。"
                "inspect 是状态同步动作；只有运行中任务且没有 submitted/blocked/failed 时，inspect 会返回各活跃任务近期的公开思考摘要与协作动态，"
                "并以轻量 deferred 提醒主 Agent 等待状态变化而不是连续查看。"
                "验收 worker 交付物时使用 read_task_artifacts 并传 task_id，由宿主解析权威 artifact_refs；"
                "blocked 任务包含 pending_approval 时，主 Agent 必须根据任务目标、工具参数和风险调用 resolve_task_approval，"
                "明确批准、拒绝或要求修改；宿主随后恢复原 worker。"
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
                    "response_guidance": {"type": "string"},
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
                    "approval": {"type": "object", "additionalProperties": True},
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
            "可执行的交付契约。至少提供 output_path、非空 output_paths 或 artifacts；路径必须是 worker 工作区内的安全相对路径，"
            "且不得位于 share_files/。路径直接相对于工作区根目录，不得添加工作区名称、宿主路径或容器挂载路径前缀。"
            "runtime 正常结束后，指定文件必须由本轮新建或修改且非空。acceptance_criteria 由主 Agent 在读取实际产物后执行语义验收。"
        ),
        "properties": {
            "format": {"type": "string"},
            "output_path": {"type": "string", "minLength": 1},
            "output_paths": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "artifacts": {
                "type": "array",
                "description": (
                    "产物声明。description 说明该文件应该交付什么；宿主只验证 path 对应文件由本轮产生且非空。"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "minLength": 1},
                        "kind": {
                            "type": "string",
                            "enum": ["markdown", "json", "text", "binary"],
                        },
                        "description": {"type": "string", "minLength": 1},
                    },
                    "required": ["path", "description"],
                    "additionalProperties": False,
                },
            },
            "acceptance_criteria": {
                "type": "array",
                "description": (
                    "主 Agent 基于任务目标和子 Agent 能力制定的语义验收标准。worker 提交后，主 Agent 必须读取真实产物逐项判断；"
                    "宿主不做关键词、章节或 JSON Schema 内容判定。"
                ),
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
        },
        "required": ["acceptance_criteria"],
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
        "resolve_task_approval",
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
            "decision": {"type": "string", "enum": ["approve", "deny", "revise"]},
            "decision_reason": {"type": "string", "minLength": 1},
            "revision_guidance": {"type": "string", "minLength": 1},
            "artifact_refs": artifact_array,
            "path": {"type": "string"},
            "max_chars": {"type": "integer", "minimum": 1, "maximum": 1000000},
            "recent_activity_limit": {
                "type": "integer",
                "minimum": MIN_INSPECT_ACTIVITY_LIMIT,
                "maximum": MAX_INSPECT_ACTIVITY_LIMIT,
                "description": "inspect 返回的全部活跃任务近期动态总条数。",
            },
            "recent_activity_max_chars": {
                "type": "integer",
                "minimum": MIN_INSPECT_ACTIVITY_MAX_CHARS,
                "maximum": MAX_INSPECT_ACTIVITY_MAX_CHARS,
                "description": "inspect 返回的全部活跃任务近期动态总字符预算。",
            },
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
            _action_requirements("resolve_task_approval", ["task_id", "decision", "decision_reason"]),
            {
                "if": {
                    "properties": {
                        "action": {"const": "resolve_task_approval"},
                        "decision": {"const": "revise"},
                    },
                    "required": ["action", "decision"],
                },
                "then": {"required": ["revision_guidance"]},
            },
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
