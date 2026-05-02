from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

from agent_factory.model.config import ModelConfig
from agent_factory.model.provider import ProviderAdapter
from agent_factory.model.router import ModelRouter
from agent_factory.model.types import (
    LLMRequest,
    LLMResponse,
    LLMStreamEvent,
    ModelError,
    StructuredOutputResult,
)


class ModelService:
    """Business-facing entrypoint for all model interactions."""

    def __init__(self, router: ModelRouter):
        self.router = router

    @classmethod
    def from_env(
        cls,
        env_file: str | Path = ".env",
        environ: Mapping[str, str] | None = None,
        *,
        validate_required: bool = True,
    ) -> "ModelService":
        config = ModelConfig.from_env(
            env_file=env_file,
            environ=environ,
            validate_required=validate_required,
        )
        return cls(ModelRouter(config))

    @classmethod
    def with_adapter(cls, config: ModelConfig, adapter: ProviderAdapter) -> "ModelService":
        router = ModelRouter(config, adapters={adapter.provider: adapter})
        return cls(router)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        adapter = self.router.adapter_for()
        return await adapter.generate(request)

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        adapter = self.router.adapter_for()
        async for event in adapter.stream(request):
            yield event

    async def generate_structured(self, request: LLMRequest) -> StructuredOutputResult:
        structured_request = request.model_copy(update={"response_format": "json_object"})
        response = await self.generate(structured_request)
        if response.error:
            return StructuredOutputResult(response=response, error=response.error)

        try:
            parsed = json.loads(response.content)
        except json.JSONDecodeError:
            error = ModelError(
                type="structured_output_parse_error",
                message="Model response was not valid JSON.",
            )
            return StructuredOutputResult(response=response, error=error)

        if not isinstance(parsed, (dict, list)):
            error = ModelError(
                type="structured_output_type_error",
                message="Model structured output must be a JSON object or array.",
            )
            return StructuredOutputResult(response=response, error=error)

        return StructuredOutputResult(data=parsed, response=response)

