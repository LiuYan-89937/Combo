from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from typing import Any, Literal

from langchain_core.language_models.chat_models import BaseChatModel

from agent_factory.models.openai_compat import ThinkingCompatibleChatOpenAI

StructuredOutputMethod = Literal["function_calling", "json_mode", "json_schema"]
_STRUCTURED_OUTPUT_METHODS: set[str] = {"function_calling", "json_mode", "json_schema"}


@dataclass(frozen=True, slots=True)
class ChatModelSettings:
    role: str
    model: str | None
    api_key: str | None
    base_url: str | None
    temperature: float | None = None
    timeout_seconds: float | None = None
    thinking: str | None = None
    structured_output_method: StructuredOutputMethod | None = None

    @property
    def available(self) -> bool:
        return bool(self.model and self.api_key and self.base_url)


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
    kwargs: dict[str, Any] = {
        "model": settings.model,
        "api_key": settings.api_key,
        "base_url": settings.base_url,
        "streaming": True,
    }
    if settings.temperature is not None:
        kwargs["temperature"] = settings.temperature
    if settings.timeout_seconds is not None:
        kwargs["timeout"] = settings.timeout_seconds
    thinking_body = _thinking_extra_body(settings.thinking)
    if thinking_body is not None:
        kwargs["extra_body"] = thinking_body
    if settings.thinking == "enabled":
        kwargs["preserve_reasoning_content"] = True
    return ThinkingCompatibleChatOpenAI(**kwargs)


def _main_settings() -> ChatModelSettings:
    return ChatModelSettings(
        role="main",
        model=os.getenv("AGENTFACTORY_OPENAI_MODEL"),
        api_key=os.getenv("AGENTFACTORY_OPENAI_API_KEY"),
        base_url=os.getenv("AGENTFACTORY_OPENAI_BASE_URL"),
        temperature=_env_float("AGENTFACTORY_LLM_TEMPERATURE"),
        timeout_seconds=_env_float("AGENTFACTORY_LLM_TIMEOUT_SECONDS"),
        thinking=_env_choice("AGENTFACTORY_LLM_THINKING", {"enabled", "disabled"}),
        structured_output_method=_structured_method_setting("AGENTFACTORY_LLM_STRUCTURED_OUTPUT_METHOD"),
    )


def _task_settings() -> ChatModelSettings:
    return ChatModelSettings(
        role="task",
        model=os.getenv("AGENTFACTORY_TASK_MODEL"),
        api_key=os.getenv("AGENTFACTORY_OPENAI_API_KEY"),
        base_url=os.getenv("AGENTFACTORY_OPENAI_BASE_URL"),
        temperature=_env_float("AGENTFACTORY_TASK_TEMPERATURE"),
        timeout_seconds=_env_float("AGENTFACTORY_LLM_TIMEOUT_SECONDS"),
        thinking=_env_choice("AGENTFACTORY_TASK_THINKING", {"enabled", "disabled"}),
        structured_output_method=_structured_method_setting("AGENTFACTORY_TASK_STRUCTURED_OUTPUT_METHOD"),
    )


def _compression_settings() -> ChatModelSettings:
    return ChatModelSettings(
        role="compression",
        model=os.getenv("AGENTFACTORY_COMPRESSION_MODEL"),
        api_key=os.getenv("AGENTFACTORY_COMPRESSION_API_KEY"),
        base_url=os.getenv("AGENTFACTORY_COMPRESSION_BASE_URL"),
        temperature=_env_float("AGENTFACTORY_COMPRESSION_TEMPERATURE"),
        timeout_seconds=_env_float("AGENTFACTORY_COMPRESSION_TIMEOUT_SECONDS"),
        thinking=_env_choice("AGENTFACTORY_COMPRESSION_THINKING", {"enabled", "disabled"}),
        structured_output_method=_structured_method_setting("AGENTFACTORY_COMPRESSION_STRUCTURED_OUTPUT_METHOD"),
    )


def _env_float(name: str) -> float | None:
    value = os.getenv(name)
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _env_choice(name: str, allowed: set[str]) -> str | None:
    value = os.getenv(name)
    if not value:
        return None
    normalized = value.strip().lower()
    if normalized in allowed:
        return normalized
    return None


def _structured_method_setting(role_env_name: str) -> StructuredOutputMethod | None:
    value = _env_choice(role_env_name, _STRUCTURED_OUTPUT_METHODS)
    if value is None:
        value = _env_choice("AGENTFACTORY_STRUCTURED_OUTPUT_METHOD", _STRUCTURED_OUTPUT_METHODS)
    return value  # type: ignore[return-value]


def _thinking_extra_body(thinking: str | None) -> dict[str, Any] | None:
    if thinking == "disabled":
        return {"thinking": {"type": "disabled"}}
    if thinking == "enabled":
        return {"thinking": {"type": "enabled"}}
    return None
