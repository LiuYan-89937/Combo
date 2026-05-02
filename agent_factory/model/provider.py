from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol

from agent_factory.model.types import LLMRequest, LLMResponse, LLMStreamEvent


class ProviderAdapter(Protocol):
    """Provider boundary for model calls."""

    provider: str

    async def generate(self, request: LLMRequest) -> LLMResponse:
        ...

    async def stream(self, request: LLMRequest) -> AsyncIterator[LLMStreamEvent]:
        ...

