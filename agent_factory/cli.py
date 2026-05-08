from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from langchain_core.messages import HumanMessage
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from agent_factory.env import load_agentfactory_dotenv
from agent_factory.factory_graph.constants import DEFAULT_CREATE_AGENT_BREAKPOINT_STAGE, STAGE_IDS
from agent_factory.factory_graph.runner import FactoryGraphRunner
from agent_factory.factory_graph.session import (
    FactorySessionRecord,
    FactorySessionManager,
    build_factory_checkpointer,
    is_factory_checkpointer_persistent,
)
from agent_factory.factory_graph.shell_cli import FactoryGraphShell, FactoryRunOptions


app = typer.Typer(
    name="agentfactory",
    help="FastAgentFactory command line interface.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def init() -> None:
    """Print the current workspace entry information."""

    console.print("[bold green]FastAgentFactory workspace ready[/bold green]")
    console.print(f"cwd: {Path.cwd()}")
    console.print("try: uv run agentfactory shell")


@app.command("create-agent")
def create_agent(
    prompt: Annotated[str, typer.Option("--prompt", "-p", help="用户想创建的 Agent 需求。")],
    stop_after_stage: Annotated[
        str | None,
        typer.Option("--stop-after-stage", help="运行到指定 FactoryGraph stage 后停止。"),
    ] = DEFAULT_CREATE_AGENT_BREAKPOINT_STAGE,
    show_state: Annotated[bool, typer.Option("--json", help="打印最终 state JSON。")] = False,
) -> None:
    """Run one FactoryGraph build request."""

    load_agentfactory_dotenv()
    stop_after_stage = _normalize_stop_after_stage(stop_after_stage)
    shell = FactoryGraphShell(console=console)
    shell.run_once(
        prompt,
        options=FactoryRunOptions(
            stop_after_stage=stop_after_stage,
            show_state=show_state,
            show_messages=True,
            force_manufacture=True,
            interaction_mode="create_agent",
        ),
    )


@app.command("test-stages")
def test_stages(
    prompt: Annotated[str, typer.Option("--prompt", "-p", help="用于逐阶段测试的需求。")],
) -> None:
    """Run the FactoryGraph skeleton through all stages."""

    load_agentfactory_dotenv()
    result = FactoryGraphRunner().run(requirement=prompt)
    console.print("[bold green]stage skeleton test completed[/bold green]")
    console.print(f"status: {result.get('status')}")
    console.print(f"current_stage: {result.get('current_stage')}")
    console.print(f"stage_log_count: {len(result.get('stage_log', []))}")


@app.command()
def shell(
    resume_latest: Annotated[
        bool,
        typer.Option("--resume-latest", help="启动时恢复最近一次 Factory 会话。"),
    ] = False,
    session_id: Annotated[
        str | None,
        typer.Option("--session-id", help="启动时恢复指定 Factory session_id。"),
    ] = None,
) -> None:
    """Open an interactive shell for talking to the Factory Agent graph."""

    load_agentfactory_dotenv()
    session_manager = FactorySessionManager.from_env()
    session_record = _select_initial_session(
        session_manager,
        session_id=session_id,
        resume_latest=resume_latest,
    )
    checkpointer = build_factory_checkpointer()
    use_checkpoint_memory = is_factory_checkpointer_persistent(checkpointer)
    ui = FactoryGraphShell(console=console, checkpointer=checkpointer)
    options = FactoryRunOptions(stop_after_stage=DEFAULT_CREATE_AGENT_BREAKPOINT_STAGE)
    prompt_reader = _make_prompt_reader()
    mode = session_record.current_mode
    ui.print_welcome()
    _print_active_session(session_record.session_id, mode)
    while True:
        prompt_label = f"factory:{mode}" if mode else "factory"
        try:
            raw = prompt_reader(prompt_label).strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            console.print("bye")
            return
        if not raw:
            continue
        if raw == "/quit":
            console.print("bye")
            return
        if raw == "/exit":
            if mode is None:
                console.print("bye")
                return
            console.print(f"exit {mode} mode")
            mode = None
            session_record = session_manager.set_mode(session_record.session_id, None)
            continue
        if raw == "/chat":
            mode = "chat"
            session_record = session_manager.set_mode(session_record.session_id, mode)
            console.print("enter chat mode")
            continue
        if raw in {"/create-agent", "/create—agent"}:
            mode = "create_agent"
            session_record = session_manager.set_mode(session_record.session_id, mode)
            console.print("enter create_agent mode")
            continue
        if raw == "/session":
            _print_session(session_record)
            continue
        if raw == "/sessions":
            _print_sessions(session_manager.list_sessions())
            continue
        if raw == "/new-session":
            session_record = session_manager.create()
            mode = None
            console.print(f"new session: {session_record.session_id}")
            continue
        if raw.startswith("/resume "):
            session_id = raw.removeprefix("/resume ").strip()
            try:
                session_record = session_manager.load(session_id)
            except FileNotFoundError as exc:
                console.print(f"[red]{exc}[/red]")
                continue
            mode = session_record.current_mode
            console.print(f"resumed session: {session_record.session_id}")
            continue
        if raw == "/help":
            ui.print_help()
            continue
        if raw == "/stages":
            ui.print_stages()
            continue
        if raw == "/tools":
            ui.print_tools()
            continue
        if raw.startswith("/stop "):
            stage_id = _normalize_stop_after_stage(raw.removeprefix("/stop ").strip())
            options.stop_after_stage = stage_id
            console.print(f"stop_after_stage = {stage_id}")
            continue
        if raw.startswith("/state "):
            options.show_state = _parse_on_off(raw.removeprefix("/state ").strip())
            console.print(f"show_state = {options.show_state}")
            continue
        if raw.startswith("/messages "):
            options.show_messages = _parse_on_off(raw.removeprefix("/messages ").strip())
            console.print(f"show_messages = {options.show_messages}")
            continue
        if mode is None:
            console.print("先输入 /chat 或 /create-agent 进入模式。")
            continue
        requirement = raw
        if mode == "chat":
            new_message = HumanMessage(content=requirement)
            chat_messages = [new_message]
            if not use_checkpoint_memory:
                chat_messages = [*session_manager.messages(session_record, "chat"), new_message]
            result = ui.run_chat_once(
                chat_messages,
                thread_id=session_manager.thread_id(session_record, "chat")
                if use_checkpoint_memory
                else None,
                show_messages=options.show_messages,
                show_state=options.show_state,
            )
            session_record = session_manager.replace_messages(
                session_record.session_id,
                "chat",
                result.get("messages", chat_messages),
            )
            continue
        run_options = FactoryRunOptions(
            stop_after_stage=options.stop_after_stage,
            show_state=options.show_state,
            show_messages=options.show_messages,
            force_manufacture=mode == "create_agent",
            interaction_mode=mode,
            thread_id=session_manager.thread_id(session_record, "create_agent"),
        )
        if requirement:
            new_message = HumanMessage(content=requirement)
            create_messages = [new_message]
            if not use_checkpoint_memory:
                create_messages = [
                    *session_manager.messages(session_record, "create_agent"),
                    new_message,
                ]
            run_options.thread_id = (
                session_manager.thread_id(session_record, "create_agent")
                if use_checkpoint_memory
                else None
            )
            result = ui.run_once(requirement, messages=create_messages, options=run_options)
            session_record = session_manager.replace_messages(
                session_record.session_id,
                "create_agent",
                result.get("messages", create_messages),
            )


def _validate_stage(stage_id: str | None) -> None:
    if stage_id is not None and stage_id not in STAGE_IDS:
        raise typer.BadParameter(f"unknown stage_id: {stage_id}")


def _normalize_stop_after_stage(stage_id: str | None) -> str | None:
    if stage_id in {None, "", "off", "none"}:
        return None
    _validate_stage(stage_id)
    return stage_id


def _parse_on_off(value: str) -> bool:
    if value == "on":
        return True
    if value == "off":
        return False
    raise typer.BadParameter("expected on or off")


def _make_prompt_reader():
    try:
        from prompt_toolkit import PromptSession
    except ModuleNotFoundError:
        return lambda label: Prompt.ask(f"[bold cyan]{label}[/bold cyan]")

    session: PromptSession[str] = PromptSession()
    return lambda label: session.prompt(f"{label}: ")


def _select_initial_session(
    session_manager: FactorySessionManager,
    *,
    session_id: str | None,
    resume_latest: bool,
) -> FactorySessionRecord:
    if session_id and resume_latest:
        raise typer.BadParameter("--session-id 和 --resume-latest 只能选择一个")
    if session_id:
        try:
            return session_manager.load(session_id)
        except FileNotFoundError as exc:
            raise typer.BadParameter(str(exc)) from exc
    if resume_latest:
        return session_manager.latest() or session_manager.create()
    return session_manager.create()


def _print_active_session(session_id: str, mode: str | None) -> None:
    console.print(f"session: {session_id}")
    console.print(f"mode: {mode or '-'}")


def _print_session(record: FactorySessionRecord) -> None:
    table = Table(title="Current Factory Session", show_header=True, header_style="bold cyan")
    table.add_column("Field", no_wrap=True)
    table.add_column("Value")
    table.add_row("session_id", record.session_id)
    table.add_row("current_mode", str(record.current_mode or "-"))
    table.add_row("chat_thread_id", record.chat_thread_id)
    table.add_row("create_agent_thread_id", record.create_agent_thread_id)
    table.add_row("chat_turn_count", str(record.chat_turn_count))
    table.add_row("create_agent_turn_count", str(record.create_agent_turn_count))
    table.add_row("updated_at", record.updated_at)
    console.print(table)


def _print_sessions(records: list[FactorySessionRecord]) -> None:
    table = Table(title="Factory Sessions", show_header=True, header_style="bold cyan")
    table.add_column("#", justify="right", no_wrap=True)
    table.add_column("session_id", style="cyan")
    table.add_column("mode")
    table.add_column("chat_turns", justify="right")
    table.add_column("create_turns", justify="right")
    table.add_column("updated_at")
    for index, record in enumerate(records, start=1):
        table.add_row(
            str(index),
            record.session_id,
            str(record.current_mode or "-"),
            str(record.chat_turn_count),
            str(record.create_agent_turn_count),
            record.updated_at,
        )
    console.print(table)


if __name__ == "__main__":
    app()
