from __future__ import annotations

from agent_factory.factory_runtime import FactoryPromptBuilder, FactoryRunContext
from agent_factory.model import ModelService
from agent_factory.model.types import StructuredOutputResult


class PrimitivePlanner:
    def __init__(
        self,
        model_service: ModelService,
        prompt_builder: FactoryPromptBuilder | None = None,
    ) -> None:
        self.model_service = model_service
        self.prompt_builder = prompt_builder or FactoryPromptBuilder()

    async def plan(
        self,
        context: FactoryRunContext,
        *,
        requirement: str,
    ) -> StructuredOutputResult:
        request = self.prompt_builder.build_primitives_request(context, requirement=requirement)
        return await self.model_service.generate_structured(request)
