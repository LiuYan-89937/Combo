from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol, cast

from combo.models.adapters.base import ChatModelAdapter
from combo.models.capabilities import ProviderProfile


class _AdapterFactory(Protocol):
    def __call__(self, profile: ProviderProfile) -> ChatModelAdapter: ...


@dataclass(frozen=True, slots=True)
class _AdapterSpec:
    module: str
    class_name: str


def adapter_for_profile(profile: ProviderProfile) -> ChatModelAdapter:
    spec = _ADAPTER_SPECS.get(profile.adapter_id)
    if spec is None:
        raise ValueError(f"unsupported chat model adapter: {profile.adapter_id}")
    module = import_module(spec.module)
    adapter_type: Any = getattr(module, spec.class_name, None)
    if not isinstance(adapter_type, type):
        raise TypeError(
            f"chat model adapter {profile.adapter_id} does not expose {spec.class_name}"
        )
    return cast(_AdapterFactory, adapter_type)(profile)


_ADAPTER_SPECS = {
    "openai_chat": _AdapterSpec("combo.models.adapters.openai_chat", "OpenAIChatAdapter"),
    "openai_compatible_chat": _AdapterSpec(
        "combo.models.adapters.openai_chat",
        "GenericOpenAICompatibleChatAdapter",
    ),
    "openai_responses": _AdapterSpec(
        "combo.models.adapters.openai_responses",
        "GenericOpenAIResponsesAdapter",
    ),
    "deepseek": _AdapterSpec("combo.models.adapters.deepseek", "DeepSeekChatAdapter"),
    "qwen": _AdapterSpec("combo.models.adapters.qwen", "QwenChatAdapter"),
    "zhipu": _AdapterSpec("combo.models.adapters.zhipu", "ZhipuChatAdapter"),
    "kimi": _AdapterSpec("combo.models.adapters.kimi", "KimiChatAdapter"),
    "minimax": _AdapterSpec("combo.models.adapters.minimax", "MiniMaxChatAdapter"),
    "mimo": _AdapterSpec("combo.models.adapters.mimo", "MiMoChatAdapter"),
    "hunyuan": _AdapterSpec("combo.models.adapters.hunyuan", "HunyuanChatAdapter"),
}
