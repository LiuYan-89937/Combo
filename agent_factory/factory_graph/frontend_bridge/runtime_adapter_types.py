from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agent_factory.factory_package.constants import DEFAULT_CREATE_AGENT_BREAKPOINT_STAGE
from agent_factory.factory_graph.frontend_bridge.event_normalizer import RuntimeEventNormalizer
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent


Emit = Callable[[FactoryFrontendEvent], None]
SYSTEM_CHAT_PACKAGE_ID = "factory_chat"
SYSTEM_CREATE_AGENT_PACKAGE_ID = "factory_create_agent"


@dataclass(slots=True)
class FactoryBridgeOptions:
    stop_after_stage: str | None = DEFAULT_CREATE_AGENT_BREAKPOINT_STAGE
    show_state: bool = False
    show_messages: bool = True


@dataclass(slots=True)
class PendingAgentPackageRun:
    package_id: str
    session_id: str
    normalizer: RuntimeEventNormalizer
