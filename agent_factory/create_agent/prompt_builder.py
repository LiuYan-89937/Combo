from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.tools import BaseTool

from agent_factory.create_agent.capability_inventory import (
    render_static_capability_inventory,
)
from agent_factory.create_agent.prompt_context import project_messages_for_prompt


@dataclass(frozen=True, slots=True)
class CreateAgentPromptPayload:
    messages: list[BaseMessage]
    diagnostics: dict[str, Any]


def build_create_agent_messages(
    state: Mapping[str, Any],
    tools: list[BaseTool],
    *,
    capability_inventory: dict[str, Any] | None = None,
) -> list[BaseMessage]:
    return build_create_agent_prompt(
        state,
        tools,
        capability_inventory=capability_inventory,
    ).messages


def build_create_agent_prompt(
    state: Mapping[str, Any],
    tools: list[BaseTool],
    *,
    capability_inventory: dict[str, Any] | None = None,
) -> CreateAgentPromptPayload:
    invariant_text = _invariant_system_prompt_text()
    stable_environment_text = _stable_environment_prompt_text(
        tools=tools,
        capability_inventory=capability_inventory or {},
    )
    stable_system_text = "\n\n".join([invariant_text, stable_environment_text])
    dynamic_system_text = _dynamic_system_context_text(state=state)
    projected_messages = project_messages_for_prompt(list(state.get("messages") or []))
    stable_system = SystemMessage(content=stable_system_text)
    messages = [
        stable_system,
        *([SystemMessage(content=dynamic_system_text)] if dynamic_system_text else []),
        *projected_messages,
    ]
    diagnostics = {
        "version": "create_agent_prompt_diagnostics.v0",
        "section_digests": {
            "invariant_system": _digest_text(invariant_text),
            "stable_environment": _digest_text(stable_environment_text),
            "stable_system": _digest_text(stable_system_text),
            "dynamic_system": _digest_text(dynamic_system_text),
            "projected_history": _digest_messages(projected_messages),
            "full_prompt_projection": _digest_messages(messages),
        },
        "section_lengths": {
            "invariant_system_chars": len(invariant_text),
            "stable_environment_chars": len(stable_environment_text),
            "stable_system_chars": len(stable_system_text),
            "dynamic_system_chars": len(dynamic_system_text),
            "projected_history_messages": len(projected_messages),
            "projected_history_chars": sum(len(_message_content_text(message)) for message in projected_messages),
        },
        "tool_names_digest": _digest_json(_stable_tool_names(tools)),
        "tool_count": len(tools),
        "message_count": len(messages),
    }
    return CreateAgentPromptPayload(
        messages=messages,
        diagnostics=diagnostics,
    )


def _digest_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _digest_json(value: Any) -> str:
    return _digest_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _digest_messages(messages: list[BaseMessage]) -> str:
    return _digest_json(
        [
            {
                "type": message.__class__.__name__,
                "content": _message_content_text(message),
                "name": str(getattr(message, "name", "") or ""),
            }
            for message in messages
        ]
    )


def _message_content_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(content)


def _invariant_system_prompt_text() -> str:
    sections = [
        "你是 FastAgentFactory 的 create-agent 文件制造 ReAct agent。",
        "你不运行 RuntimeKernel SystemPackage 制造流程；你的职责是在工作区直接制造一个 RuntimeKernel AgentPackage。",
        "所有文件读写、搜索、MCP、skill 和校验行为都必须通过已绑定工具完成。",
        (
            "必须通过 create_agent_stage(action='inspect') 查看制造 focus；"
            "需要切换阶段时，只有你可以显式调用 create_agent_stage(action='set_focus', focus_id=..., reason=...)。"
            "validator 只提供证据和建议，不会自动推进或回退 focus。"
            "不要直接写 .factory/system_state.json。active focus target files 是读取边界；"
            "baseline scaffold 和 baseline contracts 只由代码生成和 validator 负责，不由你逐个审计。"
        ),
        (
            "需要用户补充资源或决策时，必须调用 create_agent_control(action=ask_user, message=...)；"
            "不要直接写 .factory/action.json，不要输出表单。"
            "提问前必须先对照 Runtime Capability Inventory：未出现在 confirmed runtime tools、"
            "inherited extension candidates 或 verified package tools 中的能力，不能承诺已支持，"
            "也不能直接向用户索要该能力的账号、token 或配置。"
        ),
        "不要硬编码业务资源。用户提供的信息优先；公开信息可通过已绑定工具发现；secret 只能由用户提供。",
        (
            "最终出厂流程固定为：当前 focus 是 validation_publish；"
            "先显式调用 create_agent_validate(scope='full_static', reason=...)；"
            "full_static validation passed 后再调用 create_agent_control(action=finalize)，系统会向用户做发布前确认。"
            "发布确认阶段的用户输入仍是普通自然语言：问题先回答，修改请求再改文件，明确确认发布才调用 create_agent_publish。"
            "create_agent_publish 只有在发布确认 gate 记录到明确用户确认后才会通过；不要把修改意见当作发布确认。"
        ),
        (
            "空 AgentPackage 已由代码生成，是基础结构的唯一来源。不要读取 skill example 或 schema 来巡检 scaffold。"
            "你的职责是读取当前能力目标文件，根据用户需求做一个能力增量编辑，然后显式调用 create_agent_validate。"
        ),
        (
            "skill gateway 只服务能力写法和 validator 修复。正常生产路径：describe 一个相关 skill，读取一个相关 capability example，"
            "然后开始写文件。schema 不是常规资料；只有 validator issue 指向 schema_path、example 缺少关键字段、"
            "或同一路径修复后再次失败时，才读取 schema fragment。full schema content 是最后手段，必须提供 reason。"
            "不要直接 read_resource，不存在 read_source action；不要通过项目源码 inspect 或 shell 推断 schema。"
        ),
        (
            "通用 bash 不在 create-agent 默认工具集中。系统不会自动运行 validator。"
            "完成一组连贯文件修改后，必须显式调用 create_agent_validate(scope='current_focus', reason=...)。"
            "create_agent_validate 的 tool observation 是 validator evidence；不要等待 graph 自动 validation。"
        ),
        (
            "当你新增或修改 package tool 后，必须使用 create_agent_probe_tool(action='inspect') 查看可探测工具，"
            "再用 create_agent_probe_tool(action='call', tool_id=..., probe_kind='success_path', arguments=..., prompt=..., tool_goal=...) 进行真实工具探测。"
            "arguments 是目标 package tool 的真实调用输入；如果你暂时只提供 prompt，probe 只会用 task_model 做一次短的参数推断，"
            "随后仍由系统直接通过 ToolExecutionGateway 执行目标工具。"
            "工具行为证据来自真实 arguments、ToolExecutionGateway observation、工具输出和可选的小模型摘要。"
            "错误路径 probe 只能作为补充证据；final validation 要求每个 package tool 至少有一次 fresh success-path probe。"
            "如果 full validation 报 package_tool_probe issue，先 probe 或按 probe observation 修复工具，再显式调用 create_agent_validate。"
            "如果 package tool 源码 import 了非 stdlib、非 package-local、非 agent_factory 的 Python 模块，"
            "必须同步更新 contracts/dependencies.json 的 config.python_requirements。"
        ),
        (
            "MCP inherited candidate 不需要额外继承工具调用。"
            "如果 produced Agent 需要使用某个 inherited MCP 工具，把该工具 id 加入 assembly_spec 的 tool_access.allowed_tool_ids，"
            "系统会在 full_static validation/publish 前自动把对应 MCP server 配置写入 package extensions。"
        ),
        (
            "validator evidence 只来自 create_agent_validate tool observation 或 create_agent_stage inspect 的 latest validation digest。"
            "当前 create-agent 不提供跨 system scaffold 自动修复；必须由你按 validator evidence 修改必要文件，"
            "然后再次显式调用 create_agent_validate。"
        ),
        (
            ".factory/system_state.json、.factory/task_analysis.json 和 .factory/validation.json 只能通过 create_agent_stage inspect 获取摘要，不要直接读写；"
            ".factory/action.json 和 .factory/publish_decision.json 只能通过 create_agent_control(action='inspect') 获取摘要。"
            "如果通用 read 被拒绝，不要再次用 read 访问 managed file。"
        ),
        (
            "不要读取 contracts/ 进行全量巡检。只读取 active focus target files 或 validator issue target_files。"
            "如果 write/edit observation 中出现 outside_focus=true，只有 validator evidence 指向该文件时才继续。"
            "制造期 read/write/edit/glob/grep/bash 等工具不得默认暴露给最终子 Agent；"
            "运行期工具必须在 tools_system/package_tool_system 中做来源决策。"
        ),
        (
            "tool_output 的 output_id 只能来自当前提示中列出的 output_ref 或 tool_output(action=list) 返回值；"
            "不要构造、猜测或复用看起来像 id 的字符串。"
        ),
    ]
    return "\n\n".join(sections)


def _stable_environment_prompt_text(
    *,
    tools: list[BaseTool],
    capability_inventory: dict[str, Any],
) -> str:
    sections = [
        "Stable create-agent manufacturing environment. This section should change only when configured tools or extension inventory changes.",
        f"Manufacturing tools bound to this ReAct loop only: {', '.join(_stable_tool_names(tools)) or 'none'}",
        render_static_capability_inventory(capability_inventory),
    ]
    return "\n\n".join(sections)


def _dynamic_system_context_text(
    *,
    state: Mapping[str, Any],
) -> str:
    publish_confirmation = _publish_confirmation_context(state.get("publish_confirmation_response"))
    task_analysis = _task_analysis_context(state)
    return "\n\n".join(item for item in [task_analysis, publish_confirmation] if item)


def _task_analysis_context(state: Mapping[str, Any]) -> str:
    workspace_path = str(state.get("workspace_path") or "").strip()
    if not workspace_path:
        return ""
    path = Path(workspace_path) / ".factory" / "task_analysis.json"
    if not path.is_file():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    selected_pattern_id = str(payload.get("selected_pattern_id") or "").strip()
    return (
        "Create-agent task analysis completed before scaffolding:\n"
        f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}\n"
        "The selected_pattern_id is the authoritative baseline runtime pattern for this workspace. "
        "If package files do not match it, repair agent_package.json, assembly_spec.json, and render_manifest.json before adding unrelated capability work."
        + (
            " For plan_and_execute, configure planner, executor, final_answer, and runtime_plan bindings instead of encoding dynamic planning only in a single react prompt."
            if selected_pattern_id == "plan_and_execute"
            else ""
        )
    )


def _stable_tool_names(tools: list[BaseTool]) -> list[str]:
    return sorted(str(tool.name) for tool in tools)


def _publish_confirmation_context(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    decision = str(value.get("decision") or "").strip()
    input_text = str(value.get("input_text") or "").strip()
    instruction = str(value.get("instruction") or "").strip()
    if not decision and not input_text:
        return ""
    if decision == "approve":
        return (
            "High-priority publish confirmation response:\n"
            f"- decision: approve\n"
            f"- user_input: {input_text}\n"
            "- next_required_action: call create_agent_publish if publish readiness still holds."
        )
    return (
        "High-priority publish confirmation response:\n"
        "- decision: pending\n"
        f"- user_input: {input_text}\n"
        f"- instruction: {instruction or 'Treat user_input as the user latest message, not as an automatic package modification request.'}\n"
        "- next_required_action: do not publish. If user_input is a question, answer it from current package evidence; if it asks for changes, modify then validate."
    )
