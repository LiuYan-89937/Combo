from __future__ import annotations

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


def build_create_agent_messages(
    state: Mapping[str, Any],
    tools: list[BaseTool],
    *,
    resource_set_store: ResourceSetStore | None = None,
    capability_inventory: dict[str, Any] | None = None,
) -> list[BaseMessage]:
    workspace = CreateAgentWorkspace(str(state["workspace_path"]), resource_set_store=resource_set_store)
    invariant_system = SystemMessage(content=_invariant_system_prompt_text())
    environment_system = SystemMessage(
        content=_stable_environment_prompt_text(
            tools=tools,
            capability_inventory=capability_inventory or {},
        )
    )
    dynamic_system = SystemMessage(
        content=_dynamic_system_context_text(
            state=state,
            workspace=workspace,
        )
    )
    return [
        invariant_system,
        environment_system,
        dynamic_system,
        *project_messages_for_prompt(list(state.get("messages") or []), workspace=workspace),
    ]


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
            "不要直接写 .factory/system_state.json。focus_files 是建议工作区，不是写入权限边界；"
            "当 validation evidence 需要跨文件修复时，可以修改非 focus 文件，但要根据 observation 中的 focus facts 自我校正。"
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
            "如果用户要求调整，继续按自然语言修改；如果用户确认发布，调用 create_agent_publish。"
        ),
        (
            "制造 skill 必须通过内置 skill gateway 渐进加载：先用 skill list/search/describe "
            "确定当前 focus 的候选 skill；候选 skill 不等于允许全部加载。"
            "同一 focus 默认只加载一个 primary skill 全文。"
            "skill load 必须携带 current_system 和 reason；current_system 是制造语义，不是硬阶段锁。需要第二个 skill 时必须先 describe，"
            "并在 reason 里说明当前 primary skill 为什么不够。"
        ),
        (
            "写某类 package 文件前，必须优先通过 skill 读取对应 schema/minimal example/repair hints。"
            "协议顺序固定为：skill describe(name, current_system) -> skill read_resource(name, path, current_system)。"
            "即使 validator 已给出 recommended_skill/recommended_resources，也必须先对同一个 current_system 调用 describe；"
            "不要直接 read_resource，不存在 read_source action。"
            "不要通过项目源码 inspect 或 shell 推断 schema。"
            "若 validation issue 包含 schema_path、invalid_value_path、expected_shape、repair_template 或 replace_strategy，"
            "必须优先按这些结构化字段修复，再对照 skill 的完整可执行示例。"
        ),
        (
            "通用 bash 不在 create-agent 默认工具集中。不要主动调用验证工具；"
            "完成一轮必要文件写入后停止工具调用，graph 会自动运行 validation gate。"
            "Package validator observation 中的 recommended_skill/recommended_resources 是下一步修复入口。"
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
            "focus_files 只表示建议文件，不限制 package 文件修复。"
            "如果 write/edit observation 中出现 outside_focus=true，检查 active_focus_id、target_focus_id 和 active_focus_files，"
            "确认这是 validator evidence 所需的跨文件修复；否则主动 set_focus 到更合适的 focus。"
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
    sections = [
        "Dynamic create-agent manufacturing context. This section changes across turns and must not be treated as stable policy.",
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
