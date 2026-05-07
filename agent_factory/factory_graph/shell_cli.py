from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from agent_factory.factory_graph.constants import STAGE_IDS
from agent_factory.factory_graph.graph import FACTORY_TOOLS_NODE, build_factory_graph
from agent_factory.factory_graph.tools import get_factory_base_tool_ids


@dataclass(slots=True)
class FactoryRunOptions:
    stop_after_stage: str | None = None
    show_state: bool = False
    show_messages: bool = True
    force_manufacture: bool = False


class FactoryGraphShell:
    def __init__(self, *, console: Console | None = None) -> None:
        self.console = console or Console()

    def print_welcome(self) -> None:
        self.console.print(
            Panel.fit(
                "Factory Agent Shell\n"
                "输入需求直接运行工厂图；输入 /help 查看命令；输入 /exit 退出。",
                title="FastAgentFactory",
                border_style="cyan",
            )
        )

    def print_help(self) -> None:
        table = Table(title="Shell Commands", show_header=True, header_style="bold cyan")
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Meaning")
        table.add_row("/help", "显示帮助")
        table.add_row("/stages", "列出 FactoryGraph 的 14 个阶段")
        table.add_row("/tools", "列出当前注入到 ToolNode 的基础工具")
        table.add_row("/run <需求>", "运行一次工厂图")
        table.add_row("/stop <stage_id>", "设置本轮之后默认 stop_after_stage")
        table.add_row("/state on|off", "是否打印最终 state JSON")
        table.add_row("/messages on|off", "是否打印最终 messages")
        table.add_row("/exit", "退出 shell")
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

    def run_once(self, requirement: str, *, options: FactoryRunOptions) -> dict[str, Any]:
        app = build_factory_graph(stop_after_stage=options.stop_after_stage)
        initial_state = {
            "requirement": requirement,
            "messages": [HumanMessage(content=requirement)],
            "status": "running",
            "force_manufacture": options.force_manufacture,
            "stage_log": [],
            "errors": [],
        }
        self.console.rule("[bold cyan]Factory Run Started")
        self.console.print(f"[bold]Requirement:[/bold] {requirement}")
        if options.stop_after_stage:
            self.console.print(f"[bold]Stop after:[/bold] {options.stop_after_stage}")

        final_state: dict[str, Any] = initial_state
        streamed_message = False
        for stream_mode, chunk in app.stream(
            initial_state,
            stream_mode=["updates", "values", "messages"],
        ):
            if stream_mode == "updates":
                self._print_update_chunk(chunk)
            elif stream_mode == "values":
                final_state = chunk
            elif stream_mode == "messages":
                streamed_message = self._print_message_stream_chunk(chunk) or streamed_message
        if streamed_message:
            self.console.print()
        self.console.rule("[bold green]Factory Run Completed")
        self._print_summary(final_state)
        if options.show_messages:
            self._print_messages(final_state.get("messages", []))
        if options.show_state:
            self._print_state(final_state)
        return final_state

    def _print_update_chunk(self, chunk: dict[str, Any]) -> None:
        for node_id, patch in chunk.items():
            title = f"Node: {node_id}"
            if node_id == FACTORY_TOOLS_NODE:
                title = f"ToolNode: {node_id}"
            self.console.print(Panel(Text(_format_patch(patch)), title=title, border_style="blue"))

    def _print_message_stream_chunk(self, chunk: tuple[Any, dict[str, Any]]) -> bool:
        message_chunk, metadata = chunk
        if "nostream" in set(metadata.get("tags", [])):
            return False
        content = getattr(message_chunk, "content", "")
        if not content:
            return False
        self.console.print(str(content), end="")
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
