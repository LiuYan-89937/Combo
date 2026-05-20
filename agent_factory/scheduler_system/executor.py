from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from agent_factory.scheduler_system.schema import SchedulerExecutionReport, SchedulerJob, SchedulerRun


SchedulerGraphRunner = Callable[[SchedulerJob, SchedulerRun], dict[str, Any]]
SchedulerToolRunner = Callable[[str, dict[str, Any], SchedulerJob, SchedulerRun], dict[str, Any]]
APPROVAL_REQUIRED_RISK_LEVELS = {"medium", "high"}


class SchedulerExecutor:
    def __init__(
        self,
        *,
        graph_runner: SchedulerGraphRunner | None = None,
        tool_runner: SchedulerToolRunner | None = None,
    ) -> None:
        self.graph_runner = graph_runner
        self.tool_runner = tool_runner

    def execute(self, *, job: SchedulerJob, run: SchedulerRun) -> SchedulerExecutionReport:
        started = _now()
        try:
            if job.target.target_type == "graph_run":
                output = self._execute_graph(job, run)
            elif job.target.target_type == "script_run":
                output = self._execute_script(job, run)
            else:
                output = self._execute_tool(job, run)
            status = "completed" if str(output.get("status") or "completed") == "completed" else "failed"
            error_summary = None if status == "completed" else _summary(output.get("error") or output.get("observation_summary"))
            return self._report(
                job=job,
                run=run,
                started=started,
                status=status,
                output_summary=_summary(output.get("output_summary") or output.get("message") or output.get("final_answer")),
                error_summary=error_summary,
                evidence=output,
            )
        except Exception as exc:
            return self._report(
                job=job,
                run=run,
                started=started,
                status="failed",
                error_summary=f"{type(exc).__name__}: {exc}",
                evidence={},
            )

    def _execute_graph(self, job: SchedulerJob, run: SchedulerRun) -> dict[str, Any]:
        if self.graph_runner is None:
            raise RuntimeError("scheduler graph_run target is not configured for this runtime")
        return self.graph_runner(job, run)

    def _execute_script(self, job: SchedulerJob, run: SchedulerRun) -> dict[str, Any]:
        payload = job.target.payload
        command = payload.get("command")
        if self.tool_runner is None:
            raise RuntimeError("scheduler script_run target requires a tool runner")
        return self.tool_runner("bash", {"command": command, **_optional_tool_args(payload)}, job, run)

    def _execute_tool(self, job: SchedulerJob, run: SchedulerRun) -> dict[str, Any]:
        payload = job.target.payload
        tool_id = str(payload.get("tool_id") or "")
        arguments = dict(payload.get("arguments") or {})
        if self.tool_runner is None:
            raise RuntimeError("scheduler tool_call target requires a tool runner")
        return self.tool_runner(tool_id, arguments, job, run)

    def _report(
        self,
        *,
        job: SchedulerJob,
        run: SchedulerRun,
        started: datetime,
        status: str,
        output_summary: str | None = None,
        error_summary: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> SchedulerExecutionReport:
        completed = _now()
        duration_ms = int((completed - started).total_seconds() * 1000)
        evidence = evidence or {}
        return SchedulerExecutionReport(
            run_id=run.run_id,
            job_id=job.job_id,
            owner_type=job.owner_type,
            owner_id=job.owner_id,
            target_type=job.target.target_type,
            status=status,  # type: ignore[arg-type]
            started_at=started.isoformat(),
            completed_at=completed.isoformat(),
            duration_ms=duration_ms,
            output_summary=output_summary,
            error_summary=error_summary,
            stdout_preview=_summary(evidence.get("stdout")),
            stderr_preview=_summary(evidence.get("stderr")),
            exit_code=_exit_code(evidence),
            evidence=evidence,
        )


def runtime_tool_runner(registry: Any) -> SchedulerToolRunner:
    def run(tool_id: str, arguments: dict[str, Any], job: SchedulerJob, run_record: SchedulerRun) -> dict[str, Any]:
        from agent_factory.runtime_kernel.state import RuntimeState

        denial = deny_if_unattended_approval_required(
            job=job,
            tool_id=tool_id,
            model_tool=_model_tool_for_id(registry, tool_id),
        )
        if denial is not None:
            return denial
        state = RuntimeState()
        state.run.agent_id = job.owner_id
        state.run.run_id = run_record.run_id
        state.runtime_config.agent_config["triggered_by"] = "scheduler"
        state.runtime_config.agent_config["scheduler_job_id"] = job.job_id
        result = registry.execute(tool_id, arguments, state=state)
        output = result.output if isinstance(result.output, dict) else {"value": result.output}
        return {
            "status": result.status,
            "error": result.error,
            "observation_summary": result.observation_summary,
            **(output or {}),
        }

    return run


def deny_if_unattended_approval_required(*, job: SchedulerJob, tool_id: str, model_tool: Any | None) -> dict[str, Any] | None:
    if job.unattended_policy != "deny_if_approval_required":
        return None
    risk_level = _risk_level_from_model_tool(model_tool)
    if risk_level not in APPROVAL_REQUIRED_RISK_LEVELS:
        return None
    message = f"scheduler unattended policy denied approval-required tool: {tool_id}"
    return {
        "status": "failed",
        "error": message,
        "observation_summary": message,
        "risk_level": risk_level,
        "unattended_policy": job.unattended_policy,
    }


def _model_tool_for_id(registry: Any, tool_id: str) -> Any | None:
    try:
        tools = registry.model_tools([tool_id])
    except Exception:
        return None
    return tools[0] if tools else None


def _risk_level_from_model_tool(model_tool: Any | None) -> str | None:
    metadata = getattr(model_tool, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    agent_factory = metadata.get("agent_factory")
    if not isinstance(agent_factory, dict):
        return None
    risk_level = agent_factory.get("risk_level")
    return str(risk_level) if risk_level else None


def _optional_tool_args(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ("cwd", "timeout_seconds", "env"):
        if key in payload:
            result[key] = payload[key]
    return result


def _now() -> datetime:
    return datetime.now(UTC)


def _summary(value: Any, limit: int = 500) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text if len(text) <= limit else f"{text[:limit]}..."


def _exit_code(evidence: dict[str, Any]) -> int | None:
    value = evidence.get("exit_code")
    if isinstance(value, int):
        return value
    output = evidence.get("output")
    if isinstance(output, dict) and isinstance(output.get("exit_code"), int):
        return output["exit_code"]
    return None
