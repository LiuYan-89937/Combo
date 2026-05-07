from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from langchain_core.messages import HumanMessage
from rich.console import Console
from rich.prompt import Prompt

from agent_factory.env import load_agentfactory_dotenv
from agent_factory.factory_graph.constants import STAGE_IDS
from agent_factory.factory_graph.runner import FactoryGraphRunner
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
    ] = None,
    show_state: Annotated[bool, typer.Option("--json", help="打印最终 state JSON。")] = False,
) -> None:
    """Run one FactoryGraph build request."""

    load_agentfactory_dotenv()
    _validate_stage(stop_after_stage)
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
def shell() -> None:
    """Open an interactive shell for talking to the Factory Agent graph."""

    load_agentfactory_dotenv()
    ui = FactoryGraphShell(console=console)
    options = FactoryRunOptions()
    prompt_reader = _make_prompt_reader()
    mode: str | None = None
    chat_messages = []
    ui.print_welcome()
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
            continue
        if raw == "/chat":
            mode = "chat"
            chat_messages = []
            console.print("enter chat mode")
            continue
        if raw in {"/create-agent", "/create—agent"}:
            mode = "create_agent"
            console.print("enter create_agent mode")
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
            stage_id = raw.removeprefix("/stop ").strip() or None
            _validate_stage(stage_id)
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
            chat_messages = [*chat_messages, HumanMessage(content=requirement)]
            result = ui.run_chat_once(
                chat_messages,
                show_messages=options.show_messages,
                show_state=options.show_state,
            )
            chat_messages = result.get("messages", chat_messages)
            continue
        run_options = FactoryRunOptions(
            stop_after_stage=options.stop_after_stage,
            show_state=options.show_state,
            show_messages=options.show_messages,
            force_manufacture=mode == "create_agent",
            interaction_mode=mode,
        )
        if requirement:
            ui.run_once(requirement, options=run_options)


def _validate_stage(stage_id: str | None) -> None:
    if stage_id is not None and stage_id not in STAGE_IDS:
        raise typer.BadParameter(f"unknown stage_id: {stage_id}")


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


if __name__ == "__main__":
    app()
