from __future__ import annotations

from pathlib import Path
from typing import Any

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
    auto_repair: bool = False
    approved_tool_call_id: str | None = None


class RunAgentServiceResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    target: str
    package_path: Path | None = None
    result: AgentRunResult | None = None
    error: str | None = None
    repair_result: dict[str, Any] | None = None

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
            if request.approved_tool_call_id:
                return RunAgentServiceResult(
                    target=request.target,
                    package_path=package_path,
                    error="Tool approval rerun is not supported in process mode yet.",
                )
            ipc = AgentProcessManager().run(
                AgentIPCRequest(
                    package_path=package_path,
                    user_input=request.user_input,
                    session_id=request.session_id,
                )
            )
            if not ipc.ok:
                service_result = RunAgentServiceResult(
                    target=request.target,
                    package_path=package_path,
                    error=ipc.error or "Agent process failed.",
                )
                return self._maybe_repair(request, service_result)
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
                approved_tool_call_id=request.approved_tool_call_id,
            )
        )
        service_result = RunAgentServiceResult(target=request.target, package_path=package_path, result=result)
        return self._maybe_repair(request, service_result)

    def _maybe_repair(
        self,
        request: RunAgentServiceRequest,
        result: RunAgentServiceResult,
    ) -> RunAgentServiceResult:
        if not request.auto_repair or result.ok or result.package_path is None:
            return result
        original_error = result.error
        if result.result and result.result.error:
            original_error = result.result.error.message
        if not original_error:
            original_error = "Agent run failed."
        from agent_factory.application.repair_agent_service import (
            RepairAgentRequest,
            RepairAgentService,
        )

        repair = RepairAgentService(model_service=self.model_service).repair_agent(
            RepairAgentRequest(
                target=str(result.package_path),
                user_input=request.user_input,
                session_id=request.session_id,
                original_error=original_error,
                rerun_after_repair=True,
            )
        )
        return result.model_copy(update={"repair_result": repair.model_dump(mode="json")})

    def _resolve_package(self, target: str, version: str | None) -> Path | None:
        path = Path(target)
        if path.exists():
            return path
        record = (self.registry or FilesystemRegistry()).get(target, version)
        return record.package_path if record else None


def _factory_env_file(package_path: Path) -> Path:
    workspace = FactoryWorkspace.discover(package_path)
    return workspace.project_root / ".env"
