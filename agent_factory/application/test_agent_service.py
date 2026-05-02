from __future__ import annotations

from pathlib import Path
from pydantic import ConfigDict, Field

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory.package_verification import FactoryVerificationReport, VerificationIssue
from agent_factory.harness import AgentHarnessRunner, HarnessLoadError, HarnessRunResult
from agent_factory.package import PackageValidator
from agent_factory.specs import ValidationReport


class TestAgentRequest(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    path: Path
    scenario: str | None = None


class HarnessScenarioSummary(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str | None = None
    status: str
    assertion_count: int = 0
    failed_assertions: int = 0


class TestAgentResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    package_path: Path
    status: str
    validation_report: ValidationReport
    verification_report: FactoryVerificationReport | None = None
    harness_path: Path | None = None
    harness_run: HarnessRunResult | None = None
    scenario_count: int = 0
    scenarios: list[HarnessScenarioSummary] = Field(default_factory=list)
    selected_scenario: str | None = None
    issues: list[VerificationIssue] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "passed"


class TestAgentService:
    """Read generated reports and harness.yaml as the first AgentHarness entrypoint."""

    def __init__(
        self,
        validator: PackageValidator | None = None,
        runner: AgentHarnessRunner | None = None,
    ) -> None:
        self.validator = validator or PackageValidator()
        self.runner = runner or AgentHarnessRunner()

    def test_agent(self, request: TestAgentRequest) -> TestAgentResult:
        package_path = request.path
        validation_report = self.validator.validate_primitives(package_path)
        issues: list[VerificationIssue] = []
        harness_path = package_path / "harness.yaml"
        scenarios: list[HarnessScenarioSummary] = []
        harness_run: HarnessRunResult | None = None

        verification_report = self._load_factory_verification_report(package_path, issues)
        if not harness_path.exists():
            issues.append(
                VerificationIssue(
                    code="harness_yaml_missing",
                    message="harness.yaml is required before test-agent can run.",
                    path="harness.yaml",
                )
            )
        elif verification_report is None or not verification_report.ok:
            # Keep test-agent side-effect free when the Factory verification gate has not passed.
            pass
        else:
            try:
                harness_run = self.runner.run(package_path, scenario_id=request.scenario)
                if request.scenario and not harness_run.scenario_results:
                    issues.append(
                        VerificationIssue(
                            code="harness_scenario_not_found",
                            message=f"Scenario not found: {request.scenario}",
                            path="harness.yaml:scenarios",
                        )
                    )
                scenarios = [
                    HarnessScenarioSummary(
                        id=result.scenario_id,
                        name=result.name,
                        status=result.status,
                        assertion_count=len(result.assertion_results),
                        failed_assertions=result.failed_assertion_count,
                    )
                    for result in harness_run.scenario_results
                ]
            except HarnessLoadError as error:
                issues.extend(error.issues)
            except Exception as error:
                issues.append(
                    VerificationIssue(
                        code="harness_run_error",
                        message=str(error),
                        path="harness.yaml",
                    )
                )

        status = self._status(validation_report, verification_report, harness_run, issues)
        return TestAgentResult(
            package_path=package_path,
            status=status,
            validation_report=validation_report,
            verification_report=verification_report,
            harness_path=harness_path if harness_path.exists() else None,
            harness_run=harness_run,
            scenario_count=len(scenarios),
            scenarios=scenarios,
            selected_scenario=request.scenario,
            issues=issues,
            next_steps=self._next_steps(status, package_path, issues),
        )

    def _load_factory_verification_report(
        self,
        package_path: Path,
        issues: list[VerificationIssue],
    ) -> FactoryVerificationReport | None:
        report_path = package_path / "generated" / "reports" / "factory_verification.json"
        if not report_path.exists():
            issues.append(
                VerificationIssue(
                    code="factory_verification_report_missing",
                    message="generated/reports/factory_verification.json is required.",
                    path=str(report_path.relative_to(package_path)),
                )
            )
            return None
        try:
            return FactoryVerificationReport.model_validate_json(
                report_path.read_text(encoding="utf-8")
            )
        except Exception as error:
            issues.append(
                VerificationIssue(
                    code="factory_verification_report_invalid",
                    message=str(error),
                    path=str(report_path.relative_to(package_path)),
                )
            )
            return None

    @staticmethod
    def _status(
        validation_report: ValidationReport,
        verification_report: FactoryVerificationReport | None,
        harness_run: HarnessRunResult | None,
        issues: list[VerificationIssue],
    ) -> str:
        if not validation_report.ok:
            return "failed"
        if issues:
            return "failed"
        if verification_report is None or not verification_report.ok:
            return "failed"
        if harness_run is None or not harness_run.ok:
            return "failed"
        return "passed"

    @staticmethod
    def _next_steps(status: str, package_path: Path, issues: list[VerificationIssue]) -> list[str]:
        if status == "passed":
            return [
                "AgentHarness scenarios passed.",
                f"/run {package_path}",
            ]
        if any(issue.code == "factory_verification_report_missing" for issue in issues):
            return [
                "Run create-agent again so Factory can generate local verification reports.",
            ]
        return [
            f"/validate {package_path}",
            "Fix the reported harness or verification issue, then run /test again.",
        ]
