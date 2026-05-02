from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field

from agent_factory.core.types import JsonDumpMixin

HarnessRunStatus = Literal["passed", "failed", "error"]
AssertionStatus = Literal["passed", "failed", "skipped"]


class AssertionResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    id: str
    status: AssertionStatus
    message: str
    expected: Any = None
    actual: Any = None


class ScenarioObservation(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    turn_count: int = 0
    intent: str | None = None
    selected_tool: str | None = None
    tool_available: bool | None = None
    confirmation_required: bool | None = None
    direct_execution_blocked: bool = True
    history_turn_count: int = 0
    tool_result_statuses: dict[str, str] = Field(default_factory=dict)
    tool_summary_fallback: bool = False
    fixture_refs: list[str] = Field(default_factory=list)
    final_response: str = ""


class ScenarioRunResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str
    name: str | None = None
    status: HarnessRunStatus
    observations: ScenarioObservation
    assertion_results: list[AssertionResult] = Field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "passed"

    @property
    def failed_assertion_count(self) -> int:
        return sum(1 for result in self.assertion_results if result.status == "failed")


class HarnessRunResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    package_path: Path
    harness_path: Path
    status: HarnessRunStatus
    scenario_results: list[ScenarioRunResult] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None
    report_path: Path | None = None

    @property
    def ok(self) -> bool:
        return self.status == "passed"

    @property
    def scenario_count(self) -> int:
        return len(self.scenario_results)

    @property
    def passed_count(self) -> int:
        return sum(1 for result in self.scenario_results if result.status == "passed")

    @property
    def failed_count(self) -> int:
        return sum(1 for result in self.scenario_results if result.status in {"failed", "error"})
