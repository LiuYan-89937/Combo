from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from agent_factory.artifact_system import ArtifactStore
from agent_factory.model_pool.schema import ModelProfileBinding, ModelToolBinding
from agent_factory.model_pool.store import ModelPoolStore
from agent_factory.models.image_generation import (
    ImageGenerationService,
    ImageGenerationSettings,
    get_image_generation_model_settings,
)
from agent_factory.models import (
    ChatModelSettings,
    get_compression_model_settings,
    get_main_model_settings,
    get_task_model_settings,
    resolve_provider_profile,
)
from agent_factory.models.chat_model import create_chat_model_from_settings


@dataclass(frozen=True, slots=True)
class ResolvedChatModelProfile:
    profile_id: str
    model: Any
    settings: ChatModelSettings


@dataclass(frozen=True, slots=True)
class ResolvedImageGenerationProfile:
    profile_id: str
    service: ImageGenerationService
    settings: ImageGenerationSettings


def resolve_chat_model_profile(
    binding: ModelProfileBinding,
    *,
    role: str,
    store: ModelPoolStore | None = None,
) -> ResolvedChatModelProfile:
    model_store = store or ModelPoolStore(setup=False)
    if not binding.profile_id:
        raise ValueError("model_pool chat binding requires profile_id")
    profile = model_store.require_profile(binding.profile_id)
    if profile.kind != "chat":
        raise ValueError(f"model profile {profile.profile_id} is {profile.kind}, expected chat")
    if not profile.enabled:
        raise ValueError(f"model profile is disabled: {profile.profile_id}")
    credential = model_store.require_credential(profile.credential_id)
    if not credential.enabled:
        raise ValueError(f"model credential is disabled: {credential.credential_id}")
    if not credential.api_key:
        raise ValueError(f"model credential has no API key: {credential.credential_id}")
    overrides = binding.overrides
    provider_profile = resolve_provider_profile(profile.provider)
    settings = ChatModelSettings(
        role=role,
        provider=profile.provider,
        profile=provider_profile,
        model=profile.model_name,
        api_key=credential.api_key,
        base_url=credential.base_url,
        profile_id=profile.profile_id,
        source="model_pool",
        temperature=overrides.temperature,
        timeout_seconds=overrides.timeout_seconds or profile.limits.timeout_seconds,
        max_output_tokens=overrides.max_output_tokens or profile.limits.max_output_tokens,
        max_input_tokens=overrides.max_input_tokens or profile.limits.max_input_tokens,
        multimodal=bool(overrides.multimodal) if overrides.multimodal is not None else ("image" in profile.capabilities.input_modalities),
        reasoning=overrides.reasoning or _default_reasoning(),
        structured_output_method=overrides.structured_output_method,
    )
    model = create_chat_model_from_settings(settings)
    if model is None:
        raise ValueError(f"model profile is not runnable: {profile.profile_id}")
    return ResolvedChatModelProfile(profile_id=profile.profile_id, model=model, settings=settings)


def resolve_chat_model_binding(
    binding: ModelProfileBinding,
    *,
    role: str,
    store: ModelPoolStore | None = None,
) -> ResolvedChatModelProfile:
    if binding.source == "env":
        return _resolve_env_chat_model(binding, role=role)
    return resolve_chat_model_profile(binding, role=role, store=store)


def resolve_image_generation_model_profile(
    binding: ModelToolBinding,
    *,
    artifact_store: ArtifactStore,
    store: ModelPoolStore | None = None,
) -> ResolvedImageGenerationProfile:
    model_store = store or ModelPoolStore(setup=False)
    if not binding.profile_id:
        raise ValueError("model_pool image generation binding requires profile_id")
    profile = model_store.require_profile(binding.profile_id)
    if profile.kind != "image_generation":
        raise ValueError(f"model profile {profile.profile_id} is {profile.kind}, expected image_generation")
    if not profile.enabled:
        raise ValueError(f"model profile is disabled: {profile.profile_id}")
    credential = model_store.require_credential(profile.credential_id)
    if not credential.enabled:
        raise ValueError(f"model credential is disabled: {credential.credential_id}")
    if not credential.api_key:
        raise ValueError(f"model credential has no API key: {credential.credential_id}")
    settings = ImageGenerationSettings(
        provider=profile.provider,
        model=profile.model_name,
        api_key=credential.api_key,
        base_url=credential.base_url,
        profile_id=profile.profile_id,
        source="model_pool",
        timeout_seconds=binding.overrides.timeout_seconds or profile.limits.timeout_seconds,
    )
    return ResolvedImageGenerationProfile(
        profile_id=profile.profile_id,
        service=ImageGenerationService(settings=settings, artifact_store=artifact_store),
        settings=settings,
    )


def resolve_image_generation_binding(
    binding: ModelToolBinding,
    *,
    artifact_store: ArtifactStore,
    store: ModelPoolStore | None = None,
) -> ResolvedImageGenerationProfile | None:
    if binding.source == "env":
        settings = get_image_generation_model_settings()
        if settings is None:
            return None
        if binding.overrides.timeout_seconds is not None:
            settings = replace(settings, timeout_seconds=binding.overrides.timeout_seconds)
        return ResolvedImageGenerationProfile(
            profile_id=settings.profile_id,
            service=ImageGenerationService(settings=settings, artifact_store=artifact_store),
            settings=settings,
        )
    return resolve_image_generation_model_profile(binding, artifact_store=artifact_store, store=store)


def _resolve_env_chat_model(binding: ModelProfileBinding, *, role: str) -> ResolvedChatModelProfile:
    settings = _env_chat_model_settings(role)
    overrides = binding.overrides
    settings = replace(
        settings,
        role=role,
        profile_id=None,
        source="env",
        temperature=settings.temperature if overrides.temperature is None else overrides.temperature,
        timeout_seconds=settings.timeout_seconds if overrides.timeout_seconds is None else overrides.timeout_seconds,
        max_output_tokens=(
            settings.max_output_tokens
            if overrides.max_output_tokens is None
            else overrides.max_output_tokens
        ),
        max_input_tokens=settings.max_input_tokens if overrides.max_input_tokens is None else overrides.max_input_tokens,
        multimodal=settings.multimodal if overrides.multimodal is None else overrides.multimodal,
        reasoning=settings.reasoning if overrides.reasoning is None else overrides.reasoning,
        structured_output_method=(settings.structured_output_method if overrides.structured_output_method is None else overrides.structured_output_method),
    )
    if not settings.available:
        raise ValueError(f"env {role} chat model is not configured")
    model = create_chat_model_from_settings(settings)
    if model is None:
        raise ValueError(f"env {role} chat model is not runnable")
    return ResolvedChatModelProfile(profile_id="", model=model, settings=settings)


def _env_chat_model_settings(role: str) -> ChatModelSettings:
    if role == "main":
        return get_main_model_settings()
    if role == "compression":
        return get_compression_model_settings()
    if role == "task":
        return get_task_model_settings()
    if role.startswith("tool:"):
        return get_task_model_settings()
    raise ValueError(f"env model binding does not support role: {role}")


def _default_reasoning():
    from agent_factory.models.protocol import ModelReasoningSettings

    return ModelReasoningSettings()
