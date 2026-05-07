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
        table.add_row("/stages", "列出 FactoryGraph 的 14 个阶段")
        table.add_row("/tools", "列出当前注入到 ToolNode 的基础工具")
        table.add_row("/stop <stage_id>", "设置本轮之后默认 stop_after_stage")
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
                resume = self._approval_resume_from_chunk(chunk)
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
                resume = self._approval_resume_from_chunk(chunk)
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

    def _approval_resume_from_chunk(self, chunk: Any) -> dict[str, bool] | None:
        interrupts = _extract_interrupts(chunk)
        if not interrupts:
            return None
        for item in interrupts:
            self._print_interrupt_payload(getattr(item, "value", item))
        return {"approved": self._read_approval()}

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
