from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from combo.models.adapters import adapter_for_profile
from combo.models.capabilities import (
    ProviderProfile,
    list_provider_profiles,
    provider_profile_payload,
)
from combo.models.protocol import ModelReasoningSettings, StructuredOutputMethod

@dataclass(frozen=True, slots=True)
class ChatModelSettings:
    role: str
    provider: str
    profile: ProviderProfile
    model: str | None
    api_key: str | None
    base_url: str | None
    profile_id: str | None = None
    source: str = "model_pool"
    temperature: float | None = None
    timeout_seconds: float | None = None
    max_output_tokens: int | None = None
    max_input_tokens: int | None = None
    compression_trigger_tokens: int | None = None
    multimodal: bool = False
    reasoning: ModelReasoningSettings = field(default_factory=ModelReasoningSettings)
    structured_output_method: StructuredOutputMethod | None = None

    @property
    def available(self) -> bool:
        return bool(self.model and self.api_key and self.base_url)

    def metadata(self) -> dict[str, Any]:
        capabilities = self.profile.capabilities
        return {
            "model_role": self.role,
            "model": self.model or "",
            "model_profile_id": self.profile_id or "",
            "model_source": self.source,
            "provider": self.profile.provider_id,
            "provider_display_name": self.profile.display_name,
            "provider_adapter": self.profile.adapter_id,
            "transport": capabilities.transport,
            "max_input_tokens": self.max_input_tokens,
            "compression_trigger_tokens": self.compression_trigger_tokens,
            "max_output_tokens": self.max_output_tokens,
            "multimodal": self.multimodal,
            "structured_output_method": self.structured_output_method or "",
            "structured_output_methods": list(capabilities.structured_output_methods),
            "default_structured_output_method": capabilities.default_structured_output_method,
            "reasoning": {
                "enabled": self.reasoning.enabled,
                "effort": self.reasoning.effort,
                "summary": self.reasoning.summary,
                "budget_tokens": self.reasoning.budget_tokens,
                "send_history": self.reasoning.send_history,
                "supported": capabilities.reasoning,
            },
            "capabilities": provider_profile_payload(self.profile),
        }


def get_main_model() -> BaseChatModel | None:
    return _available_model("main")


def get_task_model() -> BaseChatModel | None:
    return _available_model("task")


def get_compression_model() -> BaseChatModel | None:
    return _available_model("compression")


def create_chat_model_from_settings(settings: ChatModelSettings) -> BaseChatModel | None:
    return _create_model(settings)


def list_supported_chat_model_profiles() -> list[dict[str, object]]:
    return [provider_profile_payload(profile) for profile in list_provider_profiles()]


def _create_model(settings: ChatModelSettings) -> BaseChatModel | None:
    if not settings.available:
        return None
    return adapter_for_profile(settings.profile).create_chat_model(settings)


def _available_model(role: str) -> BaseChatModel | None:
    from combo.model_pool.resolver import resolve_available_chat_model

    resolved = resolve_available_chat_model(role)
    return resolved.model if resolved is not None else None
