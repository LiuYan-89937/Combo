from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agent_factory.factory_graph.frontend_bridge.event_normalizer import RuntimeEventNormalizer
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent


Emit = Callable[[FactoryFrontendEvent], None]
SYSTEM_CHAT_PACKAGE_ID = "factory_chat"


@dataclass(slots=True)
class FactoryBridgeOptions:
    show_state: bool = False
    show_messages: bool = True
    context_window_tokens: int | None = None
    context_window_tokens_source: str = "unset"

    @classmethod
    def defaults(cls) -> "FactoryBridgeOptions":
        return cls()


@dataclass(slots=True)
class PendingAgentPackageRun:
    package_id: str
    session_id: str
    normalizer: RuntimeEventNormalizer
    interrupt_id: str | None = None
    interrupt_event_id: str | None = None
    group_id: str | None = None
    group_run_id: str | None = None
    workdir_root: Any | None = None


@dataclass(slots=True)
class PendingCreateAgentRun:
    session_id: str
    request_id: str | None = None
    interrupt_id: str | None = None
    interrupt_event_id: str | None = None


@dataclass(slots=True)
class PendingEvolutionRun:
    package_id: str
    session_id: str
    request_id: str | None = None
    trace_id: str | None = None
    interrupt_id: str | None = None
    interrupt_event_id: str | None = None
