from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from langchain_core.messages import BaseMessage, SystemMessage
from langchain_core.tools import BaseTool

from agent_factory.create_agent.prompt_context import project_messages_for_prompt
from agent_factory.create_agent.workspace import CreateAgentWorkspace
from agent_factory.tooling.builtins.resource_set.resource_set import ResourceSetStore


def build_create_agent_messages(
    state: Mapping[str, Any],
    tools: list[BaseTool],
    *,
    resource_set_store: ResourceSetStore | None = None,
) -> list[BaseMessage]:
    workspace = CreateAgentWorkspace(str(state["workspace_path"]), resource_set_store=resource_set_store)
    system = SystemMessage(content=_system_prompt_text(state=state, tools=tools, workspace=workspace))
    return [system, *project_messages_for_prompt(list(state.get("messages") or []), workspace=workspace)]


def validation_repair_context(*, workspace: CreateAgentWorkspace, report: Any) -> str:
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
        "Package validation/todo gate is not complete. Continue the ReAct loop.\n"
        "Use create_agent_todo for the active working set. Full validation details are stored in .factory/validation.json; "
        "load only the recommended skill resources needed for the next repair.\n\n"
        f"{workspace.context_summary()}\n\n"
        f"Validation digest: {digest.status} | scope={digest.validation_scope} | {digest.summary}\n"
        + "\n".join(issue_lines)
        + ("\nMachine-applicable repair bundles:\n" + "\n".join(repair_bundle_lines) if repair_bundle_lines else "")
    )


def _system_prompt_text(*, state: Mapping[str, Any], tools: list[BaseTool], workspace: CreateAgentWorkspace) -> str:
    repair_context = str(state.get("repair_context") or "").strip()
    sections = [
        "你是 FastAgentFactory 的 create-agent 文件制造 ReAct agent。",
        "你不运行 RuntimeKernel SystemPackage 制造流程；你的职责是在工作区直接制造一个 RuntimeKernel AgentPackage。",
        "所有文件读写、搜索、MCP、skill 和校验行为都必须通过已绑定工具完成。",
        (
            "必须通过 create_agent_todo 维护制造 todo；不要直接写 .factory/todo.json。"
            "todo 未全部完成或 package 校验未通过时，必须继续制造或修复。"
        ),
        (
            "需要用户补充资源或决策时，必须调用 create_agent_control(action=ask_user, message=...)；"
            "不要直接写 .factory/action.json，不要输出表单。"
        ),
        "不要硬编码业务资源。用户提供的信息优先；公开信息可通过已绑定工具发现；secret 只能由用户提供。",
        "最终出厂条件只有两个：Package validation passed，并且所有 required todo 都是 done。",
        (
            "制造 skill 必须通过内置 skill gateway 渐进加载：先用 skill list/search/describe "
            "确定 active todo 的候选 skill；候选 skill 不等于允许全部加载。"
            "同一 active todo 默认只加载一个 primary skill 全文。"
            "skill load 必须携带 current_todo 和 reason；需要第二个 skill 时必须先 describe，"
            "并在 reason 里说明当前 primary skill 为什么不够。"
        ),
        (
            "写某类 package 文件前，必须优先通过 skill 读取对应 schema/minimal example/repair hints。"
            "协议顺序固定为：skill describe(name, current_todo) -> skill read_resource(name, path, current_todo)。"
            "即使 validator 已给出 recommended_skill/recommended_resources，也必须先对同一个 current_todo 调用 describe；"
            "不要直接 read_resource，不存在 read_source action。"
            "不要通过项目源码 inspect 或 shell 推断 schema。"
        ),
        (
            "通用 bash 不在 create-agent 默认工具集中。需要校验时调用 create_agent_validate；"
            "Package validator observation 中的 recommended_skill/recommended_resources 是下一步修复入口。"
        ),
        (
            "当 validation digest 或 repair_context 中出现 machine_applicable repair bundle，"
            "必须立即调用 create_agent_scaffold(action=apply_machine_repair)。"
            "不要继续读取 validation、skill 或 package 文件来思考机器可修复问题。"
            "机器修复完成后再调用 create_agent_validate。"
        ),
        (
            ".factory/todo.json 只能通过 create_agent_todo 读取或更新；"
            "如果通用 read 被拒绝，不要再次用 read 访问这个文件。"
        ),
        (
            "tool_output 的 output_id 只能来自当前提示中列出的 output_ref 或 tool_output(action=list) 返回值；"
            "不要构造、猜测或复用看起来像 id 的字符串。"
        ),
        f"Bound tools: {', '.join(tool.name for tool in tools) if tools else 'none'}",
        workspace.context_summary(),
    ]
    if repair_context:
        sections.append(
            "Hidden repair context from the latest package/todo validation gate. "
            "Use it to continue the ReAct repair loop; do not repeat it verbatim to the user.\n\n"
            f"{repair_context}"
        )
    return "\n\n".join(sections)
