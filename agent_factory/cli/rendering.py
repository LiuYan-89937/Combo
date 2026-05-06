from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from agent_factory.application import CreateAgentResult, InitFactoryResult
from agent_factory.core import FactoryEvent


def emit_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False))


def render_banner(console: Console | None = None, *, workspace: str | Path | None = None, state: str = "ready") -> None:
    console = console or Console()
    lines = ["AgentFactory Skeleton", f"State: {state}"]
    if workspace:
        lines.append(f"Workspace: {workspace}")
    console.print(Panel("\n".join(lines), title="LangGraph 14-Stage Skeleton"))


def render_event(event: FactoryEvent, console: Console | None = None) -> None:
    console = console or Console()
    console.print(f"[bold]{event.title}[/bold]")
    if event.message:
        console.print(f"  {event.message}")


class FactoryStreamRenderer:
    def __init__(self, console: Console | None = None, *, show_thinking: bool = False) -> None:
        self.console = console or Console()
        self.show_thinking = show_thinking

    def render(self, event: FactoryEvent) -> None:
        render_event(event, self.console)

    def close(self) -> None:
        return


def render_create_result(result: CreateAgentResult, console: Console | None = None) -> None:
    console = console or Console()
    console.print("")
    console.print(Text(f"Status: {result.status}", style="bold"))
    console.print(f"Requirement: {result.requirement}")
    console.print(f"Workspace: {result.workspace_path}")
    console.print(f"Trace: {result.trace_path}")
    if result.breakpoint_details:
        console.print(f"Breakpoint: {result.breakpoint_details.get('breakpoint_stage')}")
        if result.breakpoint_details.get("next_stage"):
            console.print(f"Next stage: {result.breakpoint_details.get('next_stage')}")
    if result.production_summary:
        console.print(json.dumps(result.production_summary, ensure_ascii=False, indent=2))
    if result.next_steps:
        console.print("Next:")
        for item in result.next_steps:
            console.print(f"  - {item}")


def render_factory_stream_result(events: list[FactoryEvent], console: Console | None = None) -> None:
    console = console or Console()
    if not events:
        return
    console.print("")
    console.print(Text("Stream finished.", style="bold"))
    console.print(f"Last stage: {events[-1].stage}")


def render_init_result(result: InitFactoryResult, console: Console | None = None) -> None:
    console = console or Console()
    console.print("")
    console.print(Text("Workspace initialized", style="bold"))
    console.print(f"Workspace: {result.workspace_path}")
    console.print(f"Config: {result.config_path}")
    console.print(f"Trace: {result.trace_path}")
