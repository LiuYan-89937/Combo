from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, TypeVar


RuntimeLocale = Literal["zh-CN", "en-US"]
DEFAULT_RUNTIME_LOCALE: RuntimeLocale = "zh-CN"
SUPPORTED_RUNTIME_LOCALES: tuple[RuntimeLocale, ...] = ("zh-CN", "en-US")

T = TypeVar("T")


def normalize_runtime_locale(value: object) -> RuntimeLocale:
    normalized = str(value or "").strip().lower().replace("_", "-")
    if normalized.startswith("en"):
        return "en-US"
    if normalized.startswith("zh"):
        return "zh-CN"
    return DEFAULT_RUNTIME_LOCALE


def select_localized(values: Mapping[RuntimeLocale, T], locale: object) -> T:
    selected = normalize_runtime_locale(locale)
    if selected in values:
        return values[selected]
    if DEFAULT_RUNTIME_LOCALE in values:
        return values[DEFAULT_RUNTIME_LOCALE]
    raise ValueError("localized values require a supported runtime locale")


@dataclass(frozen=True, slots=True)
class LocalizedText:
    zh_cn: str
    en_us: str

    def __post_init__(self) -> None:
        if not self.zh_cn.strip() or not self.en_us.strip():
            raise ValueError("localized text must provide non-empty Chinese and English values")

    def resolve(self, locale: object) -> str:
        return self.en_us if normalize_runtime_locale(locale) == "en-US" else self.zh_cn
