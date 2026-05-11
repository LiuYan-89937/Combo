from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
import uuid

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langgraph.types import Command
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from agent_factory.factory_graph.chat_graph import (
    FACTORY_CHAT_TOOLS_NODE,
    build_factory_chat_graph,
    initial_factory_chat_state,
)
from agent_factory.factory_graph.constants import STAGE_IDS
from agent_factory.factory_graph.graph import (
    FACTORY_TOOLS_NODE,
    build_factory_graph,
    initial_factory_graph_state,
)
from agent_factory.factory_graph.tool_approval import FACTORY_TOOL_APPROVAL_NODE
from agent_factory.factory_graph.tools import get_factory_base_tool_ids


@dataclass(slots=True)
class FactoryRunOptions:
    stop_after_stage: str | None = None
    show_state: bool = False
    show_messages: bool = True
    force_manufacture: bool = False
    interaction_mode: str | None = None
    thread_id: str | None = None


class FactoryGraphShell:
    def __init__(self, *, console: Console | None = None, checkpointer: Any | None = None) -> None:
        self.console = console or Console()
        self.checkpointer = checkpointer

    def print_welcome(self) -> None:
        self.console.print(
            Panel.fit(
                "Factory Agent Shell\n"
                "输入 /chat 或 /create-agent 进入模式；输入 /exit 退出当前模式。",
                title="FastAgentFactory",
                border_style="cyan",
            )
        )

    def print_help(self) -> None:
        table = Table(title="Shell Commands", show_header=True, header_style="bold cyan")
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Meaning")
        table.add_row("/help", "显示帮助")
        table.add_row("/chat", "进入聊天模式，后续输入都按 chat 处理")
        table.add_row("/create-agent", "进入制造模式，后续输入都按 Agent 构建需求处理")
        table.add_row("/exit", "退出当前模式；未进入模式时退出 shell")
        table.add_row("/session", "显示当前 Factory 会话")
        table.add_row("/sessions", "列出已保存的 Factory 会话")
        table.add_row("/new-session", "创建并切换到新的 Factory 会话")
        table.add_row("/resume <session_id>", "切换并恢复指定 Factory 会话")
        table.add_row("/stages", "列出 FactoryGraph 的 10 个阶段")
        table.add_row("/tools", "列出当前注入到 ToolNode 的基础工具")
        table.add_row("/stop <stage_id|off>", "设置或关闭本轮之后默认 stop_after_stage")
        table.add_row("/state on|off", "是否打印最终 state JSON")
        table.add_row("/messages on|off", "是否打印最终 messages")
        self.console.print(table)

    def print_stages(self) -> None:
        table = Table(title="FactoryGraph Stages", show_header=True, header_style="bold cyan")
        table.add_column("#", justify="right", no_wrap=True)
        table.add_column("stage_id", style="cyan")
        for index, stage_id in enumerate(STAGE_IDS, start=1):
            table.add_row(str(index), stage_id)
        self.console.print(table)

    def print_tools(self) -> None:
        table = Table(title="Injected Factory Tools", show_header=True, header_style="bold cyan")
        table.add_column("#", justify="right", no_wrap=True)
        table.add_column("tool_id", style="cyan")
        for index, tool_id in enumerate(get_factory_base_tool_ids(), start=1):
            table.add_row(str(index), tool_id)
        self.console.print(table)

    def run_once(
        self,
        requirement: str,
        *,
        messages: list[BaseMessage] | None = None,
        options: FactoryRunOptions,
    ) -> dict[str, Any]:
        app = build_factory_graph(
            stop_after_stage=options.stop_after_stage,
            enable_interrupts=True,
            checkpointer=self.checkpointer,
        )
        initial_state = initial_factory_graph_state(
            requirement=requirement,
            messages=messages or [HumanMessage(content=requirement)],
            force_manufacture=options.force_manufacture,
            interaction_mode=options.interaction_mode,
        )
        self.console.rule("[bold cyan]Factory Run Started")
        self.console.print(f"[bold]Requirement:[/bold] {requirement}")
        if options.stop_after_stage:
            self.console.print(f"[bold]Stop after:[/bold] {options.stop_after_stage}")

        final_state: dict[str, Any] = initial_state
        streamed_message = False
        stream_input: dict[str, Any] | Command = initial_state
        config = {"configurable": {"thread_id": options.thread_id or str(uuid.uuid4())}}
        while True:
            interrupted = False
            for stream_mode, chunk in app.stream(
                stream_input,
                config=config,
                stream_mode=["updates", "values", "messages"],
            ):
                resume = self._resume_from_interrupt_chunk(chunk)
                if resume is not None:
                    stream_input = Command(resume=resume)
                    interrupted = True
                    break
                if stream_mode == "updates":
                    self._print_update_chunk(chunk)
                elif stream_mode == "values":
                    final_state = chunk
                elif stream_mode == "messages":
                    streamed_message = self._print_message_stream_chunk(chunk) or streamed_message
            if not interrupted:
                break
        if streamed_message:
            self.console.print()
        self.console.rule("[bold green]Factory Run Completed")
        self._print_requirement_brief(final_state)
        self._print_refined_plan(final_state)
        self._print_runtime_pattern_selection(final_state)
        self._print_graph_behavior_plan(final_state)
        self._print_node_strategy_plan(final_state)
        self._print_tool_capability_plan(final_state)
        self._print_resource_condition_plan(final_state)
        self._print_summary(final_state)
        if options.show_messages:
            self._print_messages(final_state.get("messages", []))
        if options.show_state:
            self._print_state(final_state)
        return final_state

    def run_chat_once(
        self,
        messages: list[BaseMessage],
        *,
        thread_id: str | None,
        show_messages: bool = True,
        show_state: bool = False,
    ) -> dict[str, Any]:
        app = build_factory_chat_graph(enable_interrupts=True, checkpointer=self.checkpointer)
        initial_state = initial_factory_chat_state(messages)
        self.console.rule("[bold cyan]Factory Chat Started")

        final_state: dict[str, Any] = initial_state
        streamed_message = False
        stream_input: dict[str, Any] | Command = initial_state
        config = {"configurable": {"thread_id": thread_id or str(uuid.uuid4())}}
        while True:
            interrupted = False
            for stream_mode, chunk in app.stream(
                stream_input,
                config=config,
                stream_mode=["updates", "values", "messages"],
            ):
                resume = self._resume_from_interrupt_chunk(chunk)
                if resume is not None:
                    stream_input = Command(resume=resume)
                    interrupted = True
                    break
                if stream_mode == "updates":
                    self._print_update_chunk(chunk)
                elif stream_mode == "values":
                    final_state = chunk
                elif stream_mode == "messages":
                    streamed_message = self._print_message_stream_chunk(chunk) or streamed_message
            if not interrupted:
                break
        if streamed_message:
            self.console.print()
        self.console.rule("[bold green]Factory Chat Completed")
        self._print_summary(final_state)
        if show_messages:
            self._print_messages(final_state.get("messages", []))
        if show_state:
            self._print_state(final_state)
        return final_state

    def _print_update_chunk(self, chunk: dict[str, Any]) -> None:
        for node_id, patch in chunk.items():
            title = f"Node: {node_id}"
            if node_id in {FACTORY_TOOLS_NODE, FACTORY_CHAT_TOOLS_NODE}:
                title = f"ToolNode: {node_id}"
            elif node_id == FACTORY_TOOL_APPROVAL_NODE:
                title = "Interrupt: tool_approval"
            self.console.print(Panel(Text(_format_patch(patch)), title=title, border_style="blue"))

    def _print_message_stream_chunk(self, chunk: tuple[Any, dict[str, Any]]) -> bool:
        message_chunk, metadata = chunk
        if "nostream" in set(metadata.get("tags", [])):
            return False
        if metadata.get("langgraph_node") in {FACTORY_TOOLS_NODE, FACTORY_CHAT_TOOLS_NODE}:
            return False
        if isinstance(message_chunk, ToolMessage):
            return False
        content = getattr(message_chunk, "content", "")
        if not content:
            return False
        self.console.file.write(str(content))
        self.console.file.flush()
        return True

    def _print_summary(self, state: dict[str, Any]) -> None:
        table = Table(show_header=True, header_style="bold green")
        table.add_column("Field", no_wrap=True)
        table.add_column("Value")
        table.add_row("status", str(state.get("status", "")))
        table.add_row("current_stage", str(state.get("current_stage", "")))
        table.add_row("stage_log_count", str(len(state.get("stage_log", []))))
        table.add_row("message_count", str(len(state.get("messages", []))))
        table.add_row("error_count", str(len(state.get("errors", []))))
        self.console.print(table)

    def _print_requirement_brief(self, state: dict[str, Any]) -> None:
        brief = state.get("requirement_brief") or {}
        refined_requirement = brief.get("refined_requirement")
        if not refined_requirement:
            return
        self.console.print(
            Panel(
                str(refined_requirement),
                title="Refined Requirement",
                border_style="green",
            )
        )

    def _print_refined_plan(self, state: dict[str, Any]) -> None:
        refined_plan_text = state.get("refined_plan_text")
        if not refined_plan_text:
            return
        self.console.print(
            Panel(
                str(refined_plan_text),
                title="Refined Business Plan",
                border_style="green",
            )
        )

    def _print_runtime_pattern_selection(self, state: dict[str, Any]) -> None:
        selection = state.get("runtime_pattern_selection") or {}
        selected_pattern_id = selection.get("selected_pattern_id")
        if not selected_pattern_id:
            return
        lines = [
            f"pattern_id: {selected_pattern_id}",
            f"name: {selection.get('selected_pattern_name', '-')}",
            f"reason: {selection.get('selection_reason', '-')}",
            f"fit: {selection.get('fit_summary', '-')}",
        ]
        alternatives = selection.get("alternatives") or []
        if alternatives:
            lines.append("alternatives:")
            for item in alternatives:
                lines.append(
                    f"  - {item.get('pattern_id')}: {item.get('reason', '')}"
                )
        assumptions = selection.get("assumptions") or []
        if assumptions:
            lines.append("assumptions:")
            lines.extend(f"  - {item}" for item in assumptions)
        self.console.print(
            Panel(
                "\n".join(lines),
                title="Runtime Pattern Selection",
                border_style="green",
            )
        )

    def _print_graph_behavior_plan(self, state: dict[str, Any]) -> None:
        plan = state.get("graph_behavior_plan") or {}
        pattern_id = plan.get("pattern_id")
        if not pattern_id:
            return
        self.console.print(
            Panel(
                str(plan.get("graph_intent") or ""),
                title=f"Runtime Graph Behavior: {pattern_id}",
                border_style="green",
            )
        )
        self._print_graph_routes(plan)
        self._print_node_behaviors(plan)

    def _print_graph_routes(self, plan: dict[str, Any]) -> None:
        routes = list(plan.get("routes") or [])
        if not routes:
            return
        route_lines = []
        for route in routes:
            route_lines.append(
                f"{route.get('from_node')} --[{route.get('condition')}]--> {route.get('to_node')}"
            )
            meaning = route.get("business_meaning")
            if meaning:
                route_lines.append(f"  {meaning}")
        self.console.print(
            Panel(
                "\n".join(route_lines),
                title="Graph Routes",
                border_style="cyan",
            )
        )

    def _print_node_behaviors(self, plan: dict[str, Any]) -> None:
        nodes = list(plan.get("nodes") or [])
        if not nodes:
            return
        table = Table(title="Node Behaviors", show_header=True, header_style="bold cyan")
        table.add_column("node_id", style="cyan", no_wrap=True)
        table.add_column("type", no_wrap=True)
        table.add_column("business_behavior")
        table.add_column("user_visible", no_wrap=True)
        for node in nodes:
            table.add_row(
                str(node.get("node_id") or ""),
                str(node.get("node_type") or ""),
                str(node.get("business_behavior") or ""),
                str(node.get("user_visible", False)),
            )
        self.console.print(table)

    def _print_node_strategy_plan(self, state: dict[str, Any]) -> None:
        plan = state.get("node_strategy_plan") or {}
        node_strategies = list(plan.get("node_strategies") or [])
        if not node_strategies:
            return
        self.console.print(
            Panel(
                str(plan.get("strategy_intent") or ""),
                title=f"Node Strategy Planning: {plan.get('pattern_id', '-')}",
                border_style="green",
            )
        )
        table = Table(title="Node Strategy Config", show_header=True, header_style="bold cyan")
        table.add_column("node_id", style="cyan", no_wrap=True)
        table.add_column("wrappers")
        table.add_column("strategy_refs")
        for item in node_strategies:
            table.add_row(
                str(item.get("node_id") or ""),
                _format_wrapper_plans(item.get("wrappers") or []),
                _format_strategy_refs(item.get("strategy_refs") or []),
            )
        self.console.print(table)
        proposed_strategies = list(plan.get("proposed_strategies") or [])
        if proposed_strategies:
            proposed_table = Table(title="Proposed Strategy Specs", show_header=True, header_style="bold magenta")
            proposed_table.add_column("strategy_id", style="cyan", no_wrap=True)
            proposed_table.add_column("kind", no_wrap=True)
            proposed_table.add_column("phase", no_wrap=True)
            proposed_table.add_column("required_by")
            proposed_table.add_column("description")
            for item in proposed_strategies:
                proposed_table.add_row(
                    str(item.get("strategy_id") or ""),
                    str(item.get("kind") or ""),
                    str(item.get("phase") or ""),
                    ", ".join(str(node_id) for node_id in item.get("required_by_node_ids") or []) or "-",
                    str(item.get("description") or ""),
                )
            self.console.print(proposed_table)

    def _print_tool_capability_plan(self, state: dict[str, Any]) -> None:
        plan = state.get("tool_capability_plan") or {}
        capabilities = list(plan.get("tool_capabilities") or [])
        visibility = list(plan.get("node_tool_visibility") or [])
        if not capabilities and not visibility:
            return
        self.console.print(
            Panel(
                str(plan.get("plan_intent") or ""),
                title="Tool Capability Planning",
                border_style="green",
            )
        )
        if capabilities:
            capability_table = Table(title="Tool Capabilities", show_header=True, header_style="bold cyan")
            capability_table.add_column("capability_id", style="cyan", no_wrap=True)
            capability_table.add_column("name")
            capability_table.add_column("required_by")
            capability_table.add_column("visible_to")
            capability_table.add_column("approval", no_wrap=True)
            capability_table.add_column("status", no_wrap=True)
            for item in capabilities:
                capability_table.add_row(
                    str(item.get("capability_id") or ""),
                    str(item.get("name") or ""),
                    ", ".join(str(node_id) for node_id in item.get("required_by_node_ids") or []) or "-",
                    ", ".join(str(node_id) for node_id in item.get("visible_to_node_ids") or []) or "-",
                    "yes" if item.get("approval_required") else "no",
                    str(item.get("implementation_status") or ""),
                )
            self.console.print(capability_table)
        if visibility:
            visibility_table = Table(title="Node Tool Visibility", show_header=True, header_style="bold cyan")
            visibility_table.add_column("node_id", style="cyan", no_wrap=True)
            visibility_table.add_column("allowed")
            visibility_table.add_column("approval_required")
            visibility_table.add_column("blocked")
            visibility_table.add_column("reason")
            for item in visibility:
                visibility_table.add_row(
                    str(item.get("node_id") or ""),
                    _join_ids(item.get("allowed_tool_capability_ids") or []),
                    _join_ids(item.get("approval_required_capability_ids") or []),
                    _join_ids(item.get("blocked_tool_capability_ids") or []),
                    str(item.get("reason") or ""),
                )
            self.console.print(visibility_table)

    def _print_resource_condition_plan(self, state: dict[str, Any]) -> None:
        plan = state.get("resource_condition_plan") or {}
        if not plan:
            return
        lines = [
            f"status: {plan.get('status', '-')}",
            f"resource_file_path: {plan.get('resource_file_path', '-')}",
        ]
        missing_keys = list(plan.get("missing_keys") or [])
        if missing_keys:
            lines.append(f"missing_keys: {len(missing_keys)}")
        self.console.print(
            Panel(
                "\n".join(lines),
                title="Resource And Condition Planning",
                border_style="green" if plan.get("status") == "complete" else "yellow",
            )
        )
        resources = dict(plan.get("resources") or {})
        if resources:
            table = Table(title="Prepared Resources", show_header=True, header_style="bold cyan")
            table.add_column("key", style="cyan", no_wrap=True)
            table.add_column("value")
            for key, value in resources.items():
                table.add_row(str(key), str(value))
            self.console.print(table)

    def _print_messages(self, messages: Iterable[BaseMessage]) -> None:
        table = Table(title="Messages", show_header=True, header_style="bold cyan")
        table.add_column("#", justify="right", no_wrap=True)
        table.add_column("type", no_wrap=True)
        table.add_column("content")
        for index, message in enumerate(messages, start=1):
            content = str(getattr(message, "content", ""))
            if len(content) > 300:
                content = f"{content[:300]}..."
            table.add_row(str(index), message.__class__.__name__, content)
        self.console.print(table)

    def _print_state(self, state: dict[str, Any]) -> None:
        self.console.print(Panel(JSON.from_data(_json_safe_state(state)), title="Final State"))

    def _resume_from_interrupt_chunk(self, chunk: Any) -> dict[str, Any] | None:
        interrupts = _extract_interrupts(chunk)
        if not interrupts:
            return None
        resume: dict[str, Any] | None = None
        for item in interrupts:
            payload = getattr(item, "value", item)
            if isinstance(payload, dict) and payload.get("type") == "requirement_clarification":
                resume = self._read_requirement_clarification(payload)
            elif isinstance(payload, dict) and payload.get("type") == "plan_review":
                resume = self._read_plan_review(payload)
            elif isinstance(payload, dict) and payload.get("type") == "resource_completion":
                resume = self._read_resource_completion(payload)
            else:
                self._print_interrupt_payload(payload)
                resume = {"approved": self._read_approval()}
        return resume

    def _read_requirement_clarification(self, payload: dict[str, Any]) -> dict[str, Any]:
        answers: list[dict[str, Any]] = []
        questions = list(payload.get("questions") or [])
        for index, question_payload in enumerate(questions, start=1):
            question_id = str(question_payload.get("id") or f"question_{index}")
            question = str(question_payload.get("question") or "")
            options = list(question_payload.get("options") or [])
            custom_option_id = str(question_payload.get("custom_option_id") or "custom")
            self.console.print(
                Panel(
                    question,
                    title=f"Requirement Clarification {index}/{len(questions)}",
                    border_style="yellow",
                )
            )
            selected = _select_option_with_prompt_toolkit(options)
            if selected is None:
                selected = _select_option_with_numbered_prompt(self.console, options)
            custom_text = None
            if str(selected.get("id")) == custom_option_id:
                custom_text = self.console.input("自定义补充: ").strip()
            answers.append(
                {
                    "question_id": question_id,
                    "selected_option_id": str(selected.get("id") or ""),
                    "selected_label": str(selected.get("label") or ""),
                    "custom_text": custom_text,
                }
            )
        return {
            "type": "requirement_clarification_answer",
            "answers": answers,
        }

    def _read_plan_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        plan_text = str(payload.get("plan_text") or "")
        message = str(payload.get("message") or "请审查计划。")
        self.console.print(Panel(plan_text, title="Refined Business Plan", border_style="yellow"))
        self.console.print(f"[yellow]{message}[/yellow]")
        options = [
            {
                "id": "continue",
                "label": "继续",
                "description": "使用这个计划进入下一阶段",
            },
            {
                "id": "custom",
                "label": "自定义输入",
                "description": "输入修改意见并重新生成计划",
            },
        ]
        selected = _select_option_with_prompt_toolkit(options)
        if selected is None:
            selected = _select_option_with_numbered_prompt(self.console, options)
        if selected.get("id") == "continue":
            return {"type": "plan_review_result", "decision": "continue"}
        revision_instruction = self.console.input("自定义修改意见: ").strip()
        return {
            "type": "plan_review_result",
            "decision": "revise",
            "revision_instruction": revision_instruction,
        }

    def _read_resource_completion(self, payload: dict[str, Any]) -> dict[str, Any]:
        missing_keys = list(payload.get("missing_keys") or [])
        current_resources = dict(payload.get("current_resources") or {})
        resource_file_path = str(payload.get("resource_file_path") or "")
        if resource_file_path:
            self.console.print(
                Panel(
                    resource_file_path,
                    title="Resource File",
                    border_style="yellow",
                )
            )
        if current_resources:
            table = Table(title="Current Resources", show_header=True, header_style="bold yellow")
            table.add_column("key", style="cyan", no_wrap=True)
            table.add_column("value")
            for key, value in current_resources.items():
                table.add_row(str(key), str(value))
            self.console.print(table)
        items: list[dict[str, Any]] = []
        for index, item in enumerate(missing_keys, start=1):
            key = str(item.get("key") or "")
            description = str(item.get("description") or "")
            used_by = _join_ids(item.get("used_by_capability_ids") or [])
            hint = str(item.get("resolution_hint") or "")
            self.console.print(
                Panel(
                    f"key: {key}\nused_by: {used_by}\n\n{description}\n\n{hint}",
                    title=f"Resource Completion {index}/{len(missing_keys)}",
                    border_style="yellow",
                )
            )
            options = [
                {
                    "id": "provide_value",
                    "label": "提供值",
                    "description": "输入一个现在可写入资源文件的值",
                },
                {
                    "id": "runtime_provided",
                    "label": "运行时提供",
                    "description": "写入运行时占位并允许进入后续阶段",
                },
                {
                    "id": "block",
                    "label": "阻塞",
                    "description": "资源无法准备，不进入下一阶段",
                },
            ]
            selected = _select_option_with_prompt_toolkit(options)
            if selected is None:
                selected = _select_option_with_numbered_prompt(self.console, options)
            decision = str(selected.get("id") or "block")
            value = None
            if decision == "provide_value":
                value = self.console.input("资源值: ").strip()
                if not value:
                    decision = "block"
            items.append({"key": key, "decision": decision, "value": value})
        return {"items": items}

    def _print_interrupt_payload(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            self.console.print(Panel(str(payload), title="Interrupt", border_style="yellow"))
            return
        table = Table(title="Tool Approval Required", show_header=True, header_style="bold yellow")
        table.add_column("#", justify="right", no_wrap=True)
        table.add_column("tool", style="cyan")
        table.add_column("summary")
        for index, request in enumerate(payload.get("requests", []), start=1):
            table.add_row(
                str(index),
                str(request.get("tool_name") or ""),
                str(request.get("summary") or ""),
            )
        self.console.print(table)
        message = payload.get("message")
        if message:
            self.console.print(f"[yellow]{message}[/yellow]")

    def _read_approval(self) -> bool:
        while True:
            answer = self.console.input("确认执行？输入 -y 或 -n: ").strip().lower()
            if answer == "-y":
                return True
            if answer == "-n":
                return False
            self.console.print("请输入 -y 或 -n。")


def _format_patch(patch: dict[str, Any]) -> str:
    lines: list[str] = []
    current_stage = patch.get("current_stage")
    if current_stage:
        lines.append(f"current_stage: {current_stage}")
    for item in patch.get("stage_log", []):
        lines.append(f"stage_log: {item.get('stage_id')} [{item.get('status')}]")
        message = item.get("message")
        if message:
            lines.append(f"  {message}")
    messages = patch.get("messages") or []
    for message in messages:
        name = getattr(message, "name", None) or message.__class__.__name__
        content = str(getattr(message, "content", ""))
        if len(content) > 300:
            content = f"{content[:300]}..."
        lines.append(f"message: {name} -> {content}")
    if not lines:
        lines.append(str(patch))
    return "\n".join(lines)


def _json_safe_state(state: dict[str, Any]) -> dict[str, Any]:
    safe = dict(state)
    safe["messages"] = [
        {
            "type": message.__class__.__name__,
            "content": getattr(message, "content", ""),
            "name": getattr(message, "name", None),
            "tool_calls": getattr(message, "tool_calls", None),
        }
        for message in state.get("messages", [])
    ]
    return safe


def _format_wrapper_plans(wrappers: list[dict[str, Any]]) -> str:
    if not wrappers:
        return "-"
    return "\n".join(
        f"{item.get('wrapper_id')}@{item.get('phase')}"
        for item in wrappers
    )


def _format_strategy_refs(strategy_refs: list[dict[str, Any]]) -> str:
    if not strategy_refs:
        return "-"
    lines: list[str] = []
    for item in strategy_refs:
        strategy_id = str(item.get("strategy_id") or "-")
        kind = str(item.get("kind") or "-")
        phase = str(item.get("phase") or "-")
        source = str(item.get("source") or "catalog")
        notes = item.get("config_notes") or {}
        suffix = f" notes:{len(notes)}" if notes else ""
        lines.append(f"{kind}:{strategy_id}@{phase} [{source}]{suffix}")
    return "\n".join(lines)


def _join_ids(values: list[Any]) -> str:
    if not values:
        return "-"
    return ", ".join(str(value) for value in values)


def _extract_interrupts(chunk: Any) -> tuple[Any, ...]:
    if not isinstance(chunk, dict):
        return ()
    interrupts = chunk.get("__interrupt__")
    if not interrupts:
        return ()
    if isinstance(interrupts, tuple):
        return interrupts
    if isinstance(interrupts, list):
        return tuple(interrupts)
    return (interrupts,)


def _select_option_with_prompt_toolkit(options: list[dict[str, Any]]) -> dict[str, Any] | None:
    try:
        from prompt_toolkit.application import Application
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import Layout
        from prompt_toolkit.layout.containers import HSplit, Window
        from prompt_toolkit.layout.controls import FormattedTextControl
    except ModuleNotFoundError:
        return None

    selected_index = 0
    result: dict[str, Any] = {}
    bindings = KeyBindings()

    def formatted_options():
        lines = []
        for index, option in enumerate(options):
            marker = "> " if index == selected_index else "  "
            label = str(option.get("label") or option.get("id") or "")
            description = option.get("description")
            text = f"{marker}{label}"
            if description:
                text = f"{text} - {description}"
            style = "reverse" if index == selected_index else ""
            lines.append((style, text + "\n"))
        return lines

    control = FormattedTextControl(formatted_options, focusable=True)

    @bindings.add("up")
    def _move_up(event) -> None:
        nonlocal selected_index
        selected_index = (selected_index - 1) % len(options)

    @bindings.add("down")
    def _move_down(event) -> None:
        nonlocal selected_index
        selected_index = (selected_index + 1) % len(options)

    @bindings.add("enter")
    def _confirm(event) -> None:
        result["selected"] = options[selected_index]
        event.app.exit()

    @bindings.add("c-c")
    def _cancel(event) -> None:
        result["selected"] = options[selected_index]
        event.app.exit()

    app = Application(
        layout=Layout(HSplit([Window(content=control)])),
        key_bindings=bindings,
        full_screen=False,
    )
    app.run()
    selected = result.get("selected")
    if selected is None:
        return None
    if not isinstance(selected, dict):
        return None
    return selected


def _select_option_with_numbered_prompt(console: Console, options: list[dict[str, Any]]) -> dict[str, Any]:
    table = Table(title="Options", show_header=True, header_style="bold yellow")
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("label")
    table.add_column("description")
    for index, option in enumerate(options, start=1):
        table.add_row(
            str(index),
            str(option.get("label") or option.get("id") or ""),
            str(option.get("description") or ""),
        )
    console.print(table)
    while True:
        raw = console.input("选择序号: ").strip()
        if raw.isdigit():
            index = int(raw) - 1
            if 0 <= index < len(options):
                return options[index]
        console.print("请输入有效序号。")
