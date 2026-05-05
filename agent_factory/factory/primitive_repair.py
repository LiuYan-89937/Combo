from __future__ import annotations

from typing import Callable

from agent_factory.factory_context import FactoryContextEnvelope, apply_context_envelope
from agent_factory.factory_runtime import FactoryPromptBuilder, FactoryRunContext
from agent_factory.model import LLMStreamEvent, ModelService
from agent_factory.model.types import StructuredOutputResult
from agent_factory.specs import AgentPackagePrimitives


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
        context_envelope: FactoryContextEnvelope | None = None,
        on_stream_event: Callable[[LLMStreamEvent], None] | None = None,
    ) -> StructuredOutputResult:
        request = apply_context_envelope(
            self.prompt_builder.build_repair_request(
                context,
                requirement=requirement,
                raw_model_data=raw_model_data,
                validation_errors=validation_errors,
            ),
            context_envelope,
        )
        method = self.model_service.stream_structured if on_stream_event else self.model_service.generate_structured
        return await method(
            request,
            schema=AgentPackagePrimitives.model_json_schema(by_alias=True),
            schema_name="AgentPackagePrimitivesRepair",
            strict=True,
            **({"on_event": on_stream_event} if on_stream_event else {}),
        )
