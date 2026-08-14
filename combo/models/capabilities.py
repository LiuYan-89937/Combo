from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from combo.models.protocol import ModelTransport, StructuredOutputMethod


FeatureScope = Literal["adapter", "model_specific", "unsupported"]


@dataclass(frozen=True, slots=True)
class ModelProviderCapabilities:
    transport: ModelTransport
    text_input: bool = True
    image_input: FeatureScope = "unsupported"
    audio_input: FeatureScope = "unsupported"
    tool_calling: FeatureScope = "adapter"
    streaming_tool_calls: FeatureScope = "model_specific"
    strict_tool_schema: FeatureScope = "model_specific"
    structured_output_methods: tuple[StructuredOutputMethod, ...] = ("json_mode", "function_calling")
    default_structured_output_method: StructuredOutputMethod = "json_mode"
    reasoning: FeatureScope = "unsupported"
    reasoning_efforts: tuple[str, ...] = ()
    reasoning_summaries: tuple[str, ...] = ()
    reasoning_content: FeatureScope = "unsupported"
    send_reasoning_history: FeatureScope = "unsupported"
    cache_usage: FeatureScope = "model_specific"

    def supports_structured_output_method(self, method: str | None) -> bool:
        return bool(method) and method in self.structured_output_methods

    def supports_reasoning(self) -> bool:
        return self.reasoning != "unsupported"


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    provider_id: str
    display_name: str
    adapter_id: str
    capabilities: ModelProviderCapabilities
    aliases: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


OPENAI_CHAT_CAPABILITIES = ModelProviderCapabilities(
    transport="openai_chat_completions",
    image_input="model_specific",
    tool_calling="adapter",
    structured_output_methods=("json_mode", "json_schema", "function_calling"),
    default_structured_output_method="json_schema",
    strict_tool_schema="model_specific",
)

GENERIC_OPENAI_COMPATIBLE_CHAT_CAPABILITIES = ModelProviderCapabilities(
    transport="openai_chat_completions",
    structured_output_methods=("json_mode", "function_calling"),
    default_structured_output_method="json_mode",
)

ANTHROPIC_CAPABILITIES = ModelProviderCapabilities(
    transport="anthropic_messages",
    image_input="model_specific",
    tool_calling="model_specific",
    streaming_tool_calls="adapter",
    strict_tool_schema="model_specific",
    structured_output_methods=("function_calling", "json_schema"),
    default_structured_output_method="json_schema",
    reasoning="model_specific",
    reasoning_efforts=("max", "xhigh", "high", "medium", "low"),
    reasoning_summaries=("summarized",),
    reasoning_content="model_specific",
    send_reasoning_history="adapter",
    cache_usage="model_specific",
)

DEEPSEEK_CAPABILITIES = ModelProviderCapabilities(
    transport="openai_chat_completions",
    tool_calling="model_specific",
    streaming_tool_calls="model_specific",
    strict_tool_schema="model_specific",
    structured_output_methods=("json_mode", "function_calling"),
    default_structured_output_method="json_mode",
    reasoning="model_specific",
    reasoning_efforts=("high", "max"),
    reasoning_content="model_specific",
    send_reasoning_history="model_specific",
    cache_usage="adapter",
)

QWEN_CAPABILITIES = ModelProviderCapabilities(
    transport="openai_chat_completions",
    image_input="model_specific",
    audio_input="model_specific",
    tool_calling="model_specific",
    structured_output_methods=("json_mode", "json_schema", "function_calling"),
    default_structured_output_method="json_mode",
    reasoning="model_specific",
    reasoning_efforts=("budget_tokens",),
    reasoning_content="model_specific",
    send_reasoning_history="model_specific",
)

ZHIPU_CAPABILITIES = ModelProviderCapabilities(
    transport="openai_chat_completions",
    image_input="model_specific",
    audio_input="model_specific",
    tool_calling="model_specific",
    structured_output_methods=("json_mode", "function_calling"),
    default_structured_output_method="json_mode",
    reasoning="model_specific",
    reasoning_efforts=("low", "medium", "high"),
    reasoning_content="model_specific",
    send_reasoning_history="model_specific",
)

KIMI_CAPABILITIES = ModelProviderCapabilities(
    transport="openai_chat_completions",
    image_input="model_specific",
    tool_calling="model_specific",
    structured_output_methods=("json_mode", "json_schema", "function_calling"),
    default_structured_output_method="json_schema",
    reasoning="model_specific",
    reasoning_content="model_specific",
    send_reasoning_history="model_specific",
    cache_usage="adapter",
)

MINIMAX_CAPABILITIES = ModelProviderCapabilities(
    transport="openai_chat_completions",
    image_input="model_specific",
    tool_calling="model_specific",
    structured_output_methods=("json_mode", "function_calling"),
    default_structured_output_method="json_mode",
    reasoning="model_specific",
    reasoning_efforts=("adaptive",),
    reasoning_content="model_specific",
    send_reasoning_history="model_specific",
)

MIMO_CAPABILITIES = ModelProviderCapabilities(
    transport="openai_chat_completions",
    image_input="model_specific",
    audio_input="model_specific",
    tool_calling="model_specific",
    structured_output_methods=("json_mode", "function_calling"),
    default_structured_output_method="json_mode",
    reasoning="model_specific",
    reasoning_content="model_specific",
    send_reasoning_history="model_specific",
    cache_usage="model_specific",
)

HUNYUAN_CAPABILITIES = ModelProviderCapabilities(
    transport="openai_chat_completions",
    image_input="model_specific",
    tool_calling="model_specific",
    structured_output_methods=("json_mode", "function_calling"),
    default_structured_output_method="json_mode",
)

PROVIDER_PROFILES: dict[str, ProviderProfile] = {
    "openai": ProviderProfile(
        provider_id="openai",
        display_name="OpenAI 兼容协议",
        adapter_id="openai_compatible_chat",
        capabilities=GENERIC_OPENAI_COMPATIBLE_CHAT_CAPABILITIES,
        aliases=(
            "openai_chat", "openai_compatible_chat", "openai_compatible", "generic_openai_chat",
            "generic", "deepseek", "deepseek_chat", "zhipu", "zai", "bigmodel", "glm",
            "kimi", "moonshot", "minimax", "mini_max", "mimo", "xiaomi_mimo", "xiaomi",
            "hunyuan", "tencent_hunyuan", "tencent", "openai_image", "volcengine_seedream",
        ),
    ),
    "dashscope": ProviderProfile(
        provider_id="dashscope",
        display_name="阿里云 DashScope",
        adapter_id="qwen",
        capabilities=QWEN_CAPABILITIES,
        aliases=("qwen", "aliyun_bailian", "bailian", "tongyi", "dashscope_wanx", "wanx", "aliyun_wanx"),
    ),
    "anthropic": ProviderProfile(
        provider_id="anthropic",
        display_name="Anthropic Messages",
        adapter_id="anthropic",
        capabilities=ANTHROPIC_CAPABILITIES,
        aliases=("claude",),
        notes=("Uses Anthropic native Messages API through langchain-anthropic.",),
    ),
}

_PROFILE_ALIASES: dict[str, str] = {
    alias: profile.provider_id
    for profile in PROVIDER_PROFILES.values()
    for alias in (profile.provider_id, *profile.aliases)
}


def resolve_provider_profile(provider: str | None) -> ProviderProfile:
    key = (provider or "openai").strip().lower()
    provider_id = _PROFILE_ALIASES.get(key)
    if provider_id is None:
        supported = ", ".join(sorted(PROVIDER_PROFILES))
        raise ValueError(f"unsupported model provider: {provider or ''}; supported providers: {supported}")
    return PROVIDER_PROFILES[provider_id]


def list_provider_profiles() -> list[ProviderProfile]:
    return [PROVIDER_PROFILES[key] for key in sorted(PROVIDER_PROFILES)]


def provider_profile_payload(profile: ProviderProfile) -> dict[str, object]:
    capabilities = profile.capabilities
    return {
        "provider_id": profile.provider_id,
        "display_name": profile.display_name,
        "adapter_id": profile.adapter_id,
        "transport": capabilities.transport,
        "content_parts": {
            "text": "adapter" if capabilities.text_input else "unsupported",
            "image": capabilities.image_input,
            "audio": capabilities.audio_input,
        },
        "tools": {
            "tool_calling": capabilities.tool_calling,
            "streaming_tool_calls": capabilities.streaming_tool_calls,
            "strict_tool_schema": capabilities.strict_tool_schema,
        },
        "structured_output_methods": list(capabilities.structured_output_methods),
        "default_structured_output_method": capabilities.default_structured_output_method,
        "reasoning": {
            "support": capabilities.reasoning,
            "efforts": list(capabilities.reasoning_efforts),
            "summaries": list(capabilities.reasoning_summaries),
            "reasoning_content": capabilities.reasoning_content,
            "send_reasoning_history": capabilities.send_reasoning_history,
        },
        "cache_usage": capabilities.cache_usage,
        "notes": list(profile.notes),
    }
