from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from collections.abc import Mapping
from typing import Any

from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.tools import BaseTool

from agent_factory.create_agent.capability_inventory import (
    render_dynamic_capability_context,
    render_static_capability_inventory,
)
from agent_factory.create_agent.prompt_context import project_messages_for_prompt
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.tooling.builtins.resource_set.resource_set import ResourceSetStore


@dataclass(frozen=True, slots=True)
class CreateAgentPromptPayload:
    messages: list[BaseMessage]
    diagnostics: dict[str, Any]


def build_create_agent_messages(
    state: Mapping[str, Any],
    tools: list[BaseTool],
    *,
    resource_set_store: ResourceSetStore | None = None,
    capability_inventory: dict[str, Any] | None = None,
) -> list[BaseMessage]:
    return build_create_agent_prompt(
        state,
        tools,
        resource_set_store=resource_set_store,
        capability_inventory=capability_inventory,
    ).messages


def build_create_agent_prompt(
    state: Mapping[str, Any],
    tools: list[BaseTool],
    *,
    resource_set_store: ResourceSetStore | None = None,
    capability_inventory: dict[str, Any] | None = None,
) -> CreateAgentPromptPayload:
    workspace = CreateAgentWorkspace(str(state["workspace_path"]), resource_set_store=resource_set_store)
    invariant_text = _invariant_system_prompt_text()
    stable_environment_text = _stable_environment_prompt_text(
        tools=tools,
        capability_inventory=capability_inventory or {},
    )
    stable_system_text = "\n\n".join([invariant_text, stable_environment_text])
    dynamic_system_text = _dynamic_system_context_text(
        state=state,
        workspace=workspace,
    )
    projected_messages = project_messages_for_prompt(list(state.get("messages") or []), workspace=workspace)
    stable_system = SystemMessage(content=stable_system_text)
    dynamic_system = SystemMessage(content=dynamic_system_text)
    messages = [
        stable_system,
        dynamic_system,
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


def validation_repair_context(*, workspace: CreateAgentWorkspace, report: Any, stage_progress: dict[str, Any] | None = None) -> str:
    digest = report.to_digest()
    issue_lines = [
        (
            f"- {issue.issue_id}: {issue.where}; files={issue.target_files}; "
            f"hint={issue.repair_hint}; skill={issue.recommended_skill}; resources={issue.recommended_resources}"
        )
        for issue in digest.issues
    ]
    repair_bundle_lines: list[str] = []
    for bundle in report.next_action.repair_bundles:
        repair_bundle_lines.append(
            json.dumps(
                {
                    "bundle_id": bundle.bundle_id,
                    "kind": bundle.kind,
                    "repair_action": bundle.repair_action,
                    "machine_applicable": bundle.machine_applicable,
                    "target_files": bundle.target_files,
                    "recommended_skill": bundle.recommended_skill,
                    "recommended_resources": bundle.recommended_resources,
                    "inputs": bundle.inputs,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    return (
        "Package validation is not complete. Continue the ReAct loop from the active focus.\n"
        "Use create_agent_stage(action='inspect') for focus state. Validator evidence may suggest a focus, "
        "but only your explicit create_agent_stage(action='set_focus', focus_id=..., reason=...) call changes it. "
        "Use create_agent_stage(action='inspect') to read the latest validation digest; do not read .factory/validation.json directly. "
        "Load only the recommended skill resources needed for the next repair.\n\n"
        f"Validation digest: {digest.status} | scope={digest.validation_scope} | {digest.summary}\n"
        + (
            "Stage progress: "
            + json.dumps(stage_progress, ensure_ascii=False, sort_keys=True)
            + "\n"
            if stage_progress
            else ""
        )
        + "\n".join(issue_lines)
        + ("\nMachine-applicable repair bundles:\n" + "\n".join(repair_bundle_lines) if repair_bundle_lines else "")
    )


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
            "调用 create_agent_control(action=finalize) 触发 full validation；"
            "full validation passed 后系统会向用户做发布前确认。"
            "发布确认阶段的用户输入仍是普通自然语言：问题先回答，修改请求再改文件，明确确认发布才调用 create_agent_publish。"
            "create_agent_publish 只有在发布确认 gate 记录到明确用户确认后才会通过；不要把修改意见当作发布确认。"
        ),
        (
            "空 AgentPackage 已由代码生成，是基础结构的唯一来源。不要读取 skill example 或 schema 来巡检 scaffold。"
            "你的职责是读取当前能力目标文件，根据用户需求做一个能力增量编辑，然后停止工具调用等待 validation。"
        ),
        (
            "skill gateway 只服务能力写法和 validator 修复。正常生产路径：describe 一个相关 skill，读取一个相关 capability example，"
            "然后开始写文件。schema 不是常规资料；只有 validator issue 指向 schema_path、example 缺少关键字段、"
            "或同一路径修复后再次失败时，才读取 schema fragment。full schema content 是最后手段，必须提供 reason。"
            "不要直接 read_resource，不存在 read_source action；不要通过项目源码 inspect 或 shell 推断 schema。"
        ),
        (
            "通用 bash 不在 create-agent 默认工具集中。不要主动调用验证工具；"
            "完成一轮必要文件写入后停止工具调用，graph 会自动运行 validation gate。"
            "Package validator observation 中的 recommended_skill/recommended_resources 是下一步修复入口。"
        ),
        (
            "当你新增或修改 package tool 后，必须使用 create_agent_probe_tool(action='inspect') 查看可探测工具，"
            "再用 create_agent_probe_tool(action='call', tool_id=..., arguments=...) 提供一次真实输入进行探测。"
            "工具行为证据来自真实 probe observation。"
            "如果 full validation 报 package_tool_probe issue，先 probe 或按 probe observation 修复工具，再停止工具调用等待 validation。"
        ),
        (
            "当 validation digest 或 repair_context 中出现 machine_applicable repair bundle，"
            "只能把它作为结构化诊断。当前 create-agent 不提供跨 system scaffold 自动修复；"
            "必须回到相关 focus 的 skill resource，按 validator evidence 修改必要文件，"
            "然后停止工具调用，让 graph 自动校验。"
        ),
        (
            ".factory/system_state.json 和 .factory/validation.json 只能通过 create_agent_stage inspect 获取摘要，不要直接读写；"
            "如果通用 read 被拒绝，不要再次用 read 访问这个文件。"
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
    workspace: CreateAgentWorkspace,
) -> str:
    repair_context = str(state.get("repair_context") or "").strip()
    publish_confirmation = _publish_confirmation_context(state.get("publish_confirmation_response"))
    sections = [
        "Dynamic create-agent manufacturing context. This section changes across turns and must not be treated as stable policy.",
        *([publish_confirmation] if publish_confirmation else []),
        render_dynamic_capability_context(package_root=workspace.root),
        workspace.context_summary(),
    ]
    if repair_context:
        sections.append(
            "Hidden repair context from the latest package/todo validation gate. "
            "Use it to continue the ReAct repair loop; do not repeat it verbatim to the user.\n\n"
            f"{repair_context}"
        )
    return "\n\n".join(sections)


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
