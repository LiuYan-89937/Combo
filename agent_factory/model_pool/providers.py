from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from agent_factory.models import list_supported_chat_model_profiles


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
    "openai_image": ModelPoolProviderProfile(
        provider_id="openai_image",
        display_name="OpenAI Images",
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
            "async_job": False,
        },
        notes=("Use this provider for GPT image models such as gpt-image-2.",),
    ),
    "qwen": ModelPoolProviderProfile(
        provider_id="qwen",
        display_name="Alibaba Bailian / Qwen / Wanx",
        kind="image_generation",
        adapter_id="dashscope_wanx",
        transport="dashscope_multimodal_generation",
        default_base_url="https://dashscope.aliyuncs.com",
        capabilities={
            "text_to_image": True,
            "image_to_image": True,
            "image_edit": True,
            "multi_image_reference": True,
            "batch_generation": True,
            "async_job": True,
        },
        notes=("Generated remote URLs are treated as temporary and must be copied into runtime artifacts.",),
    ),
    "volcengine_seedream": ModelPoolProviderProfile(
        provider_id="volcengine_seedream",
        display_name="Volcengine Ark / Seedream",
        kind="image_generation",
        adapter_id="volcengine_seedream",
        transport="volcengine_images",
        default_base_url="https://ark.cn-beijing.volces.com/api/v3",
        capabilities={
            "text_to_image": True,
            "image_to_image": True,
            "image_edit": True,
            "multi_image_reference": True,
            "batch_generation": True,
            "async_job": False,
        },
        notes=("Provider-specific endpoint paths can be supplied through provider_options when needed.",),
    ),
}

_IMAGE_GENERATION_PROVIDER_ALIASES = {
    "dashscope_wanx": "qwen",
    "wanx": "qwen",
    "aliyun_wanx": "qwen",
}


def list_model_pool_provider_profiles() -> list[dict[str, Any]]:
    chat_profiles = []
    for item in list_supported_chat_model_profiles():
        payload = dict(item)
        payload["kind"] = "chat"
        payload["supported_kinds"] = ["chat"]
        if _chat_provider_supports_embedding(payload):
            payload["supported_kinds"].append("embedding")
        payload.setdefault("default_base_url", "")
        payload.setdefault("capabilities", {})
        chat_profiles.append(payload)
    image_profiles = [profile.payload() for profile in IMAGE_GENERATION_PROVIDERS.values()]
    return sorted([*chat_profiles, *image_profiles], key=lambda item: (str(item.get("kind")), str(item.get("provider_id"))))


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
