from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os

from langchain_core.embeddings import Embeddings

from combo.model_pool.defaults import DEFAULT_EMBEDDING_BATCH_SIZE
from combo.model_pool.headers import credential_header_variables, render_credential_headers
from combo.model_pool.resolver import resolve_protocol_base_url
from combo.model_pool.store import ModelPoolStore, ModelPoolStoreNotInitialized
from combo.models.embedding_model import EmbeddingModelSettings, create_embedding_model_from_settings


@dataclass(frozen=True, slots=True)
class ResolvedEmbeddingModel:
    profile_id: str | None
    model: Embeddings
    settings: EmbeddingModelSettings


def get_embedding_model() -> Embeddings | None:
    return _cached_embedding_model()


def get_embedding_model_settings() -> EmbeddingModelSettings:
    return _embedding_settings()


def reset_embedding_model() -> None:
    _cached_embedding_model.cache_clear()


def resolve_embedding_model_profile(
    profile_id: str,
    *,
    store: ModelPoolStore | None = None,
) -> ResolvedEmbeddingModel:
    settings = _model_pool_settings(profile_id=profile_id, store=store)
    if settings is None:
        raise ValueError(f"embedding model profile is not configured: {profile_id}")
    model = create_embedding_model_from_settings(settings)
    if model is None:
        raise ValueError(f"embedding model profile is not runnable: {profile_id}")
    return ResolvedEmbeddingModel(profile_id=profile_id, model=model, settings=settings)


@lru_cache(maxsize=1)
def _cached_embedding_model() -> Embeddings | None:
    return create_embedding_model_from_settings(_embedding_settings())


def _embedding_settings() -> EmbeddingModelSettings:
    settings = _model_pool_settings()
    return settings if settings is not None else _legacy_embedding_settings()


def _model_pool_settings(
    *,
    profile_id: str | None = None,
    store: ModelPoolStore | None = None,
) -> EmbeddingModelSettings | None:
    if store is None:
        try:
            store = ModelPoolStore(setup=False)
        except ModelPoolStoreNotInitialized:
            return None
    selected_profile_id = profile_id or store.embedding_binding()
    if not selected_profile_id:
        selected_profile_id = next(
            (profile.profile_id for profile in store.list_profiles(kind="embedding", enabled=True)),
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
        headers=render_credential_headers(
            credential.headers,
            variables=credential_header_variables(profile_id=profile.profile_id),
        ),
    )


def _legacy_embedding_settings() -> EmbeddingModelSettings:
    return EmbeddingModelSettings(
        provider=os.getenv("COMBO_EMBEDDING_PROVIDER", "openai_compatible").strip().lower() or "openai_compatible",
        model=os.getenv("COMBO_EMBEDDING_MODEL"),
        api_key=os.getenv("COMBO_EMBEDDING_API_KEY"),
        base_url=os.getenv("COMBO_EMBEDDING_BASE_URL"),
        dims=_env_int("COMBO_EMBEDDING_DIMS"),
        batch_size=_env_int("COMBO_EMBEDDING_BATCH_SIZE") or DEFAULT_EMBEDDING_BATCH_SIZE,
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
