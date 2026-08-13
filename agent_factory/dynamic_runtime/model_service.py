from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_factory.model_pool.store import ModelPoolStore
from agent_factory.models import ChatModelSettings, resolve_provider_profile
from agent_factory.models.chat_model import create_chat_model_from_settings
from agent_factory.models.protocol import ModelReasoningSettings
from agent_factory.models.reasoning import apply_reasoning_intensity
from agent_factory.runtime_kernel.model_operations import RuntimeModelHandle, RuntimeModelHandleRegistry
from agent_factory.runtime_protocol import (
    ApprovalMode,
    ExecutionPreference,
    ModelOperationKind,
    ModelSelectionSnapshot,
    RuntimePolicySnapshot,
    UserRuntimePolicy,
)


class RuntimeModelResolutionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ResolvedRuntimeChatModel:
    snapshot: ModelSelectionSnapshot
    model: Any
    settings: ChatModelSettings
    input_modalities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResolvedRuntimePolicy:
    snapshot: RuntimePolicySnapshot
    chat_model: ResolvedRuntimeChatModel


class RuntimeModelResolver:
    """Resolve one immutable model selection without role or environment fallback."""

    def __init__(self, store: ModelPoolStore) -> None:
        self._store = store

    def resolve_chat_model(
        self,
        *,
        operation: ModelOperationKind,
        profile_id: str,
        expected_profile_revision: int | None = None,
        expected_credential_revision: int | None = None,
        reasoning_intensity: int | None = None,
    ) -> ResolvedRuntimeChatModel:
        normalized_profile_id = _required_text(profile_id, "profile_id")
        profile = (
            self._store.require_profile_revision(normalized_profile_id, expected_profile_revision)
            if expected_profile_revision is not None
            else self._store.require_profile(normalized_profile_id)
        )
        if profile.kind != "chat":
            raise RuntimeModelResolutionError(
                f"runtime chat operation requires a chat model profile: {profile.profile_id}"
            )
        if not profile.enabled:
            raise RuntimeModelResolutionError(f"model profile is disabled: {profile.profile_id}")
        credential = (
            self._store.require_credential_revision(
                profile.credential_id,
                expected_credential_revision,
            )
            if expected_credential_revision is not None
            else self._store.require_credential(profile.credential_id)
        )
        if not credential.enabled:
            raise RuntimeModelResolutionError(f"model credential is disabled: {credential.credential_id}")
        if not credential.api_key:
            raise RuntimeModelResolutionError(f"model credential has no API key: {credential.credential_id}")
        settings = ChatModelSettings(
            role=operation,
            provider=profile.provider,
            profile=resolve_provider_profile(profile.provider),
            model=profile.model_name,
            api_key=credential.api_key,
            base_url=credential.base_url,
            profile_id=profile.profile_id,
            source="model_pool",
            temperature=profile.settings.temperature,
            timeout_seconds=profile.limits.timeout_seconds,
            max_output_tokens=profile.limits.max_output_tokens,
            max_input_tokens=profile.limits.max_input_tokens,
            compression_trigger_tokens=profile.limits.compression_trigger_tokens,
            multimodal="image" in profile.capabilities.input_modalities,
            reasoning=ModelReasoningSettings(),
            structured_output_method=None,
        )
        if reasoning_intensity is not None:
            settings = apply_reasoning_intensity(settings, reasoning_intensity)
        model = create_chat_model_from_settings(settings)
        if model is None:
            raise RuntimeModelResolutionError(f"model profile is not runnable: {profile.profile_id}")
        snapshot = ModelSelectionSnapshot(
            operation=operation,
            profile_id=profile.profile_id,
            profile_revision=profile.revision,
            credential_resource_id=credential.credential_id,
            credential_revision=credential.revision,
            provider=profile.provider,
            model_name=profile.model_name,
            temperature=profile.settings.temperature,
            max_output_tokens=profile.limits.max_output_tokens,
        )
        return ResolvedRuntimeChatModel(
            snapshot=snapshot,
            model=model,
            settings=settings,
            input_modalities=tuple(profile.capabilities.input_modalities),
        )

    def resolve_policy(
        self,
        policy: UserRuntimePolicy,
        *,
        operation: ModelOperationKind,
        execution_preference: ExecutionPreference | None = None,
        approval_mode: ApprovalMode | None = None,
    ) -> ResolvedRuntimePolicy:
        if not policy.model_profile_id:
            raise RuntimeModelResolutionError("runtime policy requires an explicit model_profile_id")
        resolved = self.resolve_chat_model(
            operation=operation,
            profile_id=policy.model_profile_id,
            reasoning_intensity=policy.reasoning_intensity,
        )
        snapshot = RuntimePolicySnapshot(
            principal_id=policy.principal_id,
            source_policy_id=policy.policy_id,
            source_policy_revision=policy.revision,
            execution_preference=execution_preference or policy.execution_preference,
            execution_preference_source="command" if execution_preference is not None else "user_policy",
            approval_mode=approval_mode or policy.approval_mode,
            approval_mode_source="command" if approval_mode is not None else "user_policy",
            model=resolved.snapshot,
            reasoning_intensity=policy.reasoning_intensity,
            request_timeout_seconds=policy.request_timeout_seconds,
            browser_operation_timeout_ms=policy.browser_operation_timeout_ms,
            browser_navigation_timeout_ms=policy.browser_navigation_timeout_ms,
            max_model_attempts=policy.max_model_attempts,
            max_parallel_temporary_agents=policy.max_parallel_temporary_agents,
            memory_auto_write_enabled=policy.memory_auto_write_enabled,
            memory_write_interval_turns=policy.memory_write_interval_turns,
            memory_agent_write_enabled=policy.memory_agent_write_enabled,
            memory_max_injected_items=policy.memory_max_injected_items,
            memory_max_injected_tokens=policy.memory_max_injected_tokens,
            max_temporary_delegation_depth=policy.max_temporary_delegation_depth,
            delegation_grant_ttl_seconds=policy.delegation_grant_ttl_seconds,
            timezone=policy.timezone,
        )
        return ResolvedRuntimePolicy(snapshot=snapshot, chat_model=resolved)


def register_runtime_model_handle(
    registry: RuntimeModelHandleRegistry,
    *,
    runtime_instance_id: str,
    resolved: ResolvedRuntimeChatModel,
) -> RuntimeModelHandle:
    handle = RuntimeModelHandle(
        runtime_instance_id=_required_text(runtime_instance_id, "runtime_instance_id"),
        snapshot=resolved.snapshot,
        model=resolved.model,
        settings=resolved.settings,
    )
    registry.register(handle)
    return handle


def _required_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise RuntimeModelResolutionError(f"{field_name} must not be empty")
    return text
