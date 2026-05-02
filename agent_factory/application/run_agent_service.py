from __future__ import annotations

from pathlib import Path

from pydantic import ConfigDict

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory_runtime import FactoryWorkspace
from agent_factory.isolation import AgentIPCRequest, AgentProcessManager
from agent_factory.model import ModelService
from agent_factory.registry import FilesystemRegistry
from agent_factory.runtime import AgentRunRequest, AgentRunResult, WorkflowRuntime


class RunAgentServiceRequest(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    target: str
    user_input: str
    version: str | None = None
    session_id: str = "default"
    process: bool = False


class RunAgentServiceResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    target: str
    package_path: Path | None = None
    result: AgentRunResult | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.result is not None and self.result.ok


class RunAgentService:
    def __init__(
        self,
        *,
        model_service: ModelService | None = None,
        runtime: WorkflowRuntime | None = None,
        registry: FilesystemRegistry | None = None,
    ) -> None:
        self.model_service = model_service
        self.runtime = runtime
        self.registry = registry

    def run_agent(self, request: RunAgentServiceRequest) -> RunAgentServiceResult:
        package_path = self._resolve_package(request.target, request.version)
        if package_path is None:
            return RunAgentServiceResult(
                target=request.target,
                error=f"AgentPackage or registry record not found: {request.target}",
            )
        if request.process:
            ipc = AgentProcessManager().run(
                AgentIPCRequest(
                    package_path=package_path,
                    user_input=request.user_input,
                    session_id=request.session_id,
                )
            )
            if not ipc.ok:
                return RunAgentServiceResult(
                    target=request.target,
                    package_path=package_path,
                    error=ipc.error or "Agent process failed.",
                )
            return RunAgentServiceResult(
                target=request.target,
                package_path=package_path,
                result=AgentRunResult.model_validate(ipc.payload),
            )

        runtime = self.runtime or WorkflowRuntime(
            model_service=self.model_service,
            env_file=_factory_env_file(package_path),
        )
        result = runtime.run(
            AgentRunRequest(
                package_path=package_path,
                user_input=request.user_input,
                session_id=request.session_id,
                process_isolated=request.process,
            )
        )
        return RunAgentServiceResult(target=request.target, package_path=package_path, result=result)

    def _resolve_package(self, target: str, version: str | None) -> Path | None:
        path = Path(target)
        if path.exists():
            return path
        record = (self.registry or FilesystemRegistry()).get(target, version)
        return record.package_path if record else None


def _factory_env_file(package_path: Path) -> Path:
    workspace = FactoryWorkspace.discover(package_path)
    return workspace.project_root / ".env"
