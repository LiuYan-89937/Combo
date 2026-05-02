from __future__ import annotations

from collections.abc import Mapping

from agent_factory.model.adapters import FakeModelAdapter, OpenAICompatibleChatAdapter
from agent_factory.model.config import ModelConfig
from agent_factory.model.provider import ProviderAdapter


class ModelRouter:
    """Selects provider adapters for model requests."""

    def __init__(
        self,
        config: ModelConfig,
        adapters: Mapping[str, ProviderAdapter] | None = None,
    ):
        self.config = config
        self._adapters = dict(adapters or {})

    def adapter_for(self, provider: str | None = None) -> ProviderAdapter:
        selected_provider = provider or self.config.provider
        if selected_provider in self._adapters:
            return self._adapters[selected_provider]
        if selected_provider == "fake":
            adapter = FakeModelAdapter()
        elif selected_provider == "openai_compatible_chat":
            adapter = OpenAICompatibleChatAdapter(self.config)
        else:
            raise ValueError(f"Unsupported model provider: {selected_provider}")
        self._adapters[selected_provider] = adapter
        return adapter

