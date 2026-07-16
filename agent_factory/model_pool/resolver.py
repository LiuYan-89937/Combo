from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from agent_factory.artifact_system import ArtifactStore
from agent_factory.local_inference.config import load_local_image_endpoint
from agent_factory.model_pool.schema import (
    ExternalInferenceConfig,
    ModelProfileBinding,
    ModelToolBinding,
    StableDiffusionCppInferenceConfig,
)
from agent_factory.model_pool.store import ModelPoolStore
from agent_factory.models import ChatModelSettings
from agent_factory.models.chat_model import (
    create_chat_model_from_settings,
    get_compression_model_settings,
    get_main_model_settings,
    get_task_model_settings,
    settings_from_local_profile,
)
from agent_factory.models.image_generation import ImageGenerationService, ImageGenerationSettings


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
        raise ValueError("local_registry binding requires profile_id")
    profile = model_store.require_profile(binding.profile_id)
    if profile.kind != "chat":
        raise ValueError(f"local model profile {profile.profile_id} is {profile.kind}, expected chat")
    if not profile.enabled:
        raise ValueError(f"local model profile is disabled: {profile.profile_id}")
    artifact = model_store.require_artifact(profile.artifact_id)
    if not artifact.enabled:
        raise ValueError(f"local model artifact is disabled: {artifact.artifact_id}")
    overrides = binding.overrides
    settings = settings_from_local_profile(profile, role=role)
    settings = replace(
        settings,
        temperature=overrides.temperature,
        timeout_seconds=overrides.timeout_seconds or settings.timeout_seconds,
        max_output_tokens=overrides.max_output_tokens or settings.max_output_tokens,
        max_input_tokens=overrides.max_input_tokens or settings.max_input_tokens,
        multimodal=settings.multimodal if overrides.multimodal is None else overrides.multimodal,
        reasoning=settings.reasoning if overrides.reasoning is None else overrides.reasoning,
        structured_output_method=(
            settings.structured_output_method
            if overrides.structured_output_method is None
            else overrides.structured_output_method
        ),
    )
    model = create_chat_model_from_settings(settings)
    if model is None:
        raise ValueError(f"local model profile is not runnable: {profile.profile_id}")
    return ResolvedChatModelProfile(profile_id=profile.profile_id, model=model, settings=settings)


def resolve_chat_model_binding(
    binding: ModelProfileBinding,
    *,
    role: str,
    store: ModelPoolStore | None = None,
) -> ResolvedChatModelProfile:
    if binding.source == "local_default":
        settings = _default_settings(role)
        model = create_chat_model_from_settings(settings)
        if model is None:
            raise ValueError(f"default local model is not configured for role: {role}")
        return ResolvedChatModelProfile(profile_id=str(settings.profile_id or ""), model=model, settings=settings)
    return resolve_chat_model_profile(binding, role=role, store=store)


def resolve_image_generation_binding(
    binding: ModelToolBinding,
    *,
    artifact_store: ArtifactStore,
    store: ModelPoolStore | None = None,
) -> ResolvedImageGenerationProfile:
    model_store = store or ModelPoolStore(setup=False)
    profile_id = binding.profile_id
    if binding.source == "local_default":
        profile_id = model_store.resolve_default_profile_id("image_generation")
    if not profile_id:
        raise ValueError("image generation binding has no configured profile")
    profile = model_store.require_profile(profile_id)
    if profile.kind != "image_generation":
        raise ValueError(f"local model profile {profile.profile_id} is {profile.kind}, expected image_generation")
    artifact = model_store.require_artifact(profile.artifact_id)
    if not profile.enabled or not artifact.enabled:
        raise ValueError(f"local image generation profile is disabled: {profile.profile_id}")
    endpoint = load_local_image_endpoint(
        timeout_seconds=binding.overrides.timeout_seconds or profile.limits.timeout_seconds
    )
    inference = profile.inference
    if isinstance(inference, ExternalInferenceConfig):
        inference = inference.remote_inference
    if not isinstance(inference, StableDiffusionCppInferenceConfig):
        raise ValueError("image generation profile has no stable-diffusion.cpp runtime configuration")
    settings = ImageGenerationSettings(
        provider="stable_diffusion_cpp",
        model=profile.served_model_name,
        base_url=endpoint.base_url,
        profile_id=profile.profile_id,
        timeout_seconds=endpoint.timeout_seconds,
        default_options={
            "width": inference.default_width,
            "height": inference.default_height,
            "steps": inference.default_steps,
            "cfg_scale": inference.default_cfg_scale,
            "sampler": inference.default_sampler,
        },
    )
    return ResolvedImageGenerationProfile(
        profile_id=profile.profile_id,
        service=ImageGenerationService(settings=settings, artifact_store=artifact_store),
        settings=settings,
    )


def _default_settings(role: str) -> ChatModelSettings:
    if role == "main":
        return get_main_model_settings()
    if role == "compression":
        return get_compression_model_settings()
    return get_task_model_settings()
