from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from agent_factory.context_system.token_counter import context_window_tokens_from_env
from agent_factory.factory_graph.frontend_bridge.event_normalizer import RuntimeEventNormalizer
from agent_factory.factory_graph.frontend_bridge.protocol import FactoryFrontendEvent


Emit = Callable[[FactoryFrontendEvent], None]
SYSTEM_CHAT_PACKAGE_ID = "factory_chat"
CONTEXT_WINDOW_TOKENS_ENV = "AGENTFACTORY_CONTEXT_WINDOW_TOKENS"


@dataclass(slots=True)
class FactoryBridgeOptions:
    show_state: bool = False
    show_messages: bool = True
    context_window_tokens: int | None = None
    context_window_tokens_source: str = "unset"
    env_overrides: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "FactoryBridgeOptions":
        value = context_window_tokens_from_env()
        return cls(
            context_window_tokens=value,
            context_window_tokens_source="env" if value is not None else "unset",
        )

    def effective_env_overrides(self) -> dict[str, str]:
        result = dict(self.env_overrides)
        if self.context_window_tokens is not None:
            result[CONTEXT_WINDOW_TOKENS_ENV] = str(self.context_window_tokens)
        return result


@dataclass(slots=True)
class PendingAgentPackageRun:
    package_id: str
    session_id: str
    normalizer: RuntimeEventNormalizer
    interrupt_id: str | None = None
    interrupt_event_id: str | None = None


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
