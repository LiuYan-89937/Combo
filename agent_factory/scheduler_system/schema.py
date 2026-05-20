from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SchedulerOwnerType = Literal["factory", "agent"]
SchedulerStoreBackend = Literal["sqlite"]
SchedulerScheduleType = Literal["cron", "interval", "date"]
SchedulerTargetType = Literal["graph_run", "script_run", "tool_call"]
SchedulerConcurrencyPolicy = Literal["skip", "queue", "replace"]
SchedulerUnattendedPolicy = Literal["deny_if_approval_required", "pause_and_wait_for_user", "allow_preapproved_only"]
SchedulerRunStatus = Literal["pending", "running", "completed", "failed", "skipped", "cancelled"]
SchedulerThreadPolicy = Literal["new_thread_per_run", "fixed_thread", "inherit_agent_default"]


class SchedulerContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    store_backend: SchedulerStoreBackend = "sqlite"
    store_path: str = "/runtime/scheduler/scheduler.sqlite"
    timezone: str = "Asia/Shanghai"
    default_concurrency_policy: SchedulerConcurrencyPolicy = "skip"
    default_timeout_seconds: int = Field(default=900, ge=1)
    unattended_policy: SchedulerUnattendedPolicy = "deny_if_approval_required"


class SchedulerTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_type: SchedulerTargetType
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_payload(self) -> "SchedulerTarget":
        if self.target_type == "graph_run":
            message = str(self.payload.get("message") or "").strip()
            if not message:
                raise ValueError("graph_run target payload requires message")
            thread_policy = str(self.payload.get("thread_policy") or "new_thread_per_run")
            if thread_policy not in {"new_thread_per_run", "fixed_thread", "inherit_agent_default"}:
                raise ValueError("graph_run target payload has invalid thread_policy")
            if thread_policy == "fixed_thread" and not str(self.payload.get("fixed_thread_id") or "").strip():
                raise ValueError("graph_run target payload fixed_thread requires fixed_thread_id")
        elif self.target_type == "script_run":
            command = self.payload.get("command")
            if not isinstance(command, list) or not all(isinstance(item, str) and item for item in command):
                raise ValueError("script_run target payload requires command as non-empty string array")
        elif self.target_type == "tool_call":
            tool_id = str(self.payload.get("tool_id") or "").strip()
            arguments = self.payload.get("arguments")
            if not tool_id:
                raise ValueError("tool_call target payload requires tool_id")
            if arguments is not None and not isinstance(arguments, dict):
                raise ValueError("tool_call target payload arguments must be an object")
        return self


class SchedulerJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(default_factory=lambda: uuid4().hex)
    owner_type: SchedulerOwnerType
    owner_id: str
    enabled: bool = True
    schedule_type: SchedulerScheduleType
    schedule_expr: str
    timezone: str = "Asia/Shanghai"
    target: SchedulerTarget
    concurrency_policy: SchedulerConcurrencyPolicy = "skip"
    max_concurrent_runs: int = Field(default=1, ge=1)
    timeout_seconds: int = Field(default=900, ge=1)
    retry_policy: dict[str, Any] = Field(default_factory=dict)
    unattended_policy: SchedulerUnattendedPolicy = "deny_if_approval_required"
    created_at: str = Field(default_factory=lambda: utc_now().isoformat())
    updated_at: str = Field(default_factory=lambda: utc_now().isoformat())

    @field_validator("owner_id", "schedule_expr", "timezone")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("value must not be empty")
        return value.strip()

    @model_validator(mode="after")
    def _validate_schedule(self) -> "SchedulerJob":
        from agent_factory.scheduler_system.triggers import validate_schedule_expression

        validate_schedule_expression(
            schedule_type=self.schedule_type,
            schedule_expr=self.schedule_expr,
            timezone=self.timezone,
        )
        return self


class SchedulerRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(default_factory=lambda: uuid4().hex)
    job_id: str
    owner_type: SchedulerOwnerType
    owner_id: str
    target_type: SchedulerTargetType
    status: SchedulerRunStatus = "pending"
    scheduled_at: str
    started_at: str | None = None
    completed_at: str | None = None
    trigger_reason: str = "scheduled"
    output_summary: str | None = None
    error_summary: str | None = None
    event_trace_id: str | None = None
    report_path: str | None = None


class SchedulerLease(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lease_id: str = Field(default_factory=lambda: uuid4().hex)
    job_id: str
    run_id: str
    holder_id: str
    expires_at: str


class SchedulerExecutionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["scheduler_execution_report.v0"] = "scheduler_execution_report.v0"
    run_id: str
    job_id: str
    owner_type: SchedulerOwnerType
    owner_id: str
    target_type: SchedulerTargetType
    status: Literal["completed", "failed", "skipped", "cancelled"]
    started_at: str
    completed_at: str
    duration_ms: int
    output_summary: str | None = None
    error_summary: str | None = None
    stdout_preview: str | None = None
    stderr_preview: str | None = None
    exit_code: int | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_after(seconds: int) -> datetime:
    return utc_now() + timedelta(seconds=seconds)
