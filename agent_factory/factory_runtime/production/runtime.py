from __future__ import annotations

from collections.abc import Iterator

from agent_factory.core import FactoryEvent
from agent_factory.factory_runtime import FactoryRunContext
from agent_factory.factory_runtime.production.graph import build_factory_production_graph
from agent_factory.factory_runtime.production.nodes import FactoryProductionNodes
from agent_factory.factory_runtime.production.state import FactoryProductionState


class FactoryProductionRuntime:
    def run(
        self,
        *,
        requirement: str,
        context: FactoryRunContext,
        stop_after_stage: str | None = None,
    ) -> FactoryProductionState:
        graph = self._compile(context)
        initial = FactoryProductionState(
            run_id=context.run_id,
            requirement=requirement,
            stop_after_stage=stop_after_stage,
        )
        final_state = graph.invoke(initial.as_graph_state(), config={"recursion_limit": 80})
        return FactoryProductionState.from_graph_state(final_state)

    def stream(
        self,
        *,
        requirement: str,
        context: FactoryRunContext,
        stop_after_stage: str | None = None,
    ) -> Iterator[FactoryEvent]:
        graph = self._compile(context)
        initial = FactoryProductionState(
            run_id=context.run_id,
            requirement=requirement,
            stop_after_stage=stop_after_stage,
        )
        seen_event_ids: set[str] = set()
        for update in graph.stream(initial.as_graph_state(), stream_mode="updates", config={"recursion_limit": 80}):
            for node_update in update.values():
                state = FactoryProductionState.from_graph_state(node_update)
                for event in state.events:
                    if event.event_id in seen_event_ids:
                        continue
                    seen_event_ids.add(event.event_id)
                    yield event

    def _compile(self, context: FactoryRunContext):
        nodes = FactoryProductionNodes(context)
        return build_factory_production_graph(nodes)
