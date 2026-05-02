from __future__ import annotations

from agent_factory.factory_runtime import FactoryPromptBuilder, FactoryRunContext
from agent_factory.model import ModelService
from agent_factory.model.types import StructuredOutputResult


class PrimitiveRepair:
    def __init__(
        self,
        model_service: ModelService,
        prompt_builder: FactoryPromptBuilder | None = None,
    ) -> None:
        self.model_service = model_service
        self.prompt_builder = prompt_builder or FactoryPromptBuilder()

    async def repair(
        self,
        context: FactoryRunContext,
        *,
        requirement: str,
        raw_model_data: object,
        validation_errors: str,
    ) -> StructuredOutputResult:
        request = self.prompt_builder.build_repair_request(
            context,
            requirement=requirement,
            raw_model_data=raw_model_data,
            validation_errors=validation_errors,
        )
        return await self.model_service.generate_structured(request)
