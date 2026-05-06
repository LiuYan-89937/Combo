from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from agent_factory import __version__
from agent_factory.application import (
    CreateAgentRequest,
    CreateAgentService,
    InitFactoryRequest,
    InitFactoryService,
)
from agent_factory.cli.rendering import FactoryStreamRenderer, render_create_result, render_init_result
from agent_factory.cli.shell import run_shell

app = typer.Typer(
    name="agentfactory",
    help="Minimal LangGraph 14-stage skeleton.",
    add_completion=False,
    no_args_is_help=True,
)


def _json_echo(data: object) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False))


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", help="Show AgentFactory version."),
) -> None:
    if version:
        typer.echo(f"AgentFactory {__version__}")
        raise typer.Exit()


@app.command("init")
def init_command(
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
) -> None:
    result = InitFactoryService().init_factory(InitFactoryRequest())
    if json_output:
        _json_echo(result.model_dump(mode="json"))
    else:
        render_init_result(result)


@app.command("shell")
def shell_command() -> None:
    run_shell()


@app.command("create-agent")
def create_agent_command(
    prompt: Optional[str] = typer.Option(None, "--prompt", "-p", help="Natural language requirement."),
    stop_after_stage: Optional[str] = typer.Option(
        "capture_requirement",
        "--stop-after-stage",
        help="Stop after this stage. Use empty value to run the full 14-stage skeleton.",
    ),
    stream: bool = typer.Option(False, "--stream/--no-stream", help="Stream stage events."),
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
) -> None:
    if not prompt or not prompt.strip():
        if json_output:
            _json_echo({"error": {"code": "invalid_argument", "message": "--prompt is required"}})
        else:
            typer.echo("Error: --prompt is required")
        raise typer.Exit(code=1)
    stop_value = stop_after_stage.strip() if isinstance(stop_after_stage, str) else None
    if stop_value == "":
        stop_value = None
    request = CreateAgentRequest(prompt=prompt, stop_after_stage=stop_value)
    service = CreateAgentService()
    if stream:
        renderer = FactoryStreamRenderer()
        events = list(service.stream_create_agent(request))
        if json_output:
            _json_echo([event.model_dump(mode="json") for event in events])
        else:
            for event in events:
                renderer.render(event)
            renderer.close()
        return
    result = service.create_agent(request)
    if json_output:
        _json_echo(result.model_dump(mode="json"))
    else:
        render_create_result(result)


@app.command("test-stages")
def test_stages_command(
    prompt: Optional[str] = typer.Option(None, "--prompt", "-p", help="Natural language requirement."),
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
) -> None:
    if not prompt or not prompt.strip():
        if json_output:
            _json_echo({"error": {"code": "invalid_argument", "message": "--prompt is required"}})
        else:
            typer.echo("Error: --prompt is required")
        raise typer.Exit(code=1)
    service = CreateAgentService()
    rows = []
    for stage in service.available_stages():
        result = service.create_agent(CreateAgentRequest(prompt=prompt, stop_after_stage=stage))
        rows.append(
            {
                "stage": stage,
                "status": result.status,
                "breakpoint": result.breakpoint_details,
                "stage_history": result.stage_history,
            }
        )
    if json_output:
        _json_echo(rows)
        return
    typer.echo("")
    for row in rows:
        typer.echo(f"{row['stage']}: {row['status']}")
        typer.echo(f"  history={row['stage_history']}")


if __name__ == "__main__":
    app()
