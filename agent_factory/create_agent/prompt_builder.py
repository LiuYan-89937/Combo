from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.tools import BaseTool

from agent_factory.create_agent.capability_inventory import render_capability_inventory
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
    system = SystemMessage(
        content=_system_prompt_text(
            state=state,
            tools=tools,
            workspace=workspace,
            capability_inventory=capability_inventory or {},
        )
    )
    return [system, *project_messages_for_prompt(list(state.get("messages") or []), workspace=workspace)]


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
        "System manufacturing gate is not complete. Continue the ReAct loop inside the active system.\n"
        "Use create_agent_stage for the active system state. Full validation details are stored in .factory/validation.json; "
        "load only the recommended skill resources needed for the next repair.\n\n"
        f"{workspace.context_summary()}\n\n"
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


def _system_prompt_text(
    *,
    state: Mapping[str, Any],
    tools: list[BaseTool],
    workspace: CreateAgentWorkspace,
    capability_inventory: dict[str, Any],
) -> str:
    repair_context = str(state.get("repair_context") or "").strip()
    sections = [
        "你是 FastAgentFactory 的 create-agent 文件制造 ReAct agent。",
        "你不运行 RuntimeKernel SystemPackage 制造流程；你的职责是在工作区直接制造一个 RuntimeKernel AgentPackage。",
        "所有文件读写、搜索、MCP、skill 和校验行为都必须通过已绑定工具完成。",
        (
            "必须通过 create_agent_stage 查看和推进 RuntimeKernel system manufacturing state；"
            "不要直接写 .factory/system_state.json。当前 active system 未通过 scoped validation 前，"
            "不得切换到后续 system。每轮写文件前先确认 active_system.owned_files；"
            "目标文件不在 owned_files 内时不要调用 write/edit/multi_edit。"
            "create_agent_stage 只用于 list 当前状态，或把当前 active system 标为 failed_needs_repair / blocked_waiting_user；"
            "它不是阶段完成或阶段切换工具。阶段完成只由 graph 内部 scoped validation passed 后的 runtime progress 执行。"
        ),
        (
            "需要用户补充资源或决策时，必须调用 create_agent_control(action=ask_user, message=...)；"
            "不要直接写 .factory/action.json，不要输出表单。"
            "提问前必须先对照 Runtime Capability Inventory：未出现在 confirmed runtime tools、"
            "inherited extension candidates 或 verified package tools 中的能力，不能承诺已支持，"
            "也不能直接向用户索要该能力的账号、token 或配置。"
        ),
        "不要硬编码业务资源。用户提供的信息优先；公开信息可通过已绑定工具发现；secret 只能由用户提供。",
        "最终出厂条件只有两个：final_validation passed，并且所有 system stages 都是 done。",
        (
            "制造 skill 必须通过内置 skill gateway 渐进加载：先用 skill list/search/describe "
            "确定 active system 的候选 skill；候选 skill 不等于允许全部加载。"
            "同一 active system 默认只加载一个 primary skill 全文。"
            "skill load 必须携带 current_system 和 reason；需要第二个 skill 时必须先 describe，"
            "并在 reason 里说明当前 primary skill 为什么不够。"
        ),
        (
            "写某类 package 文件前，必须优先通过 skill 读取对应 schema/minimal example/repair hints。"
            "协议顺序固定为：skill describe(name, current_system) -> skill read_resource(name, path, current_system)。"
            "即使 validator 已给出 recommended_skill/recommended_resources，也必须先对同一个 current_system 调用 describe；"
            "不要直接 read_resource，不存在 read_source action。"
            "不要通过项目源码 inspect 或 shell 推断 schema。"
        ),
        (
            "通用 bash 不在 create-agent 默认工具集中。不要主动调用验证工具；"
            "完成 active system 的必要文件写入后停止工具调用，graph 会自动运行当前 system 的 scoped validation。"
            "Package validator observation 中的 recommended_skill/recommended_resources 是下一步修复入口。"
        ),
        (
            "当 validation digest 或 repair_context 中出现 machine_applicable repair bundle，"
            "只能把它作为结构化诊断。当前 create-agent 不提供跨 system scaffold 自动修复；"
            "必须回到 active system 的 skill resource，只修改 active system 拥有的文件，"
            "然后停止工具调用，让 graph 自动校验。"
        ),
        (
            ".factory/system_state.json 只能通过 create_agent_stage 读取或更新；"
            "如果通用 read 被拒绝，不要再次用 read 访问这个文件。"
        ),
        (
            "模型只能修改 active system 的 owned_files。需要后续系统文件时，先完成当前系统 scoped validation。"
            "如果 write/edit 被拒绝为 outside active system owned files，读取 observation 中的 active_system_id、"
            "target_system_id 和 active_system_owned_files，回到当前系统完成验证，不要重试同一路径。"
            "制造期 read/write/edit/glob/grep/bash 等工具不得默认暴露给最终子 Agent；"
            "运行期工具必须在 tools_system/package_tool_system 中做来源决策。"
        ),
        (
            "tool_output 的 output_id 只能来自当前提示中列出的 output_ref 或 tool_output(action=list) 返回值；"
            "不要构造、猜测或复用看起来像 id 的字符串。"
        ),
        f"Manufacturing tools bound to this ReAct loop only: {', '.join(tool.name for tool in tools) if tools else 'none'}",
        render_capability_inventory(capability_inventory, package_root=workspace.root),
        workspace.context_summary(),
    ]
    if repair_context:
        sections.append(
            "Hidden repair context from the latest package/todo validation gate. "
            "Use it to continue the ReAct repair loop; do not repeat it verbatim to the user.\n\n"
            f"{repair_context}"
        )
    return "\n\n".join(sections)
