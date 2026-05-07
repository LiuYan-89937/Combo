from __future__ import annotations

from langchain_core.messages import HumanMessage
from langchain_core.tools import BaseTool

from agent_factory.factory_graph.graph import build_factory_graph
from agent_factory.factory_graph.state import FactoryGraphState


class FactoryGraphRunner:
    def __init__(self, *, tools: list[BaseTool] | None = None) -> None:
        self.tools = tools

    def run(
        self,
        *,
        requirement: str,
        stop_after_stage: str | None = None,
    ) -> FactoryGraphState:
        app = build_factory_graph(stop_after_stage=stop_after_stage, tools=self.tools)
        return app.invoke(
            {
                "requirement": requirement,
                "messages": [HumanMessage(content=requirement)],
                "status": "running",
                "stage_log": [],
                "errors": [],
            }
        )
