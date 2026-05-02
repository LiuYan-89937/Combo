from __future__ import annotations

from pathlib import Path
import sys

from rich.console import Console

from agent_factory.cli.rendering import (
    render_banner,
    render_create_result,
    render_event,
    render_help,
    render_not_implemented,
    render_requirement_captured,
    render_validation_report,
)
from agent_factory.cli.slash import SLASH_COMMANDS, SlashCommandDispatcher, SlashCommandResult
from agent_factory.cli.theme import PROMPT


def run_shell() -> None:
    console = Console()
    dispatcher = SlashCommandDispatcher()
    render_banner(console, workspace=Path.cwd(), state="shell")

    prompt_session = _prompt_session()
    while True:
        try:
            line = prompt_session.prompt(PROMPT) if prompt_session else input(PROMPT)
        except (EOFError, KeyboardInterrupt):
            console.print("")
            break

        if _should_stream_create_agent(line):
            error, events = dispatcher.stream_create_agent_events(line)
            if error:
                render_slash_result(error, console)
                continue
            assert events is not None
            for event in events:
                render_event(event, console)
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
    if result.kind == "not_implemented":
        render_not_implemented(result.command or "command", console)
        return
    if result.message:
        console.print("")
        console.print(f"  ! {result.message}")


def _prompt_session():
    if not sys.stdin.isatty():
        return None
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import WordCompleter
    except ImportError:
        return None

    return PromptSession(
        completer=WordCompleter(
            [
                "/help",
                "/exit",
                "/create-agent",
                "/validate",
                "/test",
                "/run",
                "/registry",
            ],
            ignore_case=True,
        )
    )


def _should_stream_create_agent(line: str) -> bool:
    stripped = line.strip()
    if not stripped.startswith("/create-agent"):
        return False
    return "--no-stream" not in stripped.split()
