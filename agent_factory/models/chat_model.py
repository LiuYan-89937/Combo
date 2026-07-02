from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import os
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from agent_factory.models.adapters import adapter_for_profile
from agent_factory.models.capabilities import (
    ProviderProfile,
    list_provider_profiles,
    provider_profile_payload,
    resolve_provider_profile,
)
from agent_factory.models.protocol import ModelReasoningSettings, StructuredOutputMethod

_STRUCTURED_OUTPUT_METHODS: set[str] = {"function_calling", "json_mode", "json_schema"}
_REASONING_MODE_VALUES = {"enabled", "disabled"}
_DEFAULT_PROVIDER = "openai_compatible_chat"
_DEFAULT_MAIN_TEMPERATURE = 0.2
_DEFAULT_TASK_TEMPERATURE = 0.1
_DEFAULT_COMPRESSION_TEMPERATURE = 0.1
_DEFAULT_MODEL_TIMEOUT_SECONDS = 600.0
_DEFAULT_MAIN_MAX_OUTPUT_TOKENS = 8192
_DEFAULT_TASK_MAX_OUTPUT_TOKENS = 2048
_DEFAULT_COMPRESSION_MAX_OUTPUT_TOKENS = 2048
_MODEL_BASE_URL_ENV = "AGENTFACTORY_MODEL_BASE_URL"
_MODEL_API_KEY_ENV = "AGENTFACTORY_MODEL_API_KEY"
_TASK_MODEL_BASE_URL_ENV = "AGENTFACTORY_TASK_MODEL_BASE_URL"
_TASK_MODEL_API_KEY_ENV = "AGENTFACTORY_TASK_MODEL_API_KEY"


@dataclass(frozen=True, slots=True)
class ChatModelSettings:
    role: str
    provider: str
    profile: ProviderProfile
    model: str | None
    api_key: str | None
    base_url: str | None
    profile_id: str | None = None
    source: str = "env"
    temperature: float | None = None
    timeout_seconds: float | None = None
    max_output_tokens: int | None = None
    max_input_tokens: int | None = None
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
    return _get_main_model()


def get_task_model() -> BaseChatModel | None:
    return _get_task_model()


def get_compression_model() -> BaseChatModel | None:
    return _get_compression_model()


def get_main_model_settings() -> ChatModelSettings:
    return _main_settings()


def get_task_model_settings() -> ChatModelSettings:
    return _task_settings()


def get_compression_model_settings() -> ChatModelSettings:
    return _compression_settings()


def reset_chat_models() -> None:
    _get_main_model.cache_clear()
    _get_task_model.cache_clear()
    _get_compression_model.cache_clear()


def create_chat_model_from_settings(settings: ChatModelSettings) -> BaseChatModel | None:
    return _create_model(settings)


def list_supported_chat_model_profiles() -> list[dict[str, object]]:
    return [provider_profile_payload(profile) for profile in list_provider_profiles()]


@lru_cache(maxsize=1)
def _get_main_model() -> BaseChatModel | None:
    return _create_model(_main_settings())


@lru_cache(maxsize=1)
def _get_task_model() -> BaseChatModel | None:
    return _create_model(_task_settings())


@lru_cache(maxsize=1)
def _get_compression_model() -> BaseChatModel | None:
    return _create_model(_compression_settings())


def _create_model(settings: ChatModelSettings) -> BaseChatModel | None:
    if not settings.available:
        return None
    return adapter_for_profile(settings.profile).create_chat_model(settings)


def _main_settings() -> ChatModelSettings:
    provider = _provider_setting("AGENTFACTORY_MODEL_PROVIDER")
    return ChatModelSettings(
        role="main",
        provider=provider,
        profile=resolve_provider_profile(provider),
        model=os.getenv("AGENTFACTORY_MAIN_MODEL"),
        api_key=_first_env(_MODEL_API_KEY_ENV),
        base_url=_first_env(_MODEL_BASE_URL_ENV),
        temperature=_env_float("AGENTFACTORY_MODEL_TEMPERATURE", default=_DEFAULT_MAIN_TEMPERATURE),
        timeout_seconds=_env_float("AGENTFACTORY_MODEL_TIMEOUT_SECONDS", default=_DEFAULT_MODEL_TIMEOUT_SECONDS),
        max_output_tokens=_env_int("AGENTFACTORY_MODEL_MAX_OUTPUT_TOKENS", default=_DEFAULT_MAIN_MAX_OUTPUT_TOKENS),
        max_input_tokens=_env_int("AGENTFACTORY_MODEL_MAX_INPUT_TOKENS"),
        multimodal=bool(_env_bool("AGENTFACTORY_MAIN_MODEL_MULTIMODAL") or False),
        reasoning=_reasoning_settings("AGENTFACTORY_MODEL"),
        structured_output_method=_structured_method_setting("AGENTFACTORY_MODEL_STRUCTURED_OUTPUT_METHOD"),
    )


def _task_settings() -> ChatModelSettings:
    provider = _provider_setting("AGENTFACTORY_TASK_MODEL_PROVIDER")
    return ChatModelSettings(
        role="task",
        provider=provider,
        profile=resolve_provider_profile(provider),
        model=_first_env("AGENTFACTORY_TASK_MODEL", "AGENTFACTORY_MAIN_MODEL"),
        api_key=_first_env(_TASK_MODEL_API_KEY_ENV, _MODEL_API_KEY_ENV),
        base_url=_first_env(_TASK_MODEL_BASE_URL_ENV, _MODEL_BASE_URL_ENV),
        temperature=_env_float("AGENTFACTORY_TASK_MODEL_TEMPERATURE", default=_DEFAULT_TASK_TEMPERATURE),
        timeout_seconds=_env_float("AGENTFACTORY_MODEL_TIMEOUT_SECONDS", default=_DEFAULT_MODEL_TIMEOUT_SECONDS),
        max_output_tokens=_env_int("AGENTFACTORY_TASK_MODEL_MAX_OUTPUT_TOKENS", default=_DEFAULT_TASK_MAX_OUTPUT_TOKENS),
        max_input_tokens=_env_int("AGENTFACTORY_MODEL_MAX_INPUT_TOKENS"),
        multimodal=False,
        reasoning=_reasoning_settings("AGENTFACTORY_TASK"),
        structured_output_method=_structured_method_setting("AGENTFACTORY_TASK_MODEL_STRUCTURED_OUTPUT_METHOD"),
    )


def _compression_settings() -> ChatModelSettings:
    provider = _provider_setting(
        "AGENTFACTORY_COMPRESSION_MODEL_PROVIDER",
        fallback_env_names=("AGENTFACTORY_TASK_MODEL_PROVIDER", "AGENTFACTORY_MODEL_PROVIDER"),
    )
    return ChatModelSettings(
        role="compression",
        provider=provider,
        profile=resolve_provider_profile(provider),
        model=_first_env("AGENTFACTORY_COMPRESSION_MODEL", "AGENTFACTORY_TASK_MODEL", "AGENTFACTORY_MAIN_MODEL"),
        api_key=_first_env("AGENTFACTORY_COMPRESSION_MODEL_API_KEY", _TASK_MODEL_API_KEY_ENV, _MODEL_API_KEY_ENV),
        base_url=_first_env("AGENTFACTORY_COMPRESSION_MODEL_BASE_URL", _TASK_MODEL_BASE_URL_ENV, _MODEL_BASE_URL_ENV),
        temperature=_env_float("AGENTFACTORY_COMPRESSION_MODEL_TEMPERATURE", default=_DEFAULT_COMPRESSION_TEMPERATURE),
        timeout_seconds=_env_float(
            "AGENTFACTORY_COMPRESSION_MODEL_TIMEOUT_SECONDS",
            default=_DEFAULT_MODEL_TIMEOUT_SECONDS,
        ),
        max_output_tokens=_env_int(
            "AGENTFACTORY_COMPRESSION_MODEL_MAX_OUTPUT_TOKENS",
            default=_DEFAULT_COMPRESSION_MAX_OUTPUT_TOKENS,
        ),
        max_input_tokens=_env_int("AGENTFACTORY_MODEL_MAX_INPUT_TOKENS"),
        multimodal=False,
        reasoning=_reasoning_settings("AGENTFACTORY_COMPRESSION"),
        structured_output_method=_structured_method_setting("AGENTFACTORY_COMPRESSION_MODEL_STRUCTURED_OUTPUT_METHOD"),
    )


def _env_float(name: str, *, default: float | None = None) -> float | None:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_int(name: str, *, default: int | None = None) -> int | None:
    value = os.getenv(name)
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else None


def _env_choice(name: str, allowed: set[str]) -> str | None:
    value = os.getenv(name)
    if not value:
        return None
    normalized = value.strip().lower()
    if normalized in allowed:
        return normalized
    return None


def _provider_setting(role_env_name: str, *, fallback_env_names: tuple[str, ...] = ("AGENTFACTORY_MODEL_PROVIDER",)) -> str:
    value = os.getenv(role_env_name)
    for fallback_name in fallback_env_names:
        if value or fallback_name == role_env_name:
            continue
        value = os.getenv(fallback_name)
    return (value or _DEFAULT_PROVIDER).strip().lower() or _DEFAULT_PROVIDER


def _structured_method_setting(role_env_name: str) -> StructuredOutputMethod | None:
    value = _env_choice(role_env_name, _STRUCTURED_OUTPUT_METHODS)
    if value is None:
        value = _env_choice("AGENTFACTORY_MODEL_STRUCTURED_OUTPUT_METHOD", _STRUCTURED_OUTPUT_METHODS)
    return value  # type: ignore[return-value]


def _reasoning_settings(prefix: str) -> ModelReasoningSettings:
    mode = _env_choice(f"{prefix}_REASONING", _REASONING_MODE_VALUES)
    return ModelReasoningSettings(
        enabled=_reasoning_enabled(mode),
        effort=_clean_env(f"{prefix}_REASONING_EFFORT"),
        summary=_clean_env(f"{prefix}_REASONING_SUMMARY"),
        budget_tokens=_env_int(f"{prefix}_REASONING_BUDGET_TOKENS"),
        send_history=_env_bool(f"{prefix}_SEND_REASONING_HISTORY"),
    )


def _reasoning_enabled(mode: str | None) -> bool | None:
    if mode == "enabled":
        return True
    if mode == "disabled":
        return False
    return None


def _env_bool(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "enabled"}:
        return True
    if normalized in {"0", "false", "no", "off", "disabled"}:
        return False
    return None


def _clean_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    text = value.strip()
    return text or None


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value and value.strip():
            return value.strip()
    return None
