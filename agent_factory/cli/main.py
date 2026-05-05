from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer

from agent_factory import __version__
from agent_factory.application import (
    CreateAgentRequest,
    CreateAgentService,
    DraftsService,
    InitFactoryRequest,
    InitFactoryService,
    RegisterAgentRequest,
    RegistryService,
    RepairAgentRequest,
    RepairAgentService,
    RunAgentService,
    RunAgentServiceRequest,
    TestAgentRequest,
    TestAgentService,
    ValidateAgentRequest,
    ValidateAgentService,
)
from agent_factory.application.approval_service import ApprovalService
from agent_factory.application.diff_service import DiffService
from agent_factory.application.patch_plan_service import PatchPlanService
from agent_factory.application.upgrade_agent_service import UpgradeAgentService
from agent_factory.cli.rendering import (
    FactoryStreamRenderer,
    render_create_result,
    render_draft_detail,
    render_drafts_list,
    render_event,
    render_init_result,
    render_not_implemented,
    render_test_agent_result,
    render_validation_report,
)
from agent_factory.cli.shell import run_shell

app = typer.Typer(
    name="agentfactory",
    help="CLI-first Agent factory framework.",
    add_completion=False,
    no_args_is_help=True,
)
agent_app = typer.Typer(
    name="agent",
    help="Create, validate, test, run, repair, and register agents.",
    add_completion=False,
    no_args_is_help=True,
)
drafts_app = typer.Typer(
    name="drafts",
    help="Inspect, select, run, and delete local draft AgentPackages.",
    add_completion=False,
    no_args_is_help=True,
)
registry_app = typer.Typer(
    name="registry",
    help="List, release, and roll back registered agents.",
    add_completion=False,
    no_args_is_help=True,
)
patch_app = typer.Typer(
    name="patch",
    help="Plan, approve, and apply package patch plans.",
    add_completion=False,
    no_args_is_help=True,
)
ops_app = typer.Typer(
    name="ops",
    help="Operational commands for traces, diffs, and approvals.",
    add_completion=False,
    no_args_is_help=True,
)
trace_app = typer.Typer(
    name="trace",
    help="Inspect Factory and Agent trace events.",
    add_completion=False,
    no_args_is_help=True,
)
approval_app = typer.Typer(
    name="approval",
    help="Inspect approval records.",
    add_completion=False,
    no_args_is_help=True,
)

app.add_typer(agent_app, name="agent")
app.add_typer(drafts_app, name="drafts")
app.add_typer(registry_app, name="registry")
app.add_typer(patch_app, name="patch")
app.add_typer(ops_app, name="ops")
ops_app.add_typer(trace_app, name="trace")
ops_app.add_typer(approval_app, name="approval")


def _json_echo(data: object) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False))


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _resolve_trace_path(path: Path | None) -> Path:
    if path is None:
        return Path(".agentfactory") / "traces" / "factory_runs.jsonl"
    if path.is_dir():
        agent_traces = sorted((path / "traces").glob("agent_run_*.jsonl"))
        if agent_traces:
            return agent_traces[-1]
        return path / "generated" / "reports" / "harness_run.json"
    return path


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


@app.command("create-agent", hidden=True)
@agent_app.command("create")
def create_agent_command(
    prompt: Optional[str] = typer.Option(None, "--prompt", "-p", help="Natural language requirement."),
    draft: bool = typer.Option(True, "--draft/--no-draft", help="Create a draft package."),
    stream: bool = typer.Option(False, "--stream/--no-stream", help="Stream human-readable progress."),
    show_thinking: bool = typer.Option(
        False,
        "--show-thinking/--hide-thinking",
        help="Show raw model reasoning and structured-output previews in streamed human output.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
) -> None:
    if not prompt or not prompt.strip():
        if json_output:
            _json_echo({"error": {"code": "invalid_argument", "message": "--prompt is required"}})
        else:
            typer.echo("Error: --prompt is required")
        raise typer.Exit(code=1)

    service = CreateAgentService()
    request = CreateAgentRequest(
        prompt=prompt,
        draft=draft,
        stream=stream,
        show_thinking=show_thinking,
    )
    if stream:
        stream_renderer = FactoryStreamRenderer(show_thinking=show_thinking)
        for event in service.stream_create_agent(request):
            if json_output:
                _json_echo(event.model_dump(mode="json"))
            else:
                stream_renderer.render(event)
        if not json_output:
            stream_renderer.close()
        return

    result = service.create_agent(request)
    if json_output:
        _json_echo(result.model_dump(mode="json"))
    else:
        render_create_result(result)


def _drafts_action(
    action: str = typer.Argument("list", help="list/show/run/use/delete"),
    draft: Optional[str] = typer.Argument(None, help="Draft id, agent name, path, or latest."),
    user_input: Optional[str] = typer.Option(None, "--input", "-i", help="Input for drafts run."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm destructive draft deletion."),
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
) -> None:
    service = DraftsService()
    if action == "list":
        result = service.list_drafts()
        if json_output:
            _json_echo(result.model_dump(mode="json"))
        else:
            render_drafts_list(result)
        return

    if action == "show":
        detail = service.show_draft(draft or "latest")
        if detail is None:
            _draft_not_found(draft, json_output)
            raise typer.Exit(code=1)
        if json_output:
            _json_echo(detail.model_dump(mode="json"))
        else:
            render_draft_detail(detail)
        return

    if action == "use":
        detail = service.show_draft(draft or "latest")
        if detail is None:
            _draft_not_found(draft, json_output)
            raise typer.Exit(code=1)
        if json_output:
            _json_echo(
                {
                    "selected_path": str(detail.summary.path),
                    "message": "CLI commands cannot persist selection; use this path with run-agent.",
                }
            )
        else:
            typer.echo(f"Selected draft path: {detail.summary.path}")
            typer.echo(f"Run: agentfactory run-agent {detail.summary.path} --input \"...\"")
        return

    if action == "run":
        if not user_input:
            if json_output:
                _json_echo({"error": {"code": "invalid_argument", "message": "--input is required"}})
            else:
                typer.echo("Error: --input is required")
            raise typer.Exit(code=1)
        path = service.resolve_draft(draft or "latest")
        if path is None:
            _draft_not_found(draft, json_output)
            raise typer.Exit(code=1)
        result = RunAgentService().run_agent(
            RunAgentServiceRequest(target=str(path), user_input=user_input)
        )
        if json_output:
            _json_echo(result.model_dump(mode="json"))
        else:
            if result.result:
                typer.echo(f"Status: {result.result.status}")
                typer.echo(f"Session: {result.result.session_id}")
                typer.echo(f"History: {result.result.history_turn_count}")
                typer.echo(f"Answer: {result.result.answer}")
                typer.echo(f"Trace: {result.result.trace_path}")
            else:
                typer.echo(f"Error: {result.error}")
        if not result.ok and not (result.result and result.result.status in {"interrupted", "needs_upgrade"}):
            raise typer.Exit(code=1)
        return

    if action in {"delete", "rm", "remove"}:
        try:
            result = service.delete_draft(draft or "latest", confirmed=yes)
        except ValueError as error:
            if json_output:
                _json_echo({"error": {"code": "unsafe_delete_path", "message": str(error)}})
            else:
                typer.echo(f"Error: {error}")
            raise typer.Exit(code=1)
        if result is None:
            _draft_not_found(draft, json_output)
            raise typer.Exit(code=1)
        if json_output:
            _json_echo(result.model_dump(mode="json"))
        else:
            typer.echo(result.message)
            typer.echo(f"Path: {result.path}")
            if not result.deleted:
                typer.echo(f"Run again with: agentfactory drafts delete {draft or 'latest'} --yes")
        if not result.deleted:
            raise typer.Exit(code=1)
        return

    typer.echo("Usage: drafts list|show|use|run|delete [draft] [--input \"...\"] [--yes]")
    raise typer.Exit(code=1)


@drafts_app.command("list")
def drafts_list_command(
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
) -> None:
    _drafts_action(action="list", json_output=json_output)


@drafts_app.command("show")
def drafts_show_command(
    draft: Optional[str] = typer.Argument("latest", help="Draft id, agent name, path, or latest."),
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
) -> None:
    _drafts_action(action="show", draft=draft, json_output=json_output)


@drafts_app.command("use")
def drafts_use_command(
    draft: Optional[str] = typer.Argument("latest", help="Draft id, agent name, path, or latest."),
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
) -> None:
    _drafts_action(action="use", draft=draft, json_output=json_output)


@drafts_app.command("run")
def drafts_run_command(
    draft: Optional[str] = typer.Argument("latest", help="Draft id, agent name, path, or latest."),
    user_input: Optional[str] = typer.Option(None, "--input", "-i", help="Input for drafts run."),
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
) -> None:
    _drafts_action(action="run", draft=draft, user_input=user_input, json_output=json_output)


@drafts_app.command("delete")
def drafts_delete_command(
    draft: Optional[str] = typer.Argument("latest", help="Draft id, agent name, path, or latest."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm destructive draft deletion."),
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
) -> None:
    _drafts_action(action="delete", draft=draft, yes=yes, json_output=json_output)


@drafts_app.command("rm", hidden=True)
def drafts_rm_command(
    draft: Optional[str] = typer.Argument("latest", help="Draft id, agent name, path, or latest."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm destructive draft deletion."),
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
) -> None:
    _drafts_action(action="delete", draft=draft, yes=yes, json_output=json_output)


def _draft_not_found(draft: str | None, json_output: bool) -> None:
    message = f"Draft not found: {draft or 'latest'}"
    if json_output:
        _json_echo({"error": {"code": "draft_not_found", "message": message}})
    else:
        typer.echo(f"Error: {message}")


@app.command("validate-agent", hidden=True)
@agent_app.command("validate")
def validate_agent_command(
    path: Path = typer.Argument(..., help="AgentPackage directory."),
    strict: bool = typer.Option(False, "--strict", help="Enable strict validation."),
    primitives_only: bool = typer.Option(
        False,
        "--primitives-only",
        help="Validate only the nine building-primitives YAML files.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
) -> None:
    result = ValidateAgentService().validate_agent(
        ValidateAgentRequest(path=path, strict=strict, primitives_only=primitives_only)
    )
    if json_output:
        _json_echo(result.report.model_dump(mode="json"))
    else:
        render_validation_report(result.report)
    if not result.ok:
        raise typer.Exit(code=1)


@app.command("test-agent", hidden=True)
@agent_app.command("test")
def test_agent_command(
    path: Path = typer.Argument(..., help="AgentPackage directory."),
    scenario: Optional[str] = typer.Option(None, "--scenario", help="Run a specific scenario id."),
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
) -> None:
    result = TestAgentService().test_agent(TestAgentRequest(path=path, scenario=scenario))
    if json_output:
        _json_echo(result.model_dump(mode="json"))
    else:
        render_test_agent_result(result)
    if not result.ok:
        raise typer.Exit(code=1)


@app.command("register-agent", hidden=True)
@agent_app.command("register")
def register_agent_command(
    path: Path = typer.Argument(..., help="AgentPackage directory."),
    status: str = typer.Option("candidate", "--status", help="Registry status."),
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
) -> None:
    record = RegistryService().register(RegisterAgentRequest(package_path=path, status=status))
    if json_output:
        _json_echo(record.model_dump(mode="json"))
    else:
        typer.echo(f"Registered {record.agent_name}@{record.version} as {record.status}")


@app.command("run-agent", hidden=True)
@agent_app.command("run")
def run_agent_command(
    target: str = typer.Argument(..., help="AgentPackage path or registered agent name."),
    user_input: Optional[str] = typer.Option(None, "--input", "-i", help="User input."),
    version: Optional[str] = typer.Option(None, "--version", help="Registry version."),
    session_id: str = typer.Option("default", "--session-id", help="Conversation session id."),
    chat: bool = typer.Option(False, "--chat", help="Start a simple interactive chat loop."),
    process: bool = typer.Option(False, "--process/--no-process", help="Run in an isolated process."),
    auto_repair: bool = typer.Option(False, "--auto-repair", help="Return to Factory repair on failed run."),
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
) -> None:
    if chat:
        while True:
            line = typer.prompt("you", default="", show_default=False)
            if not line.strip() or line.strip() in {"/exit", "exit", "quit"}:
                break
            result = RunAgentService().run_agent(
                RunAgentServiceRequest(
                    target=target,
                    user_input=line,
                    version=version,
                    session_id=session_id,
                    process=process,
                    auto_repair=auto_repair,
                )
            )
            if json_output:
                _json_echo(result.model_dump(mode="json"))
            elif result.result:
                typer.echo(result.result.answer)
            else:
                typer.echo(f"Error: {result.error}")
        return
    if not user_input:
        if json_output:
            _json_echo({"error": {"code": "invalid_argument", "message": "--input is required unless --chat is used"}})
        else:
            typer.echo("Error: --input is required unless --chat is used")
        raise typer.Exit(code=1)
    result = RunAgentService().run_agent(
        RunAgentServiceRequest(
            target=target,
            user_input=user_input,
            version=version,
            session_id=session_id,
            process=process,
            auto_repair=auto_repair,
        )
    )
    if json_output:
        _json_echo(result.model_dump(mode="json"))
    else:
        if result.result:
            typer.echo(f"Status: {result.result.status}")
            typer.echo(f"Session: {result.result.session_id}")
            typer.echo(f"History: {result.result.history_turn_count}")
            typer.echo(f"Answer: {result.result.answer}")
            typer.echo(f"Trace: {result.result.trace_path}")
        else:
            typer.echo(f"Error: {result.error}")
        if result.repair_result:
            _render_repair_summary(result.repair_result)
    repair_ok = bool(result.repair_result and result.repair_result.get("status") == "repaired")
    if not result.ok and not repair_ok and not (result.result and result.result.status in {"interrupted", "needs_upgrade"}):
        raise typer.Exit(code=1)


@app.command("repair-agent", hidden=True)
@agent_app.command("repair")
def repair_agent_command(
    target: str = typer.Argument("latest", help="AgentPackage path, draft id, or registered agent name."),
    user_input: Optional[str] = typer.Option(None, "--input", "-i", help="Input that failed; rerun after repair."),
    version: Optional[str] = typer.Option(None, "--version", help="Registry version."),
    session_id: str = typer.Option("default", "--session-id", help="Conversation session id."),
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
) -> None:
    result = RepairAgentService().repair_agent(
        RepairAgentRequest(
            target=target,
            user_input=user_input,
            version=version,
            session_id=session_id,
        )
    )
    if json_output:
        _json_echo(result.model_dump(mode="json"))
    else:
        typer.echo(f"Repair status: {result.status}")
        if result.reason:
            typer.echo(f"Reason: {result.reason}")
        if result.candidate_path:
            typer.echo(f"Candidate: {result.candidate_path}")
        for patch in result.patches:
            typer.echo(f"- {patch.action}: {patch.path} ({patch.message})")
        if result.rerun_result:
            typer.echo(f"Self-test: {result.rerun_result.status}")
            typer.echo(f"Answer: {result.rerun_result.answer}")
        for step in result.next_steps:
            typer.echo(f"Next: {step}")
    if result.status not in {"repaired", "not_needed"}:
        raise typer.Exit(code=1)


def _render_repair_summary(payload: dict[str, object]) -> None:
    typer.echo("Repair:")
    typer.echo(f"  Status: {payload.get('status')}")
    if payload.get("reason"):
        typer.echo(f"  Reason: {payload.get('reason')}")
    if payload.get("candidate_path"):
        typer.echo(f"  Candidate: {payload.get('candidate_path')}")


@app.command("upgrade-agent", hidden=True)
@agent_app.command("upgrade")
def upgrade_agent_command(
    agent_name: str = typer.Argument(...),
    prompt: str = typer.Option(..., "--prompt", "-p"),
    source_path: Optional[Path] = typer.Option(None, "--source-path"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    request = UpgradeAgentService().create_request(
        agent_name,
        prompt=prompt,
        source_path=source_path,
    )
    if json_output:
        _json_echo(request.model_dump(mode="json"))
    else:
        typer.echo(f"UpgradeRequest: {request.request_id} ({request.proposed_intent})")


@app.command("plan-upgrade", hidden=True)
@patch_app.command("plan")
def plan_upgrade_command(
    package_path: Path = typer.Argument(..., help="Base AgentPackage directory."),
    prompt: str = typer.Option("根据用户补充需求升级 Agent", "--prompt", "-p"),
    target_version: str = typer.Option("1.1.0", "--target-version"),
    output: Optional[Path] = typer.Option(None, "--output"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    service = PatchPlanService()
    plan = service.plan_upgrade(package_path, prompt=prompt, target_version=target_version)
    if output:
        service.write_plan(plan, output)
    if json_output:
        _json_echo(plan.model_dump(mode="json"))
    else:
        typer.echo(f"PatchPlan: {plan.plan_id}")
        for change in plan.changes:
            typer.echo(f"- {change.id}: {change.action} {change.path}")


@app.command("approve-patch", hidden=True)
@patch_app.command("approve")
def approve_patch_command(
    change_id: str = typer.Argument(...),
    actor: str = typer.Option("user", "--actor"),
    patch_plan: Optional[Path] = typer.Option(None, "--patch-plan"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    record = ApprovalService().create(change_id=change_id, actor=actor, patch_plan=patch_plan)
    if json_output:
        _json_echo(record.model_dump(mode="json"))
    else:
        typer.echo(f"Approved {record.change_id} by {record.actor}")


@app.command("apply-patch-plan", hidden=True)
@patch_app.command("apply")
def apply_patch_plan_command(
    package_path: Path = typer.Argument(..., help="Base AgentPackage directory."),
    output: Path = typer.Option(..., "--output"),
    target_version: str = typer.Option("1.1.0", "--target-version"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    service = PatchPlanService()
    plan = service.plan_upgrade(package_path, prompt="根据用户补充需求升级 Agent", target_version=target_version)
    path = service.apply_plan(plan, output)
    if json_output:
        _json_echo({"output_path": str(path), "plan": plan.model_dump(mode="json")})
    else:
        typer.echo(f"Applied patch plan to {path}")


def _registry_action(
    action: str = typer.Argument("list", help="list/show/versions/rollback"),
    agent_name: Optional[str] = typer.Argument(None),
    version: Optional[str] = typer.Option(None, "--version"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    service = RegistryService()
    if action == "list":
        result = service.list()
        if json_output:
            _json_echo(result.model_dump(mode="json"))
        else:
            for record in result.records:
                typer.echo(f"{record.agent_name}@{record.version} {record.status}")
        return
    if action == "rollback" and agent_name and version:
        record = service.rollback(agent_name, version)
        _json_echo(record.model_dump(mode="json")) if json_output else typer.echo(
            f"Rolled back {record.agent_name} to {record.version}"
        )
        return
    typer.echo("Usage: registry list|rollback <agent-name> --version <version>")
    raise typer.Exit(code=1)


@registry_app.command("list")
def registry_list_command(
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _registry_action(action="list", json_output=json_output)


@registry_app.command("rollback")
def registry_rollback_command(
    agent_name: str = typer.Argument(...),
    version: str = typer.Option(..., "--version"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _registry_action(action="rollback", agent_name=agent_name, version=version, json_output=json_output)


def _trace_action(
    action: str = typer.Argument("list"),
    path: Optional[Path] = typer.Option(None, "--path", help="Trace JSONL path or package directory."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    trace_path = _resolve_trace_path(path)
    rows = _read_jsonl(trace_path)
    if action == "list":
        if json_output:
            _json_echo(rows)
        else:
            for row in rows[-20:]:
                typer.echo(f"{row.get('run_id', '-')} {row.get('stage', '-')} {row.get('status', '-')}")
        return
    if action == "show":
        payload = rows[-1] if rows else {}
        _json_echo(payload) if json_output else typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    raise typer.Exit(code=1)


@app.command("trace", hidden=True)
def trace_command(
    action: str = typer.Argument("list"),
    path: Optional[Path] = typer.Option(None, "--path", help="Trace JSONL path or package directory."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _trace_action(action=action, path=path, json_output=json_output)


@trace_app.command("list")
def trace_list_command(
    path: Optional[Path] = typer.Option(None, "--path", help="Trace JSONL path or package directory."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _trace_action(action="list", path=path, json_output=json_output)


@trace_app.command("show")
def trace_show_command(
    path: Optional[Path] = typer.Option(None, "--path", help="Trace JSONL path or package directory."),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _trace_action(action="show", path=path, json_output=json_output)


@app.command("diff", hidden=True)
@ops_app.command("diff")
def diff_command(
    base_path: Path = typer.Argument(...),
    target_path: Path = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    result = DiffService().diff(base_path, target_path)
    if json_output:
        _json_echo(result.model_dump(mode="json"))
    else:
        for entry in result.entries:
            typer.echo(f"{entry.change_type}: {entry.path}")


def _approval_action(
    action: str = typer.Argument("list"),
    approval_id: Optional[str] = typer.Argument(None),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    service = ApprovalService()
    if action == "list":
        records = service.list()
        if json_output:
            _json_echo([record.model_dump(mode="json") for record in records])
        else:
            for record in records:
                typer.echo(f"{record.approval_id} {record.change_id} {record.decision}")
        return
    if action == "show" and approval_id:
        record = service.show(approval_id)
        if record is None:
            raise typer.Exit(code=1)
        _json_echo(record.model_dump(mode="json")) if json_output else typer.echo(record.model_dump_json(indent=2))
        return
    raise typer.Exit(code=1)


@app.command("approval", hidden=True)
def approval_command(
    action: str = typer.Argument("list"),
    approval_id: Optional[str] = typer.Argument(None),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _approval_action(action=action, approval_id=approval_id, json_output=json_output)


@approval_app.command("list")
def approval_list_command(
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _approval_action(action="list", json_output=json_output)


@approval_app.command("show")
def approval_show_command(
    approval_id: str = typer.Argument(...),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    _approval_action(action="show", approval_id=approval_id, json_output=json_output)


@app.command("release", hidden=True)
@registry_app.command("release")
def release_command(
    agent_name: str = typer.Argument(...),
    version: str = typer.Option(..., "--version"),
    channel: str = typer.Option("available", "--channel"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    record = RegistryService().release(agent_name, version, channel)
    if json_output:
        _json_echo(record.model_dump(mode="json"))
    else:
        typer.echo(f"Released {record.agent_name}@{record.version} as {record.status}")


if __name__ == "__main__":
    app()
