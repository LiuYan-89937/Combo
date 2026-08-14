from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from combo.artifact_system import ArtifactStore
from combo.model_pool.schema import (
    ModelProfileBinding,
    ModelSelectionRequest,
    ModelSelectionRequirement,
    ModelToolBinding,
)
from combo.model_pool.selector import ModelPoolSelector
from combo.model_pool.store import ModelPoolStore
from combo.models.image_generation import (
    ImageGenerationService,
    ImageGenerationSettings,
)
from combo.models import ChatModelSettings, resolve_provider_profile
from combo.models.chat_model import create_chat_model_from_settings


def resolve_protocol_base_url(provider: str, base_url: str, *, kind: str) -> str:
    normalized_provider = str(provider or "").strip().lower()
    normalized_url = str(base_url or "").strip().rstrip("/")
    if normalized_provider != "dashscope":
        return normalized_url
    origin = normalized_url.split("/api/v1", 1)[0].split("/compatible-mode/v1", 1)[0].rstrip("/")
    if kind in {"chat", "embedding"}:
        return f"{origin}/compatible-mode/v1"
    if kind == "image_generation":
        return f"{origin}/api/v1"
    raise ValueError(f"unsupported DashScope model kind: {kind}")


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
        base_url=resolve_protocol_base_url(profile.provider, credential.base_url, kind="chat"),
        profile_id=profile.profile_id,
        source="model_pool",
        temperature=(
            overrides.temperature
            if overrides.temperature is not None
            else profile.settings.temperature
        ),
        timeout_seconds=profile.limits.timeout_seconds,
        max_output_tokens=(
            overrides.max_output_tokens
            if overrides.max_output_tokens is not None
            else profile.limits.max_output_tokens
        ),
        max_input_tokens=profile.limits.max_input_tokens,
        compression_trigger_tokens=profile.limits.compression_trigger_tokens,
        multimodal="image" in profile.capabilities.input_modalities,
        reasoning=_default_reasoning(),
        structured_output_method=None,
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
    if binding.source == "runtime":
        raise ValueError(f"runtime {role} chat model must be resolved from request state")
    if not binding.profile_id:
        profile_id = _select_chat_profile_id(binding, role=role, store=store)
        binding = binding.model_copy(update={"profile_id": profile_id})
    return resolve_chat_model_profile(binding, role=role, store=store)


def resolve_available_chat_model(
    role: str,
    *,
    store: ModelPoolStore | None = None,
) -> ResolvedChatModelProfile | None:
    model_store = store or ModelPoolStore(setup=False)
    if role == "task":
        profile_id = model_store.task_model_binding()
        if not profile_id:
            return None
        try:
            return resolve_chat_model_profile(
                ModelProfileBinding(
                    source="model_pool",
                    profile_id=profile_id,
                    selection_source="manual",
                    reason="Use the explicitly configured task model.",
                ),
                role=role,
                store=model_store,
            )
        except (LookupError, ValueError):
            return None
    binding = ModelProfileBinding(
        source="model_pool",
        selection_source="auto",
        reason=f"Select an available {role} model from the configured model pool.",
    )
    try:
        return resolve_chat_model_binding(binding, role=role, store=model_store)
    except LookupError:
        return None


def resolve_image_generation_model_profile(
    binding: ModelToolBinding,
    *,
    artifact_store: ArtifactStore,
    store: ModelPoolStore | None = None,
) -> ResolvedImageGenerationProfile:
    model_store = store or ModelPoolStore(setup=False)
    if not binding.profile_id:
        raise ValueError("resolved model_pool image generation binding requires profile_id")
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
        base_url=resolve_protocol_base_url(profile.provider, credential.base_url, kind="image_generation"),
        profile_id=profile.profile_id,
        source="model_pool",
        timeout_seconds=profile.limits.timeout_seconds,
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
    if binding.source == "runtime":
        raise ValueError(
            f"runtime model tool binding must be resolved from request state: {binding.capability}"
        )
    if not binding.profile_id:
        profile_id = _select_image_profile_id(binding, store=store)
        if profile_id is None:
            return None
        binding = binding.model_copy(update={"profile_id": profile_id})
    return resolve_image_generation_model_profile(binding, artifact_store=artifact_store, store=store)


def _select_chat_profile_id(
    binding: ModelProfileBinding,
    *,
    role: str,
    store: ModelPoolStore | None,
) -> str:
    capabilities = binding.required_capabilities
    requirement_role = role if role in {"main", "task", "compression"} else "task"
    requirement = ModelSelectionRequirement(
        role=requirement_role,
        purpose=binding.reason,
        kind="chat",
        input_modalities=_modalities(capabilities, "input_modalities", ["text"]),
        output_modalities=_modalities(capabilities, "output_modalities", ["text"]),
        tool_calling=_optional_bool(capabilities.get("tool_calling")),
        structured_output_methods=_strings(capabilities.get("structured_output_methods")),
        reasoning_required=_optional_bool(capabilities.get("reasoning_required")),
        min_context_window_tokens=_optional_positive_int(capabilities.get("min_context_window_tokens")),
        optimize_for="balanced",
    )
    model_store = store or ModelPoolStore(setup=False)
    result = ModelPoolSelector(store=model_store).select(ModelSelectionRequest(requirements=[requirement]))
    recommendation = next((item for item in result.recommendations if item.role == requirement_role), None)
    if recommendation is None:
        raise LookupError(f"no configured model pool profile matches the {role} model requirements")
    return recommendation.profile_id


def _select_image_profile_id(
    binding: ModelToolBinding,
    *,
    store: ModelPoolStore | None,
) -> str | None:
    capabilities = binding.required_capabilities
    requirement = ModelSelectionRequirement(
        role="task",
        purpose=binding.reason,
        kind="image_generation",
        input_modalities=_modalities(capabilities, "input_modalities", ["text"]),
        output_modalities=_modalities(capabilities, "output_modalities", ["image"]),
        optimize_for="balanced",
    )
    result = ModelPoolSelector(store=store).select(ModelSelectionRequest(requirements=[requirement]))
    recommendation = next((item for item in result.recommendations if item.role == "task"), None)
    return recommendation.profile_id if recommendation is not None else None


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := str(item or "").strip())]


def _modalities(capabilities: dict[str, Any], key: str, fallback: list[str]) -> list[str]:
    values = _strings(capabilities.get(key))
    return values or fallback


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _optional_positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _default_reasoning():
    from combo.models.protocol import ModelReasoningSettings

    return ModelReasoningSettings()
