from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from agent_factory.application import CreateAgentResult, InitFactoryResult
from agent_factory.cli.theme import (
    APP_BANNER,
    APP_SUBTITLE,
    APP_TITLE,
    BANNER_MIN_WIDTH,
    FIELD_WIDTH,
    NEXT_LABEL,
    NO_89937_ASCII_BANNER,
    STYLE_ACCENT,
    STYLE_ERROR,
    STYLE_MUTED,
    STYLE_SUCCESS,
    STYLE_TITLE,
    STYLE_WARNING,
    SYMBOL_ADD,
    SYMBOL_CHANGE,
    SYMBOL_FAILED,
    SYMBOL_PROGRESS,
    SYMBOL_WARNING,
)
from agent_factory.core import EventStatus, FactoryEvent
from agent_factory.specs import ValidationReport


def emit_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False))


def render_banner(
    console: Console | None = None,
    *,
    workspace: str | Path | None = None,
    state: str = "ready",
) -> None:
    console = console or Console()
    if console.width < BANNER_MIN_WIDTH:
        banner = Text(APP_BANNER, style=STYLE_TITLE)
    else:
        banner = Text(NO_89937_ASCII_BANNER.strip("\n"), style=STYLE_TITLE)
    details = Table.grid(padding=(0, 2))
    details.add_column(style=STYLE_MUTED)
    details.add_column()
    details.add_row("Mode", "Route A / conversational CLI")
    details.add_row("State", state)
    if workspace:
        details.add_row("Workspace", str(workspace))
    body = Group(banner, Text(""), details)
    panel = Panel(
        body,
        title=APP_TITLE,
        subtitle=APP_SUBTITLE,
        border_style=STYLE_ACCENT,
        box=box.ASCII,
        padding=(1, 2),
    )
    console.print(panel)


def render_section(title: str, console: Console | None = None) -> None:
    console = console or Console()
    console.print("")
    console.print(Text(f"  {title}", style=STYLE_TITLE))


def render_kv(
    key: str,
    value: Any,
    console: Console | None = None,
    *,
    style: str | None = None,
) -> None:
    console = console or Console()
    rendered = "-" if value is None else str(value)
    console.print(f"  {key:<{FIELD_WIDTH}}", end="")
    console.print(rendered, style=style)


def render_event(event: FactoryEvent, console: Console | None = None) -> None:
    console = console or Console()
    symbol, style = _status_symbol_and_style(event.status)
    console.print(f"  {symbol} {event.title}", style=style)
    if event.message:
        console.print(f"    {event.message}", style=STYLE_MUTED)
    if event.artifact_path:
        render_kv("path", event.artifact_path, console)


def render_create_result(result: CreateAgentResult, console: Console | None = None) -> None:
    console = console or Console()
    render_section("Factory", console)
    render_kv("Status", result.status, console, style=_result_status_style(result.status))
    render_kv("Runtime", result.runtime_type, console)
    for event in result.events:
        render_event(event, console)
    if result.clarification_questions:
        render_section("Clarification", console)
        for question in result.clarification_questions:
            console.print(f"  {SYMBOL_WARNING} {question}", style=STYLE_WARNING)
    render_section("Factory workspace", console)
    render_kv("Workspace", result.workspace_path, console)
    render_kv("Trace", result.trace_path, console)
    render_kv("Memory", result.memory_path, console)
    if result.output_path:
        render_kv("Draft", result.output_path, console, style=STYLE_SUCCESS)
    if result.generated_artifacts:
        render_section("Generated artifacts", console)
        render_kv("Tool scripts", result.generated_tool_count, console)
        render_kv("Tool tests", result.generated_tool_test_count, console)
        render_kv("MCP bindings", result.mcp_binding_count, console)
        render_kv("Harness scenarios", result.harness_scenario_count, console)
    if result.error:
        render_kv("Error", result.error.code, console, style=STYLE_ERROR)
    if result.next_steps:
        render_section(NEXT_LABEL, console)
        for step in result.next_steps:
            console.print(f"  {step}", style=STYLE_MUTED)


def render_init_result(result: InitFactoryResult, console: Console | None = None) -> None:
    console = console or Console()
    render_section("Factory workspace", console)
    render_kv("Workspace", result.workspace_path, console)
    render_kv("Config", result.config_path, console)
    render_kv("Drafts", result.drafts_path, console)
    render_kv("Trace", result.trace_path, console)
    render_kv("Memory", result.memory_path, console)
    render_section(NEXT_LABEL, console)
    console.print("  /create-agent --draft", style=STYLE_MUTED)


def render_validation_report(report: ValidationReport, console: Console | None = None) -> None:
    console = console or Console()
    status = "passed" if report.ok else "failed"
    status_style = STYLE_SUCCESS if report.ok else STYLE_ERROR
    render_section("AgentPackage validation", console)
    render_kv("Status", status, console, style=status_style)
    render_kv("Issues", len(report.issues), console)
    if report.root_path:
        render_kv("Path", report.root_path, console)
    if report.issues:
        render_section("Issues", console)
        table = Table(
            box=box.ASCII,
            show_header=True,
            header_style=STYLE_TITLE,
            expand=False,
        )
        table.add_column("Severity")
        table.add_column("Code")
        table.add_column("Location")
        table.add_column("Message")
        for issue in report.issues:
            location = issue.file or "-"
            if issue.path:
                location = f"{location}:{issue.path}"
            table.add_row(issue.severity.value, issue.code, location, issue.message)
        console.print(table)
    render_section(NEXT_LABEL, console)
    if report.ok:
        console.print("  /test <path>", style=STYLE_MUTED)
    else:
        console.print("  Fix the reported YAML file and run /validate <path> again.", style=STYLE_MUTED)


def render_not_implemented(command: str, console: Console | None = None) -> None:
    console = console or Console()
    render_section("Command", console)
    console.print(f"  {SYMBOL_WARNING} {command} is not implemented in phase 01", style=STYLE_WARNING)
    render_section(NEXT_LABEL, console)
    console.print("  Use validate-agent for the first real CLI capability.", style=STYLE_MUTED)


def render_requirement_captured(requirement: str, console: Console | None = None) -> None:
    console = console or Console()
    render_section("Requirement", console)
    console.print(f"  {SYMBOL_ADD} Requirement captured", style=STYLE_SUCCESS)
    console.print(f"    {requirement}", style=STYLE_MUTED)
    render_section(NEXT_LABEL, console)
    console.print("  /create-agent --draft", style=STYLE_MUTED)


def render_help(
    commands: list[str],
    console: Console | None = None,
    *,
    pending_requirement: str | None = None,
) -> None:
    console = console or Console()
    groups = _command_groups(commands)
    table = Table(
        box=box.ASCII,
        show_header=True,
        header_style=STYLE_TITLE,
        title="Slash commands",
        title_style=STYLE_TITLE,
    )
    for title, _items in groups:
        table.add_column(title)
    max_rows = max(len(items) for _title, items in groups)
    for index in range(max_rows):
        table.add_row(
            *[items[index] if index < len(items) else "" for _title, items in groups]
        )
    console.print("")
    console.print(table)
    render_section("Session", console)
    render_kv("Pending", pending_requirement or "none", console)


def _status_symbol_and_style(status: EventStatus) -> tuple[str, str]:
    if status == EventStatus.COMPLETED:
        return SYMBOL_ADD, STYLE_SUCCESS
    if status == EventStatus.WARNING:
        return SYMBOL_WARNING, STYLE_WARNING
    if status == EventStatus.FAILED:
        return SYMBOL_FAILED, STYLE_ERROR
    if status == EventStatus.PROGRESS:
        return SYMBOL_CHANGE, STYLE_ACCENT
    return SYMBOL_PROGRESS, STYLE_ACCENT


def _result_status_style(status: str) -> str:
    if status == "completed":
        return STYLE_SUCCESS
    if status == "needs_clarification":
        return STYLE_WARNING
    if status == "failed":
        return STYLE_ERROR
    return STYLE_ACCENT


def _command_groups(commands: list[str]) -> list[tuple[str, list[str]]]:
    create = ["/help", "/exit", "/init", "/create-agent", "/review-agent", "/approve-agent"]
    run = ["/validate", "/test", "/register", "/run", "/upgrade", "/plan-upgrade"]
    ops = ["/review-patch", "/approve-patch", "/apply-patch-plan", "/trace", "/diff", "/approval", "/registry"]
    known = set(create + run + ops)
    extras = [command for command in commands if command not in known]
    command_set = set(commands)
    return [
        ("Create", [command for command in create if command in command_set]),
        ("Run", [command for command in run if command in command_set]),
        ("Ops", [command for command in ops if command in command_set] + extras),
    ]
