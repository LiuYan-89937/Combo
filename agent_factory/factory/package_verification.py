from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field
from ruamel.yaml import YAML

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory.tool_test_sandbox import SandboxResourceResolver

VerificationStatus = Literal["passed", "failed", "skipped"]


class VerificationIssue(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    path: str | None = None


class ToolStaticCheckReport(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    status: VerificationStatus
    checked_files: list[Path] = Field(default_factory=list)
    issues: list[VerificationIssue] = Field(default_factory=list)
    report_path: Path | None = None

    @property
    def ok(self) -> bool:
        return self.status in {"passed", "skipped"}


class ToolTestRunReport(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    status: VerificationStatus
    command: list[str] = Field(default_factory=list)
    return_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    test_files: list[Path] = Field(default_factory=list)
    issues: list[VerificationIssue] = Field(default_factory=list)
    report_path: Path | None = None
    sandbox_enabled: bool = False
    sandbox_mode: str | None = None
    resource_count: int = 0
    resource_map_redacted: dict[str, Any] = Field(default_factory=dict)
    diff_summary: dict[str, Any] = Field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in {"passed", "skipped"}


class MCPBindingLocalCheckReport(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    status: VerificationStatus
    server_count: int = 0
    binding_count: int = 0
    issues: list[VerificationIssue] = Field(default_factory=list)
    report_path: Path | None = None

    @property
    def ok(self) -> bool:
        return self.status in {"passed", "skipped"}


class HarnessDryRunReport(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    status: VerificationStatus
    scenario_count: int = 0
    issues: list[VerificationIssue] = Field(default_factory=list)
    report_path: Path | None = None

    @property
    def ok(self) -> bool:
        return self.status in {"passed", "skipped"}


class FactoryVerificationReport(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    status: VerificationStatus
    package_path: Path
    tool_static_check: ToolStaticCheckReport | None = None
    tool_tests: ToolTestRunReport | None = None
    mcp_binding_check: MCPBindingLocalCheckReport | None = None
    harness_dry_run: HarnessDryRunReport | None = None
    issue_count: int = 0
    report_path: Path | None = None

    @property
    def ok(self) -> bool:
        return self.status in {"passed", "skipped"}


class PackageVerificationRunner:
    """Local checks for generated Factory package artifacts."""

    def __init__(self, *, timeout_seconds: int = 10, output_limit: int = 4000) -> None:
        self.timeout_seconds = timeout_seconds
        self.output_limit = output_limit
        self._yaml = YAML(typ="safe")

    def static_check_tool_scripts(self, package_path: Path) -> ToolStaticCheckReport:
        report_path = _reports_dir(package_path) / "tool_static_check.json"
        tool_files = sorted((package_path / "generated" / "draft_tools").glob("*.py"))
        if not tool_files:
            report = ToolStaticCheckReport(status="skipped", report_path=report_path)
            self._write_report(report_path, report)
            return report

        issues: list[VerificationIssue] = []
        for path in tool_files:
            try:
                source = path.read_text(encoding="utf-8")
                compile(source, str(path), "exec")
            except SyntaxError as error:
                issues.append(
                    VerificationIssue(
                        code="tool_syntax_error",
                        message=_clean_text(error.msg),
                        path=str(path.relative_to(package_path)),
                    )
                )
            except Exception as error:
                issues.append(
                    VerificationIssue(
                        code="tool_static_check_error",
                        message=_clean_text(str(error)),
                        path=str(path.relative_to(package_path)),
                    )
                )

        report = ToolStaticCheckReport(
            status="failed" if issues else "passed",
            checked_files=tool_files,
            issues=issues,
            report_path=report_path,
        )
        self._write_report(report_path, report)
        return report

    def run_generated_tool_tests(self, package_path: Path) -> ToolTestRunReport:
        report_path = _reports_dir(package_path) / "tool_tests.json"
        test_dir = package_path / "generated" / "tool_tests"
        test_files = sorted(test_dir.glob("test_*.py")) if test_dir.exists() else []
        if not test_files:
            report = ToolTestRunReport(status="skipped", test_files=[], report_path=report_path)
            self._write_report(report_path, report)
            return report

        report_command = [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s <fresh-sandbox>/package/generated/tool_tests",
            "-p <one generated test file at a time>",
        ]
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        issues: list[VerificationIssue] = []
        return_code = 0
        resource_count = 0
        resource_map_redacted: dict[str, Any] = {}
        diff_by_test: dict[str, Any] = {}

        for test_file in test_files:
            sandbox = None
            try:
                sandbox = SandboxResourceResolver().prepare(package_path)
                resource_count = max(resource_count, sandbox.resource_count)
                resource_map_redacted.update(sandbox.resource_map_redacted)
                unsafe_issues = [
                    VerificationIssue(**issue)
                    for issue in sandbox.unsafe_real_resource_issues()
                ]
                if unsafe_issues:
                    issues.extend(unsafe_issues)
                    return_code = 1
                    diff_by_test[test_file.name] = sandbox.diff_summary()
                    continue

                env = _subprocess_env()
                env["AGENTFACTORY_TOOL_TEST_CONTEXT_JSON"] = json.dumps(
                    sandbox.context,
                    ensure_ascii=False,
                )
                sandbox_test_dir = sandbox.package_path / "generated" / "tool_tests"
                command = [
                    sys.executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    str(sandbox_test_dir),
                    "-p",
                    test_file.name,
                ]
                completed = subprocess.run(
                    command,
                    cwd=sandbox.package_path,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    env=env,
                    check=False,
                )
                if completed.stdout:
                    stdout_parts.append(f"== {test_file.name} ==\n{completed.stdout}")
                if completed.stderr:
                    stderr_parts.append(f"== {test_file.name} ==\n{completed.stderr}")
                if completed.returncode != 0:
                    return_code = completed.returncode
                    issues.append(
                        VerificationIssue(
                            code="generated_tool_tests_failed",
                            message=f"Generated tool tests failed: {test_file.name}",
                            path=str(test_file.relative_to(package_path)),
                        )
                    )
                diff_by_test[test_file.name] = sandbox.diff_summary()
            except subprocess.TimeoutExpired as error:
                return_code = 1
                stdout_parts.append(f"== {test_file.name} ==\n{_clean_text(error.stdout or '', self.output_limit)}")
                stderr_parts.append(f"== {test_file.name} ==\n{_clean_text(error.stderr or '', self.output_limit)}")
                issues.append(
                    VerificationIssue(
                        code="generated_tool_tests_timeout",
                        message=f"Generated tool tests timed out after {self.timeout_seconds} seconds: {test_file.name}",
                        path=str(test_file.relative_to(package_path)),
                    )
                )
                if sandbox is not None:
                    diff_by_test[test_file.name] = sandbox.diff_summary()
            except Exception as error:
                return_code = 1
                issues.append(
                    VerificationIssue(
                        code="tool_test_sandbox_error",
                        message=_clean_text(str(error), self.output_limit),
                        path=str(test_file.relative_to(package_path)),
                    )
                )
                if sandbox is not None:
                    diff_by_test[test_file.name] = sandbox.diff_summary()
            finally:
                if sandbox is not None:
                    sandbox.cleanup()

        report = ToolTestRunReport(
            status="passed" if not issues else "failed",
            command=report_command,
            return_code=0 if not issues else return_code or 1,
            stdout=_clean_text("\n".join(stdout_parts), self.output_limit),
            stderr=_clean_text("\n".join(stderr_parts), self.output_limit),
            test_files=test_files,
            issues=issues,
            report_path=report_path,
            sandbox_enabled=True,
            sandbox_mode="process_directory",
            resource_count=resource_count,
            resource_map_redacted=resource_map_redacted,
            diff_summary={
                "per_test_file": diff_by_test,
                "test_file_count": len(test_files),
                "failed_test_file_count": len({issue.path for issue in issues if issue.path}),
            },
        )

        self._write_report(report_path, report)
        return report

    def validate_mcp_bindings_local(self, package_path: Path) -> MCPBindingLocalCheckReport:
        report_path = _reports_dir(package_path) / "mcp_binding_check.json"
        path = package_path / "mcp.yaml"
        if not path.exists():
            report = MCPBindingLocalCheckReport(
                status="skipped",
                issues=[
                    VerificationIssue(
                        code="mcp_yaml_missing",
                        message="mcp.yaml is not present.",
                        path="mcp.yaml",
                    )
                ],
                report_path=report_path,
            )
            self._write_report(report_path, report)
            return report

        data = self._load_yaml_mapping(path)
        issues: list[VerificationIssue] = []
        servers = data.get("servers") or []
        bindings = data.get("bindings") or []
        if not isinstance(servers, list):
            issues.append(_issue("mcp_servers_not_list", "servers must be a list.", "mcp.yaml:servers"))
            servers = []
        if not isinstance(bindings, list):
            issues.append(_issue("mcp_bindings_not_list", "bindings must be a list.", "mcp.yaml:bindings"))
            bindings = []

        if not servers and not bindings and not issues:
            report = MCPBindingLocalCheckReport(status="skipped", report_path=report_path)
            self._write_report(report_path, report)
            return report

        _validate_unique_mapping_ids(servers, "server", "mcp.yaml:servers", issues)
        _validate_unique_mapping_ids(bindings, "binding", "mcp.yaml:bindings", issues)
        server_ids = {item.get("id") for item in servers if isinstance(item, dict)}
        valid_risk = {"low", "medium", "high", "critical"}
        for index, binding in enumerate(bindings):
            location = f"mcp.yaml:bindings[{index}]"
            if not isinstance(binding, dict):
                issues.append(_issue("mcp_binding_not_mapping", "binding must be a mapping.", location))
                continue
            capability_ref = binding.get("capability_ref")
            if not isinstance(capability_ref, str) or not capability_ref.startswith("mcp.") or "@" not in capability_ref:
                issues.append(_issue("mcp_capability_ref_invalid", "capability_ref must look like mcp.<name>@<version>.", location))
            source_id = binding.get("source_id")
            if source_id and source_id not in server_ids:
                issues.append(_issue("mcp_binding_source_missing", "binding source_id must reference a server id.", location))
            risk_level = binding.get("risk_level")
            if risk_level not in valid_risk:
                issues.append(_issue("mcp_risk_level_invalid", "risk_level must be low, medium, high, or critical.", location))

        report = MCPBindingLocalCheckReport(
            status="failed" if issues else "passed",
            server_count=len(servers),
            binding_count=len(bindings),
            issues=issues,
            report_path=report_path,
        )
        self._write_report(report_path, report)
        return report

    def dry_run_harness_scenarios(self, package_path: Path) -> HarnessDryRunReport:
        report_path = _reports_dir(package_path) / "harness_dry_run.json"
        path = package_path / "harness.yaml"
        issues: list[VerificationIssue] = []
        if not path.exists():
            report = HarnessDryRunReport(
                status="failed",
                issues=[
                    VerificationIssue(
                        code="harness_yaml_missing",
                        message="harness.yaml is required for dry-run validation.",
                        path="harness.yaml",
                    )
                ],
                report_path=report_path,
            )
            self._write_report(report_path, report)
            return report

        data = self._load_yaml_mapping(path)
        scenarios = data.get("scenarios") or []
        if not isinstance(scenarios, list):
            issues.append(_issue("harness_scenarios_not_list", "scenarios must be a list.", "harness.yaml:scenarios"))
            scenarios = []
        if not scenarios:
            issues.append(_issue("harness_scenarios_required", "harness.yaml must contain at least one scenario.", "harness.yaml:scenarios"))

        tool_ids = _generated_tool_ids(package_path)
        fixtures = data.get("fixtures") if isinstance(data.get("fixtures"), dict) else {}
        scenario_ids: list[str] = []
        for index, scenario in enumerate(scenarios):
            location = f"harness.yaml:scenarios[{index}]"
            if not isinstance(scenario, dict):
                issues.append(_issue("harness_scenario_not_mapping", "scenario must be a mapping.", location))
                continue
            scenario_id = scenario.get("id")
            if not isinstance(scenario_id, str) or not scenario_id.strip():
                issues.append(_issue("harness_scenario_id_required", "scenario id is required.", location))
            else:
                scenario_ids.append(scenario_id)
            turns = scenario.get("turns")
            if not isinstance(turns, list) or not turns:
                issues.append(_issue("harness_turns_required", "scenario must contain at least one turn.", location))
            if not isinstance(scenario.get("expected"), dict):
                issues.append(_issue("harness_expected_required", "scenario expected must be a mapping.", location))
            if not isinstance(scenario.get("observe"), dict):
                issues.append(_issue("harness_observe_required", "scenario observe must be a mapping.", location))
            selected_tool = (scenario.get("expected") or {}).get("selected_tool") if isinstance(scenario.get("expected"), dict) else None
            if selected_tool and selected_tool not in tool_ids:
                issues.append(_issue("harness_selected_tool_missing", f"selected_tool {selected_tool} is not generated.", location))
            _validate_fixture_refs(scenario, fixtures, location, issues)

        duplicate_ids = _duplicates(scenario_ids)
        for scenario_id in duplicate_ids:
            issues.append(_issue("harness_scenario_id_duplicate", f"duplicate scenario id: {scenario_id}", "harness.yaml:scenarios"))

        report = HarnessDryRunReport(
            status="failed" if issues else "passed",
            scenario_count=len(scenarios),
            issues=issues,
            report_path=report_path,
        )
        self._write_report(report_path, report)
        return report

    def write_factory_report(
        self,
        package_path: Path,
        *,
        tool_static_check: ToolStaticCheckReport | None = None,
        tool_tests: ToolTestRunReport | None = None,
        mcp_binding_check: MCPBindingLocalCheckReport | None = None,
        harness_dry_run: HarnessDryRunReport | None = None,
    ) -> FactoryVerificationReport:
        report_path = _reports_dir(package_path) / "factory_verification.json"
        reports = [
            report
            for report in [
                tool_static_check,
                tool_tests,
                mcp_binding_check,
                harness_dry_run,
            ]
            if report is not None
        ]
        issue_count = sum(len(getattr(report, "issues", [])) for report in reports)
        if any(report.status == "failed" for report in reports):
            status: VerificationStatus = "failed"
        elif len(reports) == 4:
            status = "passed"
        else:
            status = "skipped"

        report = FactoryVerificationReport(
            status=status,
            package_path=package_path,
            tool_static_check=tool_static_check,
            tool_tests=tool_tests,
            mcp_binding_check=mcp_binding_check,
            harness_dry_run=harness_dry_run,
            issue_count=issue_count,
            report_path=report_path,
        )
        self._write_report(report_path, report)
        return report

    def _load_yaml_mapping(self, path: Path) -> dict[str, Any]:
        data = self._yaml.load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return data

    def _write_report(self, path: Path, report: JsonDumpMixin) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")


def _reports_dir(package_path: Path) -> Path:
    return package_path / "generated" / "reports"


def _issue(code: str, message: str, path: str | None = None) -> VerificationIssue:
    return VerificationIssue(code=code, message=message, path=path)


def _validate_unique_mapping_ids(
    items: list[object],
    label: str,
    path: str,
    issues: list[VerificationIssue],
) -> None:
    ids: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            issues.append(_issue(f"mcp_{label}_not_mapping", f"{label} must be a mapping.", f"{path}[{index}]"))
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            issues.append(_issue(f"mcp_{label}_id_required", f"{label} id is required.", f"{path}[{index}]"))
            continue
        ids.append(item_id)
    for item_id in _duplicates(ids):
        issues.append(_issue(f"mcp_{label}_id_duplicate", f"duplicate {label} id: {item_id}", path))


def _generated_tool_ids(package_path: Path) -> set[str]:
    ids: set[str] = set()
    yaml = YAML(typ="safe")
    for path in sorted((package_path / "generated" / "draft_tools").glob("*.tool.yaml")):
        data = yaml.load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("tool_id"), str):
            ids.add(data["tool_id"])
    return ids


def _validate_fixture_refs(
    scenario: dict[str, Any],
    fixtures: dict[str, Any],
    location: str,
    issues: list[VerificationIssue],
) -> None:
    refs = scenario.get("fixtures") or []
    if not refs:
        return
    if not isinstance(refs, list):
        issues.append(_issue("harness_fixture_refs_not_list", "fixtures must be a list.", location))
        return
    fixture_groups = {
        "tool": fixtures.get("tools") if isinstance(fixtures.get("tools"), dict) else {},
        "mcp": fixtures.get("mcp") if isinstance(fixtures.get("mcp"), dict) else {},
        "context": fixtures.get("context") if isinstance(fixtures.get("context"), dict) else {},
        "memory": fixtures.get("memory") if isinstance(fixtures.get("memory"), dict) else {},
    }
    for ref in refs:
        if not isinstance(ref, str):
            issues.append(_issue("harness_fixture_ref_invalid", "fixture ref must be a string.", location))
            continue
        if ":" not in ref:
            if not any(ref in group for group in fixture_groups.values()):
                issues.append(_issue("harness_fixture_ref_missing", f"fixture ref not found: {ref}", location))
            continue
        group_name, item_id = ref.split(":", 1)
        group = fixture_groups.get(group_name)
        if group is None or item_id not in group:
            issues.append(_issue("harness_fixture_ref_missing", f"fixture ref not found: {ref}", location))


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _subprocess_env() -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUTF8": "1",
    }
    if "SystemRoot" in os.environ:
        env["SystemRoot"] = os.environ["SystemRoot"]
    return env


def _clean_text(value: str | bytes, limit: int = 4000) -> str:
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = value
    redacted = re.sub(
        r"(?i)(api_key|authorization|auth_header|tool_auth_token|secret)\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        text,
    )
    if len(redacted) > limit:
        return f"{redacted[:limit]}...[truncated]"
    return redacted
