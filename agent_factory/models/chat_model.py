from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI


@dataclass(frozen=True, slots=True)
class ChatModelSettings:
    role: str
    model: str | None
    api_key: str | None
    base_url: str | None
    temperature: float | None = None
    max_tokens: int | None = None
    timeout_seconds: float | None = None

    @property
    def available(self) -> bool:
        return bool(self.model and self.api_key and self.base_url)


def get_main_model() -> BaseChatModel | None:
    return _get_main_model()


def get_task_model() -> BaseChatModel | None:
    return _get_task_model()


def get_main_model_settings() -> ChatModelSettings:
    return _main_settings()


def get_task_model_settings() -> ChatModelSettings:
    return _task_settings()


def reset_chat_models() -> None:
    _get_main_model.cache_clear()
    _get_task_model.cache_clear()


@lru_cache(maxsize=1)
def _get_main_model() -> BaseChatModel | None:
    return _create_model(_main_settings())


@lru_cache(maxsize=1)
def _get_task_model() -> BaseChatModel | None:
    return _create_model(_task_settings())


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
    if settings.max_tokens is not None:
        kwargs["max_tokens"] = settings.max_tokens
    if settings.timeout_seconds is not None:
        kwargs["timeout"] = settings.timeout_seconds
    return ChatOpenAI(**kwargs)


def _main_settings() -> ChatModelSettings:
    return ChatModelSettings(
        role="main",
        model=os.getenv("AGENTFACTORY_OPENAI_MODEL"),
        api_key=os.getenv("AGENTFACTORY_OPENAI_API_KEY"),
        base_url=os.getenv("AGENTFACTORY_OPENAI_BASE_URL"),
        temperature=_env_float("AGENTFACTORY_LLM_TEMPERATURE"),
        max_tokens=_env_int("AGENTFACTORY_LLM_MAX_OUTPUT_TOKENS"),
        timeout_seconds=_env_float("AGENTFACTORY_LLM_TIMEOUT_SECONDS"),
    )


def _task_settings() -> ChatModelSettings:
    return ChatModelSettings(
        role="task",
        model=os.getenv("AGENTFACTORY_TASK_MODEL"),
        api_key=os.getenv("AGENTFACTORY_OPENAI_API_KEY"),
        base_url=os.getenv("AGENTFACTORY_OPENAI_BASE_URL"),
        temperature=_env_float("AGENTFACTORY_TASK_TEMPERATURE"),
        max_tokens=_env_int("AGENTFACTORY_TASK_MAX_OUTPUT_TOKENS"),
        timeout_seconds=_env_float("AGENTFACTORY_LLM_TIMEOUT_SECONDS"),
    )


def _env_float(name: str) -> float | None:
    value = os.getenv(name)
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _env_int(name: str) -> int | None:
    value = os.getenv(name)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None
