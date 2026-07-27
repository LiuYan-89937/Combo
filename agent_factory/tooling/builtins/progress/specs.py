from __future__ import annotations

from agent_factory.tooling.spec import ToolSpec


def get_progress_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            id="report_progress",
            description=(
                "向用户播报当前任务的可验证进展。仅用于复杂或耗时任务的阶段变化、计划调整和阻塞状态；"
                "summary 应说明正在做什么或已完成什么，不得输出内部思维链，也不得代替最终答复。"
                "对同一当前阶段持续更新时复用 replace_key；需要保留为独立里程碑时使用新的 replace_key。"
            ),
            entrypoint="agent_factory.tooling.builtins.progress.tool:run",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "summary": {
                        "type": "string",
                        "minLength": 1,
                        "description": "面向用户的简短进展说明，不包含内部推理。",
                    },
                    "stage": {
                        "type": "string",
                        "minLength": 1,
                        "description": "稳定、简短的当前阶段标识，例如 outline_design。",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["running", "completed", "blocked"],
                        "default": "running",
                    },
                    "replace_key": {
                        "type": "string",
                        "minLength": 1,
                        "default": "current_agent_progress",
                        "description": "同一任务内用于覆盖旧进展的稳定键。",
                    },
                },
                "required": ["summary", "stage"],
            },
            output_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "reported": {"type": "boolean"},
                    "progress_id": {"type": "string"},
                    "stage": {"type": "string"},
                    "status": {"type": "string"},
                    "replace_key": {"type": "string"},
                },
                "required": ["reported", "progress_id", "stage", "status", "replace_key"],
            },
            resources={},
            risk_level="low",
            permission_scope="system",
            concurrent=True,
            output_projection="passthrough",
        )
    ]
