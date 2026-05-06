from __future__ import annotations

from collections.abc import Callable

from agent_factory.factory_runtime.production.state import FactoryProductionStateDict


class FactoryNodeAccessPolicy:
    """Temporary no-op policy during the 14-stage shell cleanup."""

    def wrap(
        self,
        node_name: str,
        handler: Callable[[FactoryProductionStateDict], FactoryProductionStateDict],
    ) -> Callable[[FactoryProductionStateDict], FactoryProductionStateDict]:
        return handler
