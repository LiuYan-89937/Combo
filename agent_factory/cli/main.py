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
    ValidateAgentRequest,
    ValidateAgentService,
)
from agent_factory.cli.rendering import (
    render_create_result,
    render_event,
    render_init_result,
    render_not_implemented,
    render_validation_report,
)
from agent_factory.cli.shell import run_shell

app = typer.Typer(
    name="agentfactory",
    help="CLI-first Agent factory framework.",
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
    draft: bool = typer.Option(True, "--draft/--no-draft", help="Create a draft package."),
    stream: bool = typer.Option(True, "--stream/--no-stream", help="Stream human-readable progress."),
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
) -> None:
    if not prompt or not prompt.strip():
        if json_output:
            _json_echo({"error": {"code": "invalid_argument", "message": "--prompt is required"}})
        else:
            typer.echo("Error: --prompt is required")
        raise typer.Exit(code=1)

    service = CreateAgentService()
    request = CreateAgentRequest(prompt=prompt, draft=draft, stream=stream)
    if stream:
        for event in service.stream_create_agent(request):
            if json_output:
                _json_echo(event.model_dump(mode="json"))
            else:
                render_event(event)
        return

    result = service.create_agent(request)
    if json_output:
        _json_echo(result.model_dump(mode="json"))
    else:
        render_create_result(result)


@app.command("validate-agent")
def validate_agent_command(
    path: Path = typer.Argument(..., help="AgentPackage directory."),
    strict: bool = typer.Option(False, "--strict", help="Enable strict validation."),
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
) -> None:
    result = ValidateAgentService().validate_agent(ValidateAgentRequest(path=path, strict=strict))
    if json_output:
        _json_echo(result.report.model_dump(mode="json"))
    else:
        render_validation_report(result.report)
    if not result.ok:
        raise typer.Exit(code=1)


@app.command("test-agent")
def test_agent_command() -> None:
    render_not_implemented("test-agent")
    raise typer.Exit(code=1)


@app.command("register-agent")
def register_agent_command() -> None:
    render_not_implemented("register-agent")
    raise typer.Exit(code=1)


@app.command("run-agent")
def run_agent_command() -> None:
    render_not_implemented("run-agent")
    raise typer.Exit(code=1)


@app.command("upgrade-agent")
def upgrade_agent_command() -> None:
    render_not_implemented("upgrade-agent")
    raise typer.Exit(code=1)


@app.command("plan-upgrade")
def plan_upgrade_command() -> None:
    render_not_implemented("plan-upgrade")
    raise typer.Exit(code=1)


@app.command("approve-patch")
def approve_patch_command() -> None:
    render_not_implemented("approve-patch")
    raise typer.Exit(code=1)


@app.command("apply-patch-plan")
def apply_patch_plan_command() -> None:
    render_not_implemented("apply-patch-plan")
    raise typer.Exit(code=1)


@app.command("registry")
def registry_command() -> None:
    render_not_implemented("registry")
    raise typer.Exit(code=1)


@app.command("trace")
def trace_command() -> None:
    render_not_implemented("trace")
    raise typer.Exit(code=1)


@app.command("diff")
def diff_command() -> None:
    render_not_implemented("diff")
    raise typer.Exit(code=1)


@app.command("approval")
def approval_command() -> None:
    render_not_implemented("approval")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
