from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings


@dataclass(frozen=True, slots=True)
class EmbeddingModelSettings:
    provider: str
    model: str | None
    api_key: str | None
    base_url: str | None
    dims: int | None
    timeout_seconds: float | None = None

    @property
    def available(self) -> bool:
        return (
            self.provider == "openai_compatible"
            and bool(self.model)
            and bool(self.api_key)
            and bool(self.base_url)
            and bool(self.dims)
        )


def get_embedding_model() -> Embeddings | None:
    return _get_embedding_model()


def get_embedding_model_settings() -> EmbeddingModelSettings:
    return _embedding_settings()


def reset_embedding_model() -> None:
    _get_embedding_model.cache_clear()


@lru_cache(maxsize=1)
def _get_embedding_model() -> Embeddings | None:
    settings = _embedding_settings()
    if not settings.available:
        return None
    kwargs = {
        "model": settings.model,
        "api_key": settings.api_key,
        "base_url": settings.base_url,
        "dimensions": settings.dims,
        "tiktoken_enabled": False,
        "check_embedding_ctx_length": False,
    }
    if settings.timeout_seconds is not None:
        kwargs["timeout"] = settings.timeout_seconds
    return OpenAIEmbeddings(**kwargs)


def _embedding_settings() -> EmbeddingModelSettings:
    return EmbeddingModelSettings(
        provider=(os.getenv("AGENTFACTORY_EMBEDDING_PROVIDER", "openai_compatible").strip().lower() or "openai_compatible"),
        model=os.getenv("AGENTFACTORY_EMBEDDING_MODEL"),
        api_key=os.getenv("AGENTFACTORY_EMBEDDING_API_KEY"),
        base_url=os.getenv("AGENTFACTORY_EMBEDDING_BASE_URL"),
        dims=_env_int("AGENTFACTORY_EMBEDDING_DIMS"),
        timeout_seconds=_env_float("AGENTFACTORY_EMBEDDING_TIMEOUT_SECONDS"),
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
