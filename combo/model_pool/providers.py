from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from combo.models import list_supported_chat_model_profiles


ModelPoolProviderKind = Literal["chat", "embedding", "image_generation"]


@dataclass(frozen=True, slots=True)
class ModelPoolProviderProfile:
    provider_id: str
    display_name: str
    kind: ModelPoolProviderKind
    adapter_id: str
    transport: str
    default_base_url: str = ""
    notes: tuple[str, ...] = ()
    capabilities: dict[str, Any] | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "kind": self.kind,
            "supported_kinds": [self.kind],
            "adapter_id": self.adapter_id,
            "transport": self.transport,
            "default_base_url": self.default_base_url,
            "capabilities": dict(self.capabilities or {}),
            "notes": list(self.notes),
        }


IMAGE_GENERATION_PROVIDERS: dict[str, ModelPoolProviderProfile] = {
    "openai": ModelPoolProviderProfile(
        provider_id="openai",
        display_name="OpenAI 兼容协议",
        kind="image_generation",
        adapter_id="openai_image",
        transport="openai_images",
        default_base_url="https://api.openai.com/v1",
        capabilities={
            "text_to_image": True,
            "image_to_image": True,
            "image_edit": True,
            "multi_image_reference": True,
            "batch_generation": True,
        },
        notes=("Use this provider for GPT image models such as gpt-image-2.",),
    ),
    "dashscope": ModelPoolProviderProfile(
        provider_id="dashscope",
        display_name="阿里云 DashScope",
        kind="image_generation",
        adapter_id="dashscope_wanx",
        transport="dashscope_multimodal_generation",
        default_base_url="https://dashscope.aliyuncs.com/api/v1",
        capabilities={
            "text_to_image": True,
            "image_to_image": True,
            "image_edit": True,
            "multi_image_reference": True,
            "batch_generation": True,
        },
        notes=("Generated remote URLs are treated as temporary and must be copied into runtime artifacts.",),
    ),
}

_IMAGE_GENERATION_PROVIDER_ALIASES = {
    "qwen": "dashscope",
    "dashscope_wanx": "dashscope",
    "wanx": "dashscope",
    "aliyun_wanx": "dashscope",
    "openai_image": "openai",
    "volcengine_seedream": "openai",
}


def list_model_pool_provider_profiles() -> list[dict[str, Any]]:
    chat_by_id = {str(item["provider_id"]): dict(item) for item in list_supported_chat_model_profiles()}
    result: list[dict[str, Any]] = []
    for provider_id in ("dashscope", "openai", "anthropic"):
        payload = chat_by_id[provider_id]
        payload["kind"] = "chat"
        payload["supported_kinds"] = ["chat"]
        if provider_id != "anthropic":
            payload["supported_kinds"].extend(("embedding", "image_generation"))
            payload["capabilities"] = dict(IMAGE_GENERATION_PROVIDERS[provider_id].capabilities or {})
            payload["default_base_url"] = IMAGE_GENERATION_PROVIDERS[provider_id].default_base_url
        else:
            payload["default_base_url"] = "https://api.anthropic.com"
            payload["capabilities"] = {}
        result.append(payload)
    return result


def provider_kind(provider: str) -> ModelPoolProviderKind:
    provider_id = str(provider or "").strip().lower()
    if provider_id in IMAGE_GENERATION_PROVIDERS:
        return "image_generation"
    for item in list_supported_chat_model_profiles():
        if str(item.get("provider_id") or "").strip().lower() == provider_id:
            return "chat"
    raise ValueError(f"unsupported model pool provider: {provider}")


def provider_supports_kind(provider: str, kind: ModelPoolProviderKind) -> bool:
    provider_id = _canonical_image_provider(str(provider or "").strip().lower())
    if kind == "image_generation":
        return provider_id in IMAGE_GENERATION_PROVIDERS
    for item in list_supported_chat_model_profiles():
        if str(item.get("provider_id") or "").strip().lower() != provider_id:
            continue
        if kind == "chat":
            return True
        return _chat_provider_supports_embedding(item)
    return False


def ensure_provider_supported(provider: str) -> str:
    provider_id = str(provider or "").strip().lower()
    canonical = _canonical_image_provider(provider_id)
    if canonical in IMAGE_GENERATION_PROVIDERS:
        return canonical
    for item in list_supported_chat_model_profiles():
        if str(item.get("provider_id") or "").strip().lower() == provider_id:
            return provider_id
    raise ValueError(f"unsupported model pool provider: {provider}")


def image_generation_provider_capabilities(provider: str) -> dict[str, bool]:
    profile = IMAGE_GENERATION_PROVIDERS.get(_canonical_image_provider(str(provider or "").strip().lower()))
    if profile is None:
        raise ValueError(f"unsupported image generation provider: {provider}")
    return {key: bool(value) for key, value in dict(profile.capabilities or {}).items()}


def _canonical_image_provider(provider: str) -> str:
    return _IMAGE_GENERATION_PROVIDER_ALIASES.get(provider, provider)


def _chat_provider_supports_embedding(provider: dict[str, Any]) -> bool:
    # External embeddings use the same OpenAI-compatible credential and
    # transport as chat. Native Messages providers (for example Anthropic)
    # are deliberately excluded because their credential cannot be sent to
    # an /embeddings endpoint.
    return str(provider.get("transport") or "").strip().lower() == "openai_chat_completions"
