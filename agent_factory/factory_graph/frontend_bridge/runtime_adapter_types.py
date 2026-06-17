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


@dataclass(slots=True)
class PendingAgentPackageRun:
    package_id: str
    session_id: str
    normalizer: RuntimeEventNormalizer
    interrupt_id: str | None = None


@dataclass(slots=True)
class PendingCreateAgentRun:
    session_id: str
