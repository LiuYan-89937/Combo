from __future__ import annotations

from pathlib import Path
import sys

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from agent_factory.cli.rendering import (
    FactoryStreamRenderer,
    render_banner,
    render_create_result,
    render_draft_detail,
    render_drafts_list,
    render_event,
    render_help,
    render_not_implemented,
    render_requirement_captured,
    render_test_agent_result,
    render_validation_report,
)
from agent_factory.cli.completion import ContextualSlashCompleter
from agent_factory.cli.slash import SLASH_COMMANDS, SlashCommandDispatcher, SlashCommandResult
from agent_factory.cli.theme import PROMPT, STYLE_ACCENT, STYLE_MUTED


def run_shell() -> None:
    console = Console()
    dispatcher = SlashCommandDispatcher()
    render_banner(console, workspace=Path.cwd(), state="shell")

    prompt_session = _prompt_session(dispatcher)
    while True:
        try:
            line = prompt_session.prompt(PROMPT) if prompt_session else input(PROMPT)
        except (EOFError, KeyboardInterrupt):
            console.print("")
            break

        if _should_open_requirement_box(line, dispatcher, interactive=prompt_session is not None):
            requirement = _read_requirement_box(console, prompt_session)
            if requirement is None:
                console.print("  Requirement input canceled.", style=STYLE_MUTED)
                continue
            dispatcher.session.capture_requirement(requirement)
            render_requirement_captured(requirement, console)

        if _should_stream_create_agent(line):
            error, events = dispatcher.stream_create_agent_events(line)
            if error:
                render_slash_result(error, console)
                continue
            assert events is not None
            stream_renderer = FactoryStreamRenderer(console)
            for event in events:
                stream_renderer.render(event)
            stream_renderer.close()
            continue

        result = dispatcher.dispatch(line)
        render_slash_result(result, console)
        if result.exit_requested:
            break


def render_slash_result(result: SlashCommandResult, console: Console | None = None) -> None:
    console = console or Console()
    if result.kind == "empty":
        return
    if result.kind == "requirement":
        if result.pending_requirement:
            render_requirement_captured(result.pending_requirement, console)
        return
    if result.kind == "help":
        render_help(SLASH_COMMANDS, console, pending_requirement=result.pending_requirement)
        return
    if result.kind == "exit":
        console.print(result.message or "Exiting.")
        return
    if result.kind == "create_agent" and result.create_result:
        render_create_result(result.create_result, console)
        return
    if result.kind == "validate_agent" and result.validation_report:
        render_validation_report(result.validation_report, console)
        return
    if result.kind == "test_agent" and result.test_result:
        render_test_agent_result(result.test_result, console)
        return
    if result.kind == "drafts":
        if result.message:
            console.print("")
            console.print(f"  {result.message}")
        if result.drafts_result:
            render_drafts_list(result.drafts_result, console)
        if result.draft_detail:
            render_draft_detail(result.draft_detail, console)
        return
    if result.kind == "run_agent" and result.run_result:
        console.print("")
        if result.run_result.result:
            console.print(f"  Status: {result.run_result.result.status}")
            console.print(f"  Session: {result.run_result.result.session_id}")
            console.print(f"  History: {result.run_result.result.history_turn_count}")
            console.print(f"  Answer: {result.run_result.result.answer}")
            console.print(f"  Trace: {result.run_result.result.trace_path}")
        else:
            console.print(f"  ! {result.run_result.error}")
        return
    if result.kind == "registry":
        console.print("")
        console.print(f"  {result.message or ''}")
        return
    if result.kind == "not_implemented":
        render_not_implemented(result.command or "command", console)
        return
    if result.message:
        console.print("")
        console.print(f"  ! {result.message}")


def _prompt_session(dispatcher: SlashCommandDispatcher):
    if not sys.stdin.isatty():
        return None
    try:
        from prompt_toolkit import PromptSession
    except ImportError:
        return None

    return PromptSession(
        completer=ContextualSlashCompleter(
            session=dispatcher.session,
            drafts_service=dispatcher.drafts_service,
        )
    )


def _should_stream_create_agent(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("/create-agent"):
        return False
    return "--no-stream" not in stripped.split()


def _should_open_requirement_box(
    line: str,
    dispatcher: SlashCommandDispatcher,
    *,
    interactive: bool,
) -> bool:
    if not interactive:
        return False
    stripped = line.strip()
    if not (stripped == "/create-agent" or stripped.startswith("/create-agent ")):
        return False
    if "--prompt" in stripped or " -p" in f" {stripped}":
        return False
    return not bool(dispatcher.session.pending_requirement)


def _read_requirement_box(console: Console, prompt_session) -> str | None:
    body = Text()
    body.append("Type the Agent requirement below, then press Enter to send.\n", style=STYLE_MUTED)
    body.append("Cancel with ", style=STYLE_MUTED)
    body.append("/cancel", style=STYLE_ACCENT)
    body.append(".", style=STYLE_MUTED)
    console.print("")
    console.print(Panel(body, title="Agent Requirement", border_style=STYLE_ACCENT))

    try:
        line = prompt_session.prompt("│ ") if prompt_session is not None else input("│ ")
    except (EOFError, KeyboardInterrupt):
        return None
    return _collect_requirement_lines(lambda: line)


def _collect_requirement_lines(read_line) -> str | None:
    try:
        line = read_line()
    except (EOFError, KeyboardInterrupt):
        return None
    marker = line.strip()
    if marker in {"/cancel", "/abort"}:
        return None
    if marker in {"/done", "/end"}:
        return None
    requirement = line.strip()
    return requirement or None
