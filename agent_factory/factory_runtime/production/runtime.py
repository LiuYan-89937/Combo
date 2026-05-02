from __future__ import annotations

from collections.abc import Iterator

from agent_factory.core import FactoryEvent
from agent_factory.factory.package_artifacts import PackageArtifactGenerator
from agent_factory.factory.package_verification import PackageVerificationRunner
from agent_factory.factory.package_writer import PackageWriter
from agent_factory.factory_runtime import FactoryRunContext
from agent_factory.factory_runtime.production.graph import build_factory_production_graph
from agent_factory.factory_runtime.production.nodes import FactoryProductionNodes
from agent_factory.factory_runtime.production.state import FactoryProductionState
from agent_factory.model import ModelService


class FactoryProductionRuntime:
    def __init__(
        self,
        *,
        model_service: ModelService | None = None,
        package_writer: PackageWriter | None = None,
        artifact_generator: PackageArtifactGenerator | None = None,
        verification_runner: PackageVerificationRunner | None = None,
    ) -> None:
        self.model_service = model_service
        self.package_writer = package_writer
        self.artifact_generator = artifact_generator
        self.verification_runner = verification_runner

    def run(
        self,
        *,
        requirement: str,
        context: FactoryRunContext,
        draft: bool = True,
    ) -> FactoryProductionState:
        graph = self._compile(context)
        initial = FactoryProductionState(
            run_id=context.run_id,
            requirement=requirement,
            draft=draft,
        )
        final_state = graph.invoke(initial.as_graph_state())
        return FactoryProductionState.from_graph_state(final_state)

    def stream(
        self,
        *,
        requirement: str,
        context: FactoryRunContext,
        draft: bool = True,
    ) -> Iterator[FactoryEvent]:
        graph = self._compile(context)
        initial = FactoryProductionState(
            run_id=context.run_id,
            requirement=requirement,
            draft=draft,
        )
        seen_event_ids: set[str] = set()
        for update in graph.stream(initial.as_graph_state(), stream_mode=["custom", "updates"]):
            if isinstance(update, tuple):
                mode, payload = update
            else:
                mode, payload = "updates", update
            if mode == "custom":
                try:
                    yield FactoryEvent.model_validate(payload)
                except Exception:
                    continue
                continue
            for node_update in payload.values():
                state = FactoryProductionState.from_graph_state(node_update)
                for event in state.events:
                    if event.event_id in seen_event_ids:
                        continue
                    seen_event_ids.add(event.event_id)
                    yield event

    def _compile(self, context: FactoryRunContext):
        nodes = FactoryProductionNodes(
            context,
            model_service=self.model_service,
            package_writer=self.package_writer,
            artifact_generator=self.artifact_generator,
            verification_runner=self.verification_runner,
        )
        return build_factory_production_graph(nodes)
