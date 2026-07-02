from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_factory.model_pool.schema import ModelProfileBinding
from agent_factory.model_pool.store import ModelPoolStore
from agent_factory.models import ChatModelSettings, resolve_provider_profile
from agent_factory.models.chat_model import create_chat_model_from_settings


@dataclass(frozen=True, slots=True)
class ResolvedChatModelProfile:
    profile_id: str
    model: Any
    settings: ChatModelSettings


def resolve_chat_model_profile(
    binding: ModelProfileBinding,
    *,
    role: str,
    store: ModelPoolStore | None = None,
) -> ResolvedChatModelProfile:
    model_store = store or ModelPoolStore(setup=False)
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


def _default_reasoning():
    from agent_factory.models.protocol import ModelReasoningSettings

    return ModelReasoningSettings()
