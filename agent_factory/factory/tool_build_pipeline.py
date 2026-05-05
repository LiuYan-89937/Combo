from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory.package_artifacts import PackageArtifactGenerator
from agent_factory.factory.package_verification import PackageVerificationRunner
from agent_factory.specs import AgentPackagePrimitives, ResourceContractsSpec


ToolBuildStatus = Literal[
    "draft",
    "generated",
    "static_checked",
    "tested",
    "available",
    "requires_approval",
    "disabled",
    "failed",
    "deprecated",
]


class ToolBuildReport(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    status: Literal["passed", "passed_with_warnings", "failed"] = "failed"
    tool_states: dict[str, ToolBuildStatus] = Field(default_factory=dict)
    artifact_paths: list[Path] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    repair_attempts: int = 0
    max_repair_attempts: int = 3

    @property
    def ok(self) -> bool:
        return self.status in {"passed", "passed_with_warnings"}


class ToolStateMachine:
    """Guarded tool build lifecycle transitions."""

    allowed_transitions: dict[ToolBuildStatus, set[ToolBuildStatus]] = {
        "draft": {"generated", "failed", "disabled"},
        "generated": {"static_checked", "failed", "requires_approval"},
        "static_checked": {"tested", "failed", "requires_approval"},
        "tested": {"available", "failed", "requires_approval"},
        "available": {"deprecated", "disabled"},
        "requires_approval": {"available", "disabled", "failed"},
        "disabled": {"deprecated"},
        "failed": {"draft", "disabled"},
        "deprecated": set(),
    }

    def transition(self, current: ToolBuildStatus, target: ToolBuildStatus) -> ToolBuildStatus:
        if target not in self.allowed_transitions[current]:
            raise ValueError(f"Invalid tool build transition: {current} -> {target}")
        return target


class ToolBuildPipeline:
    """Contract-first tool build pipeline wrapper.

    Existing production graph nodes still expose each step separately for CLI
    progress, but this class is the single reusable implementation boundary for
    tests and future graph simplification.
    """

    def __init__(
        self,
        *,
        artifact_generator: PackageArtifactGenerator | None = None,
        verification_runner: PackageVerificationRunner | None = None,
        state_machine: ToolStateMachine | None = None,
        max_repair_attempts: int = 3,
    ) -> None:
        self.artifact_generator = artifact_generator or PackageArtifactGenerator()
        self.verification_runner = verification_runner or PackageVerificationRunner()
        self.state_machine = state_machine or ToolStateMachine()
        self.max_repair_attempts = max_repair_attempts

    def build(
        self,
        package_path: Path,
        primitives: AgentPackagePrimitives,
        *,
        requirement: str | None = None,
        requirement_analysis: dict[str, Any] | None = None,
        resource_contracts: ResourceContractsSpec | None = None,
    ) -> ToolBuildReport:
        report = ToolBuildReport(max_repair_attempts=self.max_repair_attempts)
        tool_ids = [
            tool_id
            for toolset in primitives.toolsets.toolsets
            for tool_id in [*toolset.exposed_tools, *toolset.hidden_tools]
        ]
        report.tool_states = {tool_id: "draft" for tool_id in tool_ids}

        generated = self.artifact_generator.generate_tool_scripts(
            package_path,
            primitives,
            requirement=requirement,
            requirement_analysis=requirement_analysis,
            resource_contracts=resource_contracts,
        )
        report.artifact_paths.extend(generated.artifact_paths)
        report.issues.extend(generated.issues)
        for tool_id in report.tool_states:
            report.tool_states[tool_id] = self.state_machine.transition(
                report.tool_states[tool_id],
                "generated",
            )
        if generated.issues:
            report.status = "passed_with_warnings"

        tests = self.artifact_generator.generate_tool_tests(package_path, primitives)
        report.artifact_paths.extend(tests.artifact_paths)

        static_report = self.verification_runner.static_check_tool_scripts(package_path)
        if not static_report.ok:
            report.status = "failed"
            report.issues.extend(issue.message for issue in static_report.issues)
            for tool_id in report.tool_states:
                report.tool_states[tool_id] = self.state_machine.transition(
                    report.tool_states[tool_id],
                    "failed",
                )
            return report
        for tool_id in report.tool_states:
            report.tool_states[tool_id] = self.state_machine.transition(
                report.tool_states[tool_id],
                "static_checked",
            )

        test_report = self.verification_runner.run_generated_tool_tests(package_path)
        while not test_report.ok and report.repair_attempts < report.max_repair_attempts:
            report.repair_attempts += 1
            repair = self.artifact_generator.repair_generated_tool_tests(
                package_path,
                primitives,
                failed_report=test_report,
            )
            report.artifact_paths.extend(repair.artifact_paths)
            report.issues.extend(repair.issues)
            test_report = self.verification_runner.run_generated_tool_tests(package_path)
        if not test_report.ok:
            report.status = "failed"
            report.issues.extend(issue.message for issue in test_report.issues)
        else:
            report.status = "passed" if not report.issues else "passed_with_warnings"
        for tool_id in report.tool_states:
            target: ToolBuildStatus = "tested" if report.ok else "failed"
            report.tool_states[tool_id] = self.state_machine.transition(
                report.tool_states[tool_id],
                target,
            )
            if report.tool_states[tool_id] == "tested" and test_report.ok:
                report.tool_states[tool_id] = self.state_machine.transition(
                    report.tool_states[tool_id],
                    "available",
                )
        return report
