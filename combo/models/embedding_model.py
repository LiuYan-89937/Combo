from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from typing import TYPE_CHECKING, Any

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from combo.model_pool.defaults import DEFAULT_EMBEDDING_BATCH_SIZE

if TYPE_CHECKING:
    from combo.model_pool.store import ModelPoolStore


@dataclass(frozen=True, slots=True)
class EmbeddingModelSettings:
    provider: str
    model: str | None
    api_key: str | None
    base_url: str | None
    dims: int | None
    batch_size: int = DEFAULT_EMBEDDING_BATCH_SIZE
    timeout_seconds: float | None = None
    profile_id: str | None = None
    source: str = "model_pool"

    @property
    def available(self) -> bool:
        return bool(self.model and self.api_key and self.base_url and self.dims)


@dataclass(frozen=True, slots=True)
class ResolvedEmbeddingModel:
    profile_id: str | None
    model: Embeddings
    settings: EmbeddingModelSettings


class BatchedEmbeddings(Embeddings):
    """Apply one configured document-batch limit to every embedding consumer."""

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
                raise RuntimeError(
                    "embedding provider returned a different number of vectors than input texts"
                )
            vectors.extend(batch_vectors)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._delegate.embed_query(text)


def get_embedding_model() -> Embeddings | None:
    return _get_embedding_model()


def get_embedding_model_settings() -> EmbeddingModelSettings:
    return _embedding_settings()


def reset_embedding_model() -> None:
    _get_embedding_model.cache_clear()


def resolve_embedding_model_profile(
    profile_id: str,
    *,
    store: ModelPoolStore | None = None,
) -> ResolvedEmbeddingModel:
    """Resolve one model-pool embedding profile using its shared credential."""

    settings = _model_pool_settings(profile_id=profile_id, store=store)
    if settings is None:
        raise ValueError(f"embedding model profile is not configured: {profile_id}")
    model = _create_embedding_model(settings)
    if model is None:
        raise ValueError(f"embedding model profile is not runnable: {profile_id}")
    return ResolvedEmbeddingModel(profile_id=profile_id, model=model, settings=settings)


@lru_cache(maxsize=1)
def _get_embedding_model() -> Embeddings | None:
    return _create_embedding_model(_embedding_settings())


def _create_embedding_model(settings: EmbeddingModelSettings) -> Embeddings | None:
    if not settings.available:
        return None
    kwargs: dict[str, Any] = {
        "model": settings.model,
        "api_key": settings.api_key,
        "base_url": settings.base_url,
        "dimensions": settings.dims,
        "tiktoken_enabled": False,
        "check_embedding_ctx_length": False,
    }
    if settings.timeout_seconds is not None:
        kwargs["timeout"] = settings.timeout_seconds
    return BatchedEmbeddings(
        OpenAIEmbeddings(**kwargs),
        batch_size=settings.batch_size,
    )


def _embedding_settings() -> EmbeddingModelSettings:
    pool_settings = _model_pool_settings()
    if pool_settings is not None:
        return pool_settings
    # Compatibility path for installations that have not created an
    # embedding profile yet. Once a model-pool embedding profile exists, the
    # pool is authoritative and these legacy variables are ignored.
    return _legacy_embedding_settings()


def _model_pool_settings(
    *,
    profile_id: str | None = None,
    store: ModelPoolStore | None = None,
) -> EmbeddingModelSettings | None:
    try:
        if store is None:
            from combo.model_pool.store import ModelPoolStore

            store = ModelPoolStore(setup=False)
        selected_profile_id = profile_id or store.embedding_binding()
        if not selected_profile_id:
            selected_profile_id = next(
                (
                    profile.profile_id
                    for profile in store.list_profiles(kind="embedding", enabled=True)
                ),
                None,
            )
        if not selected_profile_id:
            return None
        profile = store.require_profile(selected_profile_id)
        if profile.kind != "embedding":
            raise ValueError(f"model profile {selected_profile_id} is {profile.kind}, expected embedding")
        if not profile.enabled:
            raise ValueError(f"embedding model profile is disabled: {selected_profile_id}")
        credential = store.require_credential(profile.credential_id)
        if not credential.enabled:
            raise ValueError(f"embedding model credential is disabled: {credential.credential_id}")
        if not credential.api_key:
            raise ValueError(f"embedding model credential has no API key: {credential.credential_id}")
        from combo.model_pool.resolver import resolve_protocol_base_url

        return EmbeddingModelSettings(
            provider=profile.provider,
            model=profile.model_name,
            api_key=credential.api_key,
            base_url=resolve_protocol_base_url(profile.provider, credential.base_url, kind="embedding"),
            dims=profile.embedding_dimensions,
            batch_size=profile.embedding_batch_size or DEFAULT_EMBEDDING_BATCH_SIZE,
            timeout_seconds=profile.limits.timeout_seconds,
            profile_id=profile.profile_id,
            source="model_pool",
        )
    except ImportError:
        return None
    except Exception as exc:
        # A missing store is a normal first-run state. Configuration errors
        # from an explicitly assigned profile must remain visible to callers.
        from combo.model_pool.store import ModelPoolStoreError

        if isinstance(exc, ModelPoolStoreError) and "not initialized" in str(exc):
            return None
        raise


def _legacy_embedding_settings() -> EmbeddingModelSettings:
    return EmbeddingModelSettings(
        provider=(
            os.getenv("COMBO_EMBEDDING_PROVIDER", "openai_compatible").strip().lower()
            or "openai_compatible"
        ),
        model=os.getenv("COMBO_EMBEDDING_MODEL"),
        api_key=os.getenv("COMBO_EMBEDDING_API_KEY"),
        base_url=os.getenv("COMBO_EMBEDDING_BASE_URL"),
        dims=_env_int("COMBO_EMBEDDING_DIMS"),
        batch_size=(
            _env_int("COMBO_EMBEDDING_BATCH_SIZE")
            or DEFAULT_EMBEDDING_BATCH_SIZE
        ),
        timeout_seconds=_env_float("COMBO_EMBEDDING_TIMEOUT_SECONDS"),
        source="env_legacy",
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
