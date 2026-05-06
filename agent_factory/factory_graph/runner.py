from __future__ import annotations

from agent_factory.factory_graph.graph import build_factory_graph
from agent_factory.factory_graph.state import FactoryGraphState


class FactoryGraphRunner:
    def run(
        self,
        *,
        requirement: str,
        stop_after_stage: str | None = None,
    ) -> FactoryGraphState:
        app = build_factory_graph(stop_after_stage=stop_after_stage)
        return app.invoke(
            {
                "requirement": requirement,
                "status": "running",
                "stage_log": [],
                "errors": [],
            }
        )
