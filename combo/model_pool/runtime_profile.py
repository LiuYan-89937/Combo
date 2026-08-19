from __future__ import annotations

from dataclasses import replace

from combo.model_pool.schema import ModelPoolCapabilities
from combo.models.capabilities import (
    FeatureScope,
    ModelProviderCapabilities,
    ProviderProfile,
    resolve_provider_profile,
)
from combo.models.protocol import StructuredOutputMethod


def resolve_model_pool_provider_profile(
    provider: str,
    capabilities: ModelPoolCapabilities,
) -> ProviderProfile:
    """Combine provider transport behavior with one model's declared capabilities."""

    provider_profile = resolve_provider_profile(provider)
    provider_capabilities = provider_profile.capabilities
    structured_output_methods = tuple(capabilities.structured_output_methods)
    return replace(
        provider_profile,
        capabilities=replace(
            provider_capabilities,
            image_input=_declared_feature(
                "image" in capabilities.input_modalities,
                provider_capabilities.image_input,
            ),
            audio_input=_declared_feature(
                "audio" in capabilities.input_modalities,
                provider_capabilities.audio_input,
            ),
            tool_calling=_declared_feature(
                capabilities.tool_calling,
                provider_capabilities.tool_calling,
            ),
            streaming_tool_calls=_declared_feature(
                capabilities.streaming_tool_calls,
                provider_capabilities.streaming_tool_calls,
            ),
            strict_tool_schema=_declared_feature(
                capabilities.strict_tool_schema,
                provider_capabilities.strict_tool_schema,
            ),
            structured_output_methods=structured_output_methods,
            default_structured_output_method=_default_structured_output_method(
                provider_capabilities,
                structured_output_methods,
            ),
            reasoning=_declared_feature(
                capabilities.reasoning_supported,
                provider_capabilities.reasoning,
            ),
            reasoning_efforts=_reasoning_efforts(
                capabilities,
                provider_capabilities,
            ),
            reasoning_content=_declared_feature(
                capabilities.reasoning_content,
                provider_capabilities.reasoning_content,
            ),
            send_reasoning_history=_reasoning_history_support(
                capabilities,
                provider_capabilities,
            ),
            cache_usage=_declared_feature(
                capabilities.cache_usage,
                provider_capabilities.cache_usage,
            ),
        ),
    )


def _declared_feature(enabled: bool, provider_support: FeatureScope) -> FeatureScope:
    if not enabled:
        return "unsupported"
    return provider_support if provider_support != "unsupported" else "model_specific"


def _default_structured_output_method(
    provider_capabilities: ModelProviderCapabilities,
    methods: tuple[StructuredOutputMethod, ...],
) -> StructuredOutputMethod:
    current = provider_capabilities.default_structured_output_method
    if current in methods or not methods:
        return current
    return methods[0]


def _reasoning_efforts(
    capabilities: ModelPoolCapabilities,
    provider_capabilities: ModelProviderCapabilities,
) -> tuple[str, ...]:
    if not capabilities.reasoning_supported:
        return ()
    return tuple(capabilities.reasoning_efforts) or provider_capabilities.reasoning_efforts


def _reasoning_history_support(
    capabilities: ModelPoolCapabilities,
    provider_capabilities: ModelProviderCapabilities,
) -> FeatureScope:
    if not capabilities.reasoning_supported or not capabilities.reasoning_content:
        return "unsupported"
    current = provider_capabilities.send_reasoning_history
    return current if current != "unsupported" else "model_specific"
