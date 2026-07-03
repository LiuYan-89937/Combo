from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool

from agent_factory.create_agent.capability_inventory import render_static_capability_inventory
from agent_factory.create_agent.prompt_builder import CreateAgentPromptPayload
from agent_factory.models.message_layout import system_messages_first


def build_evolution_messages(
    *,
    package_id: str,
    package_path: str,
    user_input: str,
    error_pack: dict[str, Any],
    trace_gate: dict[str, Any] | None = None,
    target_plan: dict[str, Any] | None = None,
    package_summary: dict[str, Any],
    tools: list[Any],
) -> list[BaseMessage]:
    tool_names = ", ".join(str(getattr(tool, "name", "")) for tool in tools)
    system = f"""你是 FastAgentFactory 的已发布 Agent 进化运行时。

你的任务是基于用户的进化要求修改一个已发布 AgentPackage；如果系统提供 failed trace 报错摘要，它只是辅助证据。

硬性约束：
- 用户进化要求是本轮主目标。先围绕 user_evolution_goal 修改 package。
- failed_trace_error_pack 可能不存在；不存在时直接围绕 user_evolution_goal 和当前 package 状态推进。
- 如果存在 failed_trace_error_pack，它是证据和约束，不是默认主任务。
- 只有在 trace 报错与 user_evolution_goal 直接相关，或者会阻塞本轮 validate/probe/runtime readiness 时，才把 trace 报错纳入修复。
- 如果 trace 报错与用户目标无关且不会阻塞本轮验证，不要围绕 trace 报错展开调查或把它作为主要修改方向。
- 如果用户目标和 trace 报错都需要处理，先说明二者关系，再优先完成用户目标，并修复会阻塞发布的 trace 问题。
- 只能修改当前已发布 package 目录内的文件：{package_path}
- 不要创建新的 agent，不要走 create-agent 制造流程，不要生成 evolution workspace。
- 不要读取完整 trace。若系统提供了错误摘要，只能以此作为 trace 证据；若未提供，不要因为缺少 trace 阻塞进化。
- 不要暴露或引用 create-agent 制造工具、制造 workspace、制造 trace。
- 修改必须是结构性修复：优先修 prompt、contracts、tool 实现、依赖声明、附件处理、上下文策略等真实 package surface。
- 不做短中长期计划；一次进化就奔着可发布结果。
- 如果证据不足，做最小必要的 package 检查后给出保守修改，不要凭空硬编码特例。
- 在第一次修改任何文件前，必须先调用 skill(action="load", name="00-agent-evolution", current_system="agent_evolution", reason=...) 读取进化专用流程。
- 进化顺序必须是：定向定位修改面 -> 选择唯一 authoring/write 策略 -> 一次性修改相关 surface -> probe/validate -> 根据新证据修复或收束。不要在 dependencies、assembly、tool source 之间来回试错。
- 系统会提供 evolution_target_plan。它是本轮进化的执行边界：只能优先读取 required_first_reads，只能围绕 target_files 修改，只能调用 allowed_authoring_actions 中的 create_agent_authoring action。
- 如果 evolution_target_plan.write_strategy 无法表达用户目标，或者 authoring 工具缺少必要字段，停止并报告 authoring gap；不要用 generic edit/write 绕过 managed file protection。
- 如果新增或修改 package tool，必须使用 create_agent_probe_tool(action="inspect") 和 create_agent_probe_tool(action="call", probe_kind="success_path", ...) 生成 fresh successful-path probe 证据。
- 如果后续 full_static validation 失败，系统会把验证报告作为新 observation 发给你；你必须继续 ReAct 修复，而不是重复总结失败。
- full_static validation 通过后，必须把中文进化总结放入 create_agent_control(action="finalize", message=...) 并调用它收束本次进化；不要调用 create_agent_stage，它是制造期工具，进化模式不可用。
- finalize 工具调用完成后不要再生成额外总结或继续调用工具；运行时会使用 finalize 的 message 作为唯一终态摘要。

可用工具：{tool_names}
"""
    user = {
        "package_id": package_id,
        "package_path": package_path,
        "user_evolution_goal": user_input,
        "package_summary": package_summary,
        "trace_gate": trace_gate or {},
        "evolution_target_plan": target_plan or {},
        **(
            {"failed_trace_error_pack": error_pack}
            if error_pack
            else {
                "failed_trace_error_pack": {
                    "provided": False,
                    "reason": str((trace_gate or {}).get("reason") or "trace details were not provided; use the user goal and package state only"),
                }
            }
        ),
    }
    return [
        SystemMessage(content=system),
        HumanMessage(content=json.dumps(user, ensure_ascii=False, indent=2)),
    ]


def build_evolution_prompt(
    state: dict[str, Any],
    tools: list[BaseTool],
    *,
    capability_inventory: dict[str, Any] | None = None,
) -> CreateAgentPromptPayload:
    context = state.get("evolution_context") if isinstance(state.get("evolution_context"), dict) else {}
    messages = system_messages_first([
        *build_evolution_messages(
            package_id=str(context.get("package_id") or ""),
            package_path=str(state.get("workspace_path") or context.get("package_path") or ""),
            user_input=str(state.get("request") or ""),
            error_pack=context.get("error_pack") if isinstance(context.get("error_pack"), dict) else {},
            trace_gate=context.get("trace_gate") if isinstance(context.get("trace_gate"), dict) else {},
            package_summary=context.get("package_summary") if isinstance(context.get("package_summary"), dict) else {},
            target_plan=context.get("target_plan") if isinstance(context.get("target_plan"), dict) else {},
            tools=tools,
        ),
        *list(state.get("messages") or []),
    ])
    stable = {
        "tool_names": sorted(str(getattr(tool, "name", "")) for tool in tools),
        "capability_inventory": render_static_capability_inventory(capability_inventory or {}),
    }
    return CreateAgentPromptPayload(
        messages=messages,
        diagnostics={
            "version": "agent_evolution_prompt_diagnostics.v0",
            "tool_count": len(tools),
            "message_count": len(messages),
            "stable_environment": stable,
        },
    )
