from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from langchain_core.embeddings import Embeddings


@dataclass(frozen=True, slots=True)
class EmbeddingModelSettings:
    provider: str
    model: str | None
    api_key: str | None
    base_url: str | None
    dims: int | None
    batch_size: int
    timeout_seconds: float | None = None
    profile_id: str | None = None
    source: str = "model_pool"
    headers: dict[str, str] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return bool(self.model and self.api_key and self.base_url and self.dims)


class BatchedEmbeddings(Embeddings):
    """Apply the configured document-batch limit to every embedding consumer."""

    def __init__(self, delegate: Embeddings, *, batch_size: int) -> None:
        if batch_size < 1:
            raise ValueError("embedding batch_size must be positive")
        self._delegate = delegate
        self._batch_size = batch_size

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), self._batch_size):
            batch = texts[offset:offset + self._batch_size]
            batch_vectors = self._delegate.embed_documents(batch)
            if len(batch_vectors) != len(batch):
                raise RuntimeError("embedding provider returned a different number of vectors than input texts")
            vectors.extend(batch_vectors)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._delegate.embed_query(text)


def create_embedding_model_from_settings(settings: EmbeddingModelSettings) -> Embeddings | None:
    if not settings.available:
        return None
    from langchain_openai import OpenAIEmbeddings

    kwargs: dict[str, Any] = {
        "model": settings.model,
        "api_key": settings.api_key,
        "base_url": settings.base_url,
        "dimensions": settings.dims,
        "model_kwargs": {"encoding_format": "float"},
        "tiktoken_enabled": False,
        "check_embedding_ctx_length": False,
    }
    if settings.timeout_seconds is not None:
        kwargs["timeout"] = settings.timeout_seconds
    if settings.headers:
        kwargs["default_headers"] = dict(settings.headers)
    return BatchedEmbeddings(OpenAIEmbeddings(**kwargs), batch_size=settings.batch_size)
