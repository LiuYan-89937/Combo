from __future__ import annotations

from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from agent_factory.collaboration_system.orchestrator import CollaborationOrchestrator
    from agent_factory.collaboration_system.service import CollaborationService
    from agent_factory.collaboration_system.store import CollaborationStore

__all__ = ["CollaborationOrchestrator", "CollaborationService", "CollaborationStore"]


def __getattr__(name: str) -> Any:
    if name == "CollaborationOrchestrator":
        from agent_factory.collaboration_system.orchestrator import CollaborationOrchestrator

        return CollaborationOrchestrator
    if name == "CollaborationService":
        from agent_factory.collaboration_system.service import CollaborationService

        return CollaborationService
    if name == "CollaborationStore":
        from agent_factory.collaboration_system.store import CollaborationStore

        return CollaborationStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
