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
    runtime_host_path: str


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
        runtime = artifacts_root / "runtime"
        workdir.mkdir(parents=True, exist_ok=True)
        runtime.mkdir(parents=True, exist_ok=True)
        (artifacts_root / "harness_execution_plan.json").write_text("{}", encoding="utf-8")
        return PreparedSandbox(
            runtime_environment=runtime_environment,
            host_interaction=host_interaction,
            dependency_plan=dependency_plan,
            package_root=str(package_root),
            resources_path=str(resources_path),
            artifacts_root=str(artifacts_root),
            workdir_host_path=str(workdir),
            runtime_host_path=str(runtime),
        )

    def run(self, *, sandbox: PreparedSandbox, plan: HarnessExecutionPlan) -> HarnessExecutionResult:
        artifacts_root = Path(sandbox.artifacts_root)
        plan_path = artifacts_root / "harness_execution_plan.json"
        result_path = artifacts_root / "sandbox_result.json"
        plan_path.write_text(json.dumps(plan.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
        command = self._docker_command(sandbox=sandbox)
        bridge_command = {
            "type": "run_harness",
            "payload": {
                "execution_plan": plan.model_dump(mode="json"),
            },
        }
        try:
            completed = subprocess.run(
                command,
                input=json.dumps(bridge_command, ensure_ascii=False) + "\n",
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

    def _docker_command(self, *, sandbox: PreparedSandbox) -> list[str]:
        runtime = sandbox.runtime_environment
        network = "none" if runtime.network_policy.mode == "none" else "bridge"
        command = [
            "docker",
            "run",
            "--rm",
            "-i",
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
            "-v",
            f"{Path(sandbox.runtime_host_path).resolve()}:/runtime:rw",
        ]
        for mount in [*sandbox.host_interaction.mounts, *sandbox.host_interaction.volumes]:
            if mount.authorization_source == "system_required":
                continue
            access = "ro" if mount.access == "read_only" else "rw"
            command.extend(["-v", f"{Path(mount.host_path).resolve()}:{mount.container_path}:{access}"])
        command.extend([runtime.image, "python", "-m", "agent_factory.agent_runtime_bridge.stdio_server"])
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
