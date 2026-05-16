from __future__ import annotations

from abc import ABC, abstractmethod
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.factory_graph.schemas import (
    ArtifactManifestEntry,
    HarnessExecutionPlan,
    HarnessReportError,
    HarnessValidationReport,
    HostInteractionContract,
    RuntimeEnvironmentContract,
    SandboxDependencyPlan,
)


class PreparedSandbox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_environment: RuntimeEnvironmentContract
    host_interaction: HostInteractionContract
    dependency_plan: SandboxDependencyPlan
    package_root: str
    resources_path: str
    artifacts_root: str
    workdir_host_path: str


class HarnessExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    dependency_results: list[dict[str, Any]] = Field(default_factory=list)
    scenario_results: list[dict[str, Any]] = Field(default_factory=list)
    tool_test_results: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[HarnessReportError] = Field(default_factory=list)


class SandboxRuntime(ABC):
    @abstractmethod
    def prepare(
        self,
        *,
        runtime_environment: RuntimeEnvironmentContract,
        host_interaction: HostInteractionContract,
        dependency_plan: SandboxDependencyPlan,
        package_root: Path,
        resources_path: Path,
        artifacts_root: Path,
    ) -> PreparedSandbox:
        raise NotImplementedError

    @abstractmethod
    def run(self, *, sandbox: PreparedSandbox, plan: HarnessExecutionPlan) -> HarnessExecutionResult:
        raise NotImplementedError

    @abstractmethod
    def collect_artifacts(self, *, sandbox: PreparedSandbox) -> list[ArtifactManifestEntry]:
        raise NotImplementedError

    @abstractmethod
    def cleanup(self, *, sandbox: PreparedSandbox) -> None:
        raise NotImplementedError


class DockerSandboxRuntime(SandboxRuntime):
    def prepare(
        self,
        *,
        runtime_environment: RuntimeEnvironmentContract,
        host_interaction: HostInteractionContract,
        dependency_plan: SandboxDependencyPlan,
        package_root: Path,
        resources_path: Path,
        artifacts_root: Path,
    ) -> PreparedSandbox:
        docker = shutil.which("docker")
        if docker is None:
            raise SandboxRuntimeError(
                where="docker.runtime_detection",
                why="docker_not_available",
                message="Docker executable was not found. Install Docker or choose an explicit non-docker runtime backend.",
            )
        artifacts_root.mkdir(parents=True, exist_ok=True)
        workdir = artifacts_root / "workdir"
        workdir.mkdir(parents=True, exist_ok=True)
        (artifacts_root / "harness_execution_plan.json").write_text("{}", encoding="utf-8")
        return PreparedSandbox(
            runtime_environment=runtime_environment,
            host_interaction=host_interaction,
            dependency_plan=dependency_plan,
            package_root=str(package_root),
            resources_path=str(resources_path),
            artifacts_root=str(artifacts_root),
            workdir_host_path=str(workdir),
        )

    def run(self, *, sandbox: PreparedSandbox, plan: HarnessExecutionPlan) -> HarnessExecutionResult:
        artifacts_root = Path(sandbox.artifacts_root)
        plan_path = artifacts_root / "harness_execution_plan.json"
        runner_path = artifacts_root / "sandbox_runner.py"
        result_path = artifacts_root / "sandbox_result.json"
        plan_path.write_text(json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        runner_path.write_text(_SANDBOX_RUNNER, encoding="utf-8")
        command = self._docker_command(sandbox=sandbox, runner_path=runner_path)
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=sandbox.runtime_environment.limits.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return HarnessExecutionResult(
                status="failed",
                stdout=_safe_text(exc.stdout),
                stderr=_safe_text(exc.stderr),
                errors=[
                    HarnessReportError(
                        where="sandbox.run",
                        why="timeout",
                        message="Sandbox execution timed out.",
                        evidence={"timeout_seconds": sandbox.runtime_environment.limits.timeout_seconds},
                    )
                ],
            )
        parsed = _read_runner_result(result_path)
        errors = [
            HarnessReportError.model_validate(item)
            for item in parsed.get("errors", [])
        ]
        status = "passed" if completed.returncode == 0 and not errors else "failed"
        return HarnessExecutionResult(
            status=status,
            stdout=completed.stdout,
            stderr=completed.stderr,
            exit_code=completed.returncode,
            dependency_results=parsed.get("dependency_results", []),
            scenario_results=parsed.get("scenario_results", []),
            tool_test_results=parsed.get("tool_test_results", []),
            errors=errors,
        )

    def collect_artifacts(self, *, sandbox: PreparedSandbox) -> list[ArtifactManifestEntry]:
        artifacts_root = Path(sandbox.artifacts_root)
        if not artifacts_root.exists():
            return []
        entries: list[ArtifactManifestEntry] = []
        for path in sorted(item for item in artifacts_root.rglob("*") if item.is_file()):
            entries.append(
                ArtifactManifestEntry(
                    path=str(path.relative_to(artifacts_root)),
                    bytes=path.stat().st_size,
                )
            )
        return entries

    def cleanup(self, *, sandbox: PreparedSandbox) -> None:
        return None

    def _docker_command(self, *, sandbox: PreparedSandbox, runner_path: Path) -> list[str]:
        runtime = sandbox.runtime_environment
        network = "none" if runtime.network_policy.mode == "none" else "bridge"
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            network,
            "--memory",
            f"{runtime.limits.memory_mb}m",
            "--cpus",
            str(runtime.limits.cpu),
            "-v",
            f"{Path(sandbox.package_root).resolve()}:/package:ro",
            "-v",
            f"{Path(sandbox.resources_path).resolve()}:/resources/resources.json:ro",
            "-v",
            f"{Path(sandbox.artifacts_root).resolve()}:/artifacts:rw",
            "-v",
            f"{Path(sandbox.workdir_host_path).resolve()}:/workdir:rw",
        ]
        for mount in [*sandbox.host_interaction.mounts, *sandbox.host_interaction.volumes]:
            if mount.authorization_source == "system_required":
                continue
            access = "ro" if mount.access == "read_only" else "rw"
            command.extend(["-v", f"{Path(mount.host_path).resolve()}:{mount.container_path}:{access}"])
        command.extend([runtime.image, "python", f"/artifacts/{runner_path.name}"])
        return command


class LocalTrustedRuntime(SandboxRuntime):
    def prepare(self, **kwargs: Any) -> PreparedSandbox:
        raise SandboxRuntimeError(
            where="local_trusted.prepare",
            why="runtime_not_implemented",
            message="local_trusted is an explicit backend but is not implemented yet.",
        )

    def run(self, *, sandbox: PreparedSandbox, plan: HarnessExecutionPlan) -> HarnessExecutionResult:
        raise SandboxRuntimeError(
            where="local_trusted.run",
            why="runtime_not_implemented",
            message="local_trusted is not implemented.",
        )

    def collect_artifacts(self, *, sandbox: PreparedSandbox) -> list[ArtifactManifestEntry]:
        return []

    def cleanup(self, *, sandbox: PreparedSandbox) -> None:
        return None


class SandboxRuntimeError(RuntimeError):
    def __init__(self, *, where: str, why: str, message: str, evidence: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.where = where
        self.why = why
        self.message = message
        self.evidence = evidence or {}

    def to_report_error(self) -> HarnessReportError:
        return HarnessReportError(
            where=self.where,
            why=self.why,
            message=self.message,
            evidence=self.evidence,
        )


def runtime_for_backend(backend: str) -> SandboxRuntime:
    if backend == "docker":
        return DockerSandboxRuntime()
    return LocalTrustedRuntime()


def _read_runner_result(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"errors": [{"where": "sandbox.run", "why": "missing_result", "message": "Sandbox did not produce a result file.", "evidence": {}}]}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "errors": [
                {
                    "where": "sandbox.run",
                    "why": "invalid_result",
                    "message": f"Sandbox result file is invalid: {type(exc).__name__}: {exc}",
                    "evidence": {"path": str(path)},
                }
            ]
        }


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


_SANDBOX_RUNNER = r'''
from __future__ import annotations

import importlib.util
import json
import py_compile
import subprocess
import sys
from pathlib import Path


def main() -> int:
    result = {
        "dependency_results": [],
        "scenario_results": [],
        "tool_test_results": [],
        "errors": [],
    }
    package_root = Path("/package")
    resources_path = Path("/resources/resources.json")
    plan_path = Path("/artifacts/harness_execution_plan.json")
    dependency_plan_path = Path("/artifacts/sandbox_dependency_plan.json")
    result_path = Path("/artifacts/sandbox_result.json")
    try:
        resources_payload = json.loads(resources_path.read_text(encoding="utf-8"))
        resources = resources_payload.get("resources", resources_payload)
    except Exception as exc:
        result["errors"].append({
            "where": "resources.load",
            "why": "invalid_resources",
            "message": f"Unable to load resources: {type(exc).__name__}: {exc}",
            "evidence": {"path": str(resources_path)},
        })
        resources = {}
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception as exc:
        result["errors"].append({
            "where": "harness.plan",
            "why": "invalid_plan",
            "message": f"Unable to load harness plan: {type(exc).__name__}: {exc}",
            "evidence": {"path": str(plan_path)},
        })
        plan = {}
    try:
        dependency_plan = json.loads(dependency_plan_path.read_text(encoding="utf-8"))
    except Exception:
        dependency_plan = {"python_requirements": [], "system_packages": [], "install_mode": "none"}
    _install_dependencies(dependency_plan, result)
    for tool_file in sorted(package_root.glob("tools/*/tool.py")):
        tool_id = tool_file.parent.name
        try:
            py_compile.compile(str(tool_file), doraise=True)
            result["tool_test_results"].append({"tool_id": tool_id, "check": "py_compile", "status": "passed"})
        except Exception as exc:
            result["errors"].append({
                "where": f"tool_test.{tool_id}",
                "why": "tool_compile_failed",
                "message": f"Tool code failed to compile: {type(exc).__name__}: {exc}",
                "evidence": {"path": str(tool_file)},
            })
    for item in plan.get("tool_tests", []):
        tool_id = str(item.get("tool_id") or "")
        tool_file = package_root / "tools" / tool_id / "tool.py"
        if not tool_id or not tool_file.exists():
            result["errors"].append({
                "where": f"tool_test.{tool_id or 'unknown'}",
                "why": "tool_missing",
                "message": "Tool test references a missing tool.",
                "evidence": {"tool_file": str(tool_file)},
            })
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"generated_tool_{tool_id}", tool_file)
            module = importlib.util.module_from_spec(spec)
            assert spec and spec.loader
            spec.loader.exec_module(module)
            output = module.run(dict(item.get("arguments") or {}), resources)
            result["tool_test_results"].append({"tool_id": tool_id, "check": "run", "status": "passed", "output": output})
        except ModuleNotFoundError as exc:
            result["errors"].append({
                "where": f"tool_test.{tool_id}",
                "why": "dependency_missing",
                "message": f"Tool dependency is missing: {exc}",
                "evidence": {"arguments": item.get("arguments") or {}, "missing_dependency": getattr(exc, "name", None)},
            })
        except Exception as exc:
            result["errors"].append({
                "where": f"tool_test.{tool_id}",
                "why": "tool_failed",
                "message": f"Tool execution failed: {type(exc).__name__}: {exc}",
                "evidence": {"arguments": item.get("arguments") or {}},
            })
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if result["errors"] else 0


def _install_dependencies(dependency_plan: dict, result: dict) -> None:
    install_mode = dependency_plan.get("install_mode") or "none"
    python_requirements = [str(item) for item in dependency_plan.get("python_requirements") or [] if str(item).strip()]
    system_packages = [str(item) for item in dependency_plan.get("system_packages") or [] if str(item).strip()]
    if install_mode == "none":
        if python_requirements or system_packages:
            result["errors"].append({
                "where": "dependency.install",
                "why": "dependency_failed",
                "message": "Dependency plan declares packages but install_mode is none.",
                "evidence": {"python_requirements": python_requirements, "system_packages": system_packages},
            })
        return
    if system_packages:
        command = ["apt-get", "update"]
        update = _run(command, timeout_seconds=120)
        result["dependency_results"].append({"kind": "system", "command": command, **update})
        if update["exit_code"] != 0:
            result["errors"].append({
                "where": "dependency.install.system",
                "why": "system_dependency_install_failed",
                "message": "apt-get update failed.",
                "evidence": update,
            })
            return
        command = ["apt-get", "install", "-y", *system_packages]
        install = _run(command, timeout_seconds=300)
        result["dependency_results"].append({"kind": "system", "command": command, **install})
        if install["exit_code"] != 0:
            result["errors"].append({
                "where": "dependency.install.system",
                "why": "system_dependency_install_failed",
                "message": "System dependency installation failed.",
                "evidence": install,
            })
            return
    if python_requirements:
        command = [sys.executable, "-m", "pip", "install", *python_requirements]
        install = _run(command, timeout_seconds=300)
        result["dependency_results"].append({"kind": "python", "command": command, **install})
        if install["exit_code"] != 0:
            result["errors"].append({
                "where": "dependency.install.python",
                "why": "python_dependency_install_failed",
                "message": "Python dependency installation failed.",
                "evidence": install,
            })


def _run(command: list[str], timeout_seconds: int) -> dict:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds, check=False)
        return {
            "status": "completed",
            "exit_code": completed.returncode,
            "stdout": completed.stdout[-12000:],
            "stderr": completed.stderr[-12000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "timeout",
            "exit_code": None,
            "stdout": _safe_text(exc.stdout)[-12000:],
            "stderr": _safe_text(exc.stderr)[-12000:],
        }


def _safe_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
'''
