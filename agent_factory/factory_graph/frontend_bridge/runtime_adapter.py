from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_factory.env import load_agentfactory_dotenv
from agent_factory.factory_graph.frontend_bridge.agent_package_runtime import AgentPackageRuntimeManager
from agent_factory.create_agent.runtime import CreateAgentRuntime
from agent_factory.evolution import AgentEvolutionRuntime
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendCommand, FactoryMode, event
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_agent_packages import RuntimeAgentPackageCommandMixin
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_resources import RuntimeResourceCommandMixin
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_scheduler import RuntimeSchedulerCommandMixin
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_sessions import RuntimeSessionCommandMixin
from agent_factory.factory_graph.frontend_bridge.runtime_adapter_types import (
    Emit,
    FactoryBridgeOptions,
    PendingAgentPackageRun,
    PendingCreateAgentRun,
    PendingEvolutionRun,
)
from agent_factory.factory_graph.session import FactorySessionManager
from agent_factory.memory_system.factory import shutdown_factory_memory_worker
from agent_factory.runtime_kernel.background_workers import RuntimeBackgroundWorkerManager
from agent_factory.scheduler_system import SchedulerRuntime, scheduler_enabled_from_env


@dataclass(slots=True)
class FactoryRuntimeAdapter(
    RuntimeSessionCommandMixin,
    RuntimeAgentPackageCommandMixin,
    RuntimeResourceCommandMixin,
    RuntimeSchedulerCommandMixin,
):
    emit: Emit
    session_manager: FactorySessionManager | None = None
    checkpointer: Any = None
    checkpointer_handle: Any = None
    options: FactoryBridgeOptions = field(default_factory=FactoryBridgeOptions)
    session_record: Any | None = None
    mode: FactoryMode | None = None
    pending_agent_package_run: PendingAgentPackageRun | None = None
    pending_create_agent_run: PendingCreateAgentRun | None = None
    pending_evolution_run: PendingEvolutionRun | None = None
    agent_package_runtime: AgentPackageRuntimeManager | None = None
    create_agent_runtime: CreateAgentRuntime | None = None
    evolution_runtime: AgentEvolutionRuntime | None = None
    evolution_package_id: str | None = None
    scheduler_runtime: SchedulerRuntime | None = None
    background_workers: RuntimeBackgroundWorkerManager | None = None

    def __post_init__(self) -> None:
        load_agentfactory_dotenv()
        if self.session_manager is None:
            self.session_manager = FactorySessionManager.from_env()
        if self.agent_package_runtime is None:
            self.agent_package_runtime = AgentPackageRuntimeManager()
        if self.create_agent_runtime is None:
            self.create_agent_runtime = CreateAgentRuntime()
        if self.evolution_runtime is None:
            self.evolution_runtime = AgentEvolutionRuntime()
        self.agent_package_runtime.set_emit(self.emit)
        if scheduler_enabled_from_env():
            self._start_factory_scheduler()

    def handle(self, command: FactoryFrontendCommand) -> bool:
        try:
            if command.type == "shutdown":
                if self.agent_package_runtime is not None:
                    self.agent_package_runtime.close_all()
                self._shutdown_background_workers()
                shutdown_factory_memory_worker()
                return False
            handler = _COMMAND_HANDLERS.get(command.type)
            if handler is None:
                self._emit_error(command, f"unsupported command: {command.type}")
                return True
            getattr(self, handler)(command)
        except Exception as exc:
            self.emit(
                event(
                    "error",
                    request_id=command.request_id,
                    session_id=self._session_id(),
                    mode=self.mode,
                    message=f"{type(exc).__name__}: {exc}",
                )
            )
        return True


_COMMAND_HANDLERS: dict[str, str] = {
    "start_session": "start_session",
    "list_sessions": "list_sessions",
    "switch_session": "switch_session",
    "new_session": "new_session",
    "set_mode": "set_mode",
    "set_options": "set_options",
    "send_message": "send_message",
    "workspace_manage": "workspace_manage",
    "knowledge_manage": "knowledge_manage",
    "extensions_manage": "extensions_manage",
    "scheduler_manage": "scheduler_manage",
    "list_agent_packages": "list_agent_packages",
    "select_agent_package": "select_agent_package",
    "delete_agent_package": "delete_agent_package",
    "list_agent_package_sessions": "list_agent_package_sessions",
    "load_agent_package_session": "load_agent_package_session",
    "run_agent_package": "run_agent_package",
    "run_agent_evolution": "run_agent_evolution",
    "resume_interrupt": "resume_interrupt",
    "cancel_runtime_request": "cancel_runtime_request",
}
