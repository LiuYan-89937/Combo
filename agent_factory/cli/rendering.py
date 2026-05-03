from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from agent_factory.application import (
    CreateAgentResult,
    DraftAgentDetail,
    DraftsListResult,
    InitFactoryResult,
    TestAgentResult,
)
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
    questions = _event_questions(event)
    for question in questions:
        console.print(f"    {SYMBOL_WARNING} {question}", style=STYLE_WARNING)
    if event.stage == "analyze_requirement" and not questions:
        details = _analysis_details(event)
        if details:
            console.print(f"    {details}", style=STYLE_MUTED)
    if event.artifact_path:
        render_kv("path", event.artifact_path, console)


class FactoryStreamRenderer:
    """Render Factory stream as one active node plus collapsed summaries."""

    def __init__(self, console: Console | None = None, *, show_thinking: bool = False) -> None:
        self.console = console or Console()
        self.show_thinking = show_thinking
        self._live: Live | None = None
        self._current_stage: str | None = None
        self._tool_statuses: dict[str, dict[str, Any]] = {}

    def render(self, event: FactoryEvent) -> None:
        if event.status == EventStatus.PROGRESS and event.payload.get("stream_kind") == "node_thinking":
            self._show_current_node(event)
            return
        self._close_current()
        render_event(event, self.console)

    def close(self) -> None:
        self._close_current()

    def _show_current_node(self, event: FactoryEvent) -> None:
        if not self.console.is_terminal:
            render_event(event, self.console)
            return
        if self._live is None:
            self._current_stage = event.stage
            self._tool_statuses = {}
            self._record_node_progress(event)
            self._live = Live(
                self._node_panel(event),
                console=self.console,
                refresh_per_second=8,
                transient=True,
            )
            self._live.start()
            return
        if self._current_stage != event.stage:
            self._close_current()
            self._show_current_node(event)
            return
        self._record_node_progress(event)
        self._live.update(self._node_panel(event))

    def _close_current(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None
            self._current_stage = None
            self._tool_statuses = {}

    def _record_node_progress(self, event: FactoryEvent) -> None:
        if event.stage != "generate_tool_scripts":
            return
        tool_id = event.payload.get("tool_id")
        if not tool_id:
            return
        key = str(tool_id)
        previous = self._tool_statuses.get(key, {})
        self._tool_statuses[key] = {**previous, **event.payload}

    def _node_panel(self, event: FactoryEvent) -> Panel:
        items: list[Any] = [Text(event.title, style=STYLE_TITLE)]
        if event.message:
            items.append(Text(event.message, style=STYLE_MUTED))
        if self.show_thinking:
            thinking = event.payload.get("thinking")
            if thinking:
                items.append(Text(""))
                items.append(Text(_thinking_label(event), style=STYLE_ACCENT))
                items.append(Text(str(thinking), style=STYLE_MUTED))
        else:
            flow_lines = _flow_lines(event)
            if flow_lines:
                items.append(Text(""))
                items.append(Text("Flow", style=STYLE_ACCENT))
                for line in flow_lines:
                    items.append(Text(line, style=STYLE_MUTED))
            tool_table = self._tool_progress_table(event)
            if tool_table:
                items.append(Text(""))
                items.append(Text("Tools", style=STYLE_ACCENT))
                items.append(tool_table)
            thinking_kind = event.payload.get("thinking_kind")
            if thinking_kind:
                items.append(Text(""))
                items.append(
                    Text(
                        "Thinking detail hidden. Re-run with --show-thinking to inspect raw reasoning.",
                        style=STYLE_MUTED,
                    )
                )
        details = _analysis_details(event)
        if details:
            items.append(Text(""))
            items.append(Text(details, style=STYLE_MUTED))
        return Panel(
            Group(*items),
            title=f"Factory node: {event.stage}",
            border_style=STYLE_ACCENT,
            box=box.ASCII,
            padding=(1, 2),
        )

    def _tool_progress_table(self, event: FactoryEvent) -> Table | None:
        if event.stage != "generate_tool_scripts":
            return None
        statuses = dict(self._tool_statuses)
        tool_id = event.payload.get("tool_id")
        if tool_id and str(tool_id) not in statuses:
            statuses[str(tool_id)] = dict(event.payload)
        if not statuses:
            return None
        table = Table(
            box=box.ASCII,
            show_header=True,
            header_style=STYLE_TITLE,
            expand=False,
        )
        table.add_column("#", justify="right")
        table.add_column("Tool")
        table.add_column("Phase")
        table.add_column("Result")
        for payload in sorted(statuses.values(), key=_tool_sort_key):
            table.add_row(
                _tool_index_label(payload),
                str(payload.get("tool_id") or "-"),
                _human_flow_phase(str(payload.get("tool_phase") or "processing")),
                _tool_result_label(payload),
            )
        return table


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
    if result.verification_report:
        render_section("Local verification", console)
        render_kv(
            "Status",
            result.verification_report.status,
            console,
            style=_result_status_style(_verification_status_style_key(result.verification_report.status)),
        )
        render_kv("Issues", result.verification_report.issue_count, console)
        if result.verification_report.tool_static_check:
            render_kv("Tool static", result.verification_report.tool_static_check.status, console)
        if result.verification_report.tool_tests:
            render_kv("Tool tests", result.verification_report.tool_tests.status, console)
        if result.verification_report.mcp_binding_check:
            render_kv("MCP binding", result.verification_report.mcp_binding_check.status, console)
        if result.verification_report.harness_dry_run:
            render_kv("Harness dry-run", result.verification_report.harness_dry_run.status, console)
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


def render_test_agent_result(result: TestAgentResult, console: Console | None = None) -> None:
    console = console or Console()
    status_style = STYLE_SUCCESS if result.ok else STYLE_ERROR
    render_section("AgentHarness", console)
    render_kv("Status", result.status, console, style=status_style)
    render_kv("Package", result.package_path, console)
    render_kv("Validation", "passed" if result.validation_report.ok else "failed", console)
    if result.verification_report:
        render_kv("Verification", result.verification_report.status, console)
    if result.harness_path:
        render_kv("Harness", result.harness_path, console)
    if result.harness_run and result.harness_run.report_path:
        render_kv("Run report", result.harness_run.report_path, console)
    render_kv("Scenarios", result.scenario_count, console)
    if result.scenarios:
        render_section("Scenarios", console)
        table = Table(
            box=box.ASCII,
            show_header=True,
            header_style=STYLE_TITLE,
            expand=False,
        )
        table.add_column("ID")
        table.add_column("Name")
        table.add_column("Status")
        table.add_column("Assertions")
        for scenario in result.scenarios:
            table.add_row(
                scenario.id,
                scenario.name or "-",
                scenario.status,
                f"{scenario.assertion_count - scenario.failed_assertions}/{scenario.assertion_count}",
            )
        console.print(table)
    if result.issues:
        render_section("Issues", console)
        table = Table(
            box=box.ASCII,
            show_header=True,
            header_style=STYLE_TITLE,
            expand=False,
        )
        table.add_column("Code")
        table.add_column("Location")
        table.add_column("Message")
        for issue in result.issues:
            table.add_row(issue.code, issue.path or "-", issue.message)
        console.print(table)
    render_section(NEXT_LABEL, console)
    for step in result.next_steps:
        console.print(f"  {step}", style=STYLE_MUTED)


def render_drafts_list(result: DraftsListResult, console: Console | None = None) -> None:
    console = console or Console()
    render_section("Draft agents", console)
    render_kv("Drafts", result.drafts_path, console)
    render_kv("Count", len(result.drafts), console)
    if not result.drafts:
        render_section(NEXT_LABEL, console)
        console.print("  /create-agent --draft", style=STYLE_MUTED)
        return

    table = Table(
        box=box.ASCII,
        show_header=True,
        header_style=STYLE_TITLE,
        expand=False,
    )
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Version")
    table.add_column("Validation")
    table.add_column("Verification")
    table.add_column("Tools")
    table.add_column("Scenarios")
    for draft in result.drafts:
        table.add_row(
            draft.id,
            draft.agent_name,
            draft.version or "-",
            draft.validation_status,
            draft.verification_status,
            str(draft.tool_count),
            str(draft.harness_scenario_count),
        )
    console.print(table)
    render_section(NEXT_LABEL, console)
    console.print("  /drafts show latest", style=STYLE_MUTED)
    console.print("  /drafts use latest", style=STYLE_MUTED)
    console.print("  /run --input \"...\"", style=STYLE_MUTED)


def render_draft_detail(detail: DraftAgentDetail, console: Console | None = None) -> None:
    console = console or Console()
    summary = detail.summary
    render_section("Draft agent", console)
    render_kv("ID", summary.id, console)
    render_kv("Name", summary.agent_name, console, style=STYLE_SUCCESS)
    render_kv("Agent ID", summary.agent_id, console)
    render_kv("Version", summary.version, console)
    render_kv("Status", summary.status, console)
    render_kv("Path", summary.path, console)
    render_kv("Validation", summary.validation_status, console)
    render_kv("Verification", summary.verification_status, console)
    if detail.persona:
        render_section("Behavior", console)
        render_kv("Persona", detail.persona, console)
    if detail.goal:
        render_kv("Goal", detail.goal, console)
    if detail.boundaries:
        render_section("Boundaries", console)
        for boundary in detail.boundaries[:8]:
            console.print(f"  - {boundary}", style=STYLE_MUTED)
    render_section("Capabilities", console)
    render_kv("Tools", ", ".join(detail.tool_ids) or "none", console)
    render_kv("MCP bindings", ", ".join(detail.mcp_binding_ids) or "none", console)
    render_kv("Harness", ", ".join(detail.scenario_ids) or "none", console)
    if detail.validation_report and detail.validation_report.issues:
        render_section("Validation issues", console)
        for issue in detail.validation_report.issues[:5]:
            location = issue.file or "-"
            if issue.path:
                location = f"{location}:{issue.path}"
            console.print(f"  {SYMBOL_WARNING} {issue.code} {location} {issue.message}", style=STYLE_WARNING)
    render_section(NEXT_LABEL, console)
    for step in detail.next_steps:
        console.print(f"  {step}", style=STYLE_MUTED)


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
    console.print("  /create-agent", style=STYLE_MUTED)


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


def _event_questions(event: FactoryEvent) -> list[str]:
    raw_questions = event.payload.get("clarification_questions") or event.payload.get("questions")
    if not isinstance(raw_questions, list):
        return []
    return [str(question) for question in raw_questions if str(question).strip()]


def _analysis_details(event: FactoryEvent) -> str:
    pairs = []
    for key in ["agent_name", "agent_type", "safety_profile", "analysis_source"]:
        value = event.payload.get(key)
        if value:
            pairs.append(f"{key}={value}")
    return ", ".join(pairs)


def _flow_lines(event: FactoryEvent) -> list[str]:
    payload = event.payload
    lines: list[str] = []
    flow_summary = payload.get("flow_summary")
    if flow_summary:
        lines.extend(_split_flow_text(str(flow_summary)))
    tool_id = payload.get("tool_id")
    if tool_id:
        index = payload.get("tool_index")
        total = payload.get("tool_total")
        phase = payload.get("tool_phase") or payload.get("phase") or "processing"
        prefix = f"Tool {index}/{total}" if index and total else "Tool"
        line = f"{prefix}: {tool_id} - {phase}"
        if line not in lines:
            lines.append(line)
    if payload.get("reasoning_chars") or payload.get("content_chars"):
        reasoning_chars = int(payload.get("reasoning_chars") or 0)
        content_chars = int(payload.get("content_chars") or 0)
        lines.append(
            f"Model stream received: reasoning={reasoning_chars} chars, structured={content_chars} chars."
        )
    if not lines and event.message:
        lines.append(event.message)
    if not lines:
        lines.append(event.title)
    return lines[:6]


def _split_flow_text(value: str) -> list[str]:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines and value.strip():
        lines = [value.strip()]
    return lines


def _thinking_label(event: FactoryEvent) -> str:
    kind = event.payload.get("thinking_kind")
    if kind == "reasoning":
        return "Thinking detail"
    if kind == "content":
        return "Structured output detail"
    return "Working notes"


def _tool_sort_key(payload: dict[str, Any]) -> tuple[int, str]:
    try:
        index = int(payload.get("tool_index") or 9999)
    except (TypeError, ValueError):
        index = 9999
    return index, str(payload.get("tool_id") or "")


def _tool_index_label(payload: dict[str, Any]) -> str:
    index = payload.get("tool_index")
    total = payload.get("tool_total")
    if index and total:
        return f"{index}/{total}"
    if index:
        return str(index)
    return "-"


def _tool_result_label(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    if payload.get("fallback_used"):
        parts.append("fallback")
    error_count = payload.get("error_count")
    if error_count:
        parts.append(f"issues={error_count}")
    artifact_path = payload.get("artifact_path")
    if artifact_path:
        parts.append("written")
    return ", ".join(parts) or "running"


def _human_flow_phase(phase: str) -> str:
    return {
        "contracts_generated": "contracts generated",
        "model_generation_started": "model call started",
        "model_generated": "model code accepted",
        "model_repaired": "model code repaired",
        "deterministic_fallback": "deterministic fallback",
        "generic_fallback": "generic fallback",
        "written": "files written",
    }.get(phase, phase.replace("_", " "))


def _result_status_style(status: str) -> str:
    if status == "completed":
        return STYLE_SUCCESS
    if status == "needs_clarification":
        return STYLE_WARNING
    if status == "failed":
        return STYLE_ERROR
    return STYLE_ACCENT


def _verification_status_style_key(status: str) -> str:
    if status == "passed":
        return "completed"
    if status == "failed":
        return "failed"
    return "running"


def _command_groups(commands: list[str]) -> list[tuple[str, list[str]]]:
    create = ["/help", "/exit", "/init", "/create-agent", "/drafts", "/review-agent", "/approve-agent"]
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
