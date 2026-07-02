from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_factory.models.capabilities import resolve_provider_profile
from agent_factory.models.protocol import ModelReasoningSettings, StructuredOutputMethod


ModelPoolProfileKind = Literal["chat"]
ModelBindingRole = Literal["main", "task", "compression"]
ModelPoolModality = Literal["text", "image", "audio"]
ModelSelectionSource = Literal["auto", "manual"]
ModelSelectionOptimizeFor = Literal["balanced", "quality", "cost", "latency", "context"]

_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")


def utc_now_text() -> str:
    return datetime.now(UTC).isoformat()


class ModelPoolCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_modalities: list[ModelPoolModality] = Field(default_factory=lambda: ["text"])
    output_modalities: list[ModelPoolModality] = Field(default_factory=lambda: ["text"])
    tool_calling: bool = True
    streaming_tool_calls: bool = False
    strict_tool_schema: bool = False
    structured_output_methods: list[StructuredOutputMethod] = Field(default_factory=lambda: ["json_mode"])
    reasoning_supported: bool = False
    reasoning_efforts: list[str] = Field(default_factory=list)
    reasoning_content: bool = False
    cache_usage: bool = False

    @field_validator("input_modalities", "output_modalities", "structured_output_methods", "reasoning_efforts")
    @classmethod
    def _stable_non_empty_strings(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item or "").strip().lower()
            if text and text not in seen:
                result.append(text)
                seen.add(text)
        return result


class ModelPoolLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_input_tokens: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    timeout_seconds: float | None = Field(default=None, gt=0)
    requests_per_minute: int | None = Field(default=None, ge=1)
    tokens_per_minute: int | None = Field(default=None, ge=1)


class ModelPoolPricing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: str = "CNY"
    input_per_1m_tokens: float | None = Field(default=None, ge=0)
    output_per_1m_tokens: float | None = Field(default=None, ge=0)
    cache_hit_per_1m_tokens: float | None = Field(default=None, ge=0)
    reasoning_per_1m_tokens: float | None = Field(default=None, ge=0)
    image_input_unit_price: float | None = Field(default=None, ge=0)
    image_output_unit_price: float | None = Field(default=None, ge=0)


class ModelPoolCredential(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential_id: str
    display_name: str
    provider: str
    base_url: str
    api_key: str | None = None
    enabled: bool = True
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = Field(default_factory=utc_now_text)

    @field_validator("credential_id")
    @classmethod
    def _credential_id(cls, value: str) -> str:
        return validate_pool_id(value, field_name="credential_id")

    @field_validator("provider")
    @classmethod
    def _provider(cls, value: str) -> str:
        provider = str(value or "").strip().lower()
        resolve_provider_profile(provider)
        return provider

    @field_validator("display_name", "base_url")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("value must not be empty")
        return text

    @property
    def api_key_fingerprint(self) -> str:
        return api_key_fingerprint(self.api_key)

    def to_public(self) -> "ModelPoolCredentialPublic":
        return ModelPoolCredentialPublic(
            credential_id=self.credential_id,
            display_name=self.display_name,
            provider=self.provider,
            base_url=self.base_url,
            api_key_masked=mask_api_key(self.api_key),
            api_key_fingerprint=self.api_key_fingerprint,
            has_api_key=bool(self.api_key),
            enabled=self.enabled,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class ModelPoolCredentialPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential_id: str
    display_name: str
    provider: str
    base_url: str
    api_key_masked: str = ""
    api_key_fingerprint: str = ""
    has_api_key: bool = False
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""


class ModelPoolProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    display_name: str
    kind: ModelPoolProfileKind = "chat"
    provider: str
    credential_id: str
    model_name: str
    enabled: bool = True
    capabilities: ModelPoolCapabilities = Field(default_factory=ModelPoolCapabilities)
    limits: ModelPoolLimits = Field(default_factory=ModelPoolLimits)
    pricing: ModelPoolPricing = Field(default_factory=ModelPoolPricing)
    notes: str = ""
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = Field(default_factory=utc_now_text)

    @field_validator("profile_id", "credential_id")
    @classmethod
    def _ids(cls, value: str) -> str:
        return validate_pool_id(value, field_name="id")

    @field_validator("provider")
    @classmethod
    def _provider(cls, value: str) -> str:
        provider = str(value or "").strip().lower()
        resolve_provider_profile(provider)
        return provider

    @field_validator("display_name", "model_name")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("value must not be empty")
        return text

    def to_public(self, credential: ModelPoolCredential | None = None) -> "ModelPoolProfilePublic":
        return ModelPoolProfilePublic(
            **self.model_dump(mode="json"),
            credential=credential.to_public() if credential is not None else None,
        )


class ModelPoolProfilePublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    display_name: str
    kind: ModelPoolProfileKind = "chat"
    provider: str
    credential_id: str
    model_name: str
    enabled: bool = True
    capabilities: ModelPoolCapabilities = Field(default_factory=ModelPoolCapabilities)
    limits: ModelPoolLimits = Field(default_factory=ModelPoolLimits)
    pricing: ModelPoolPricing = Field(default_factory=ModelPoolPricing)
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    credential: ModelPoolCredentialPublic | None = None


class ModelSelectionRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: ModelBindingRole
    purpose: str = ""
    kind: ModelPoolProfileKind | None = None
    input_modalities: list[ModelPoolModality] = Field(default_factory=lambda: ["text"])
    output_modalities: list[ModelPoolModality] = Field(default_factory=lambda: ["text"])
    tool_calling: bool | None = None
    structured_output_methods: list[StructuredOutputMethod] = Field(default_factory=list)
    reasoning_required: bool | None = None
    min_context_window_tokens: int | None = Field(default=None, ge=1)
    excluded_profile_ids: list[str] = Field(default_factory=list)
    optimize_for: ModelSelectionOptimizeFor = "balanced"
    max_candidates: int = Field(default=5, ge=1, le=20)

    @field_validator("input_modalities", "output_modalities", "excluded_profile_ids")
    @classmethod
    def _stable_strings(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item or "").strip().lower()
            if text and text not in seen:
                result.append(text)
                seen.add(text)
        return result

    @model_validator(mode="after")
    def _default_kind(self) -> "ModelSelectionRequirement":
        if self.kind is not None:
            return self
        return self.model_copy(update={"kind": "chat"})


class ModelSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirements: list[ModelSelectionRequirement] = Field(default_factory=list)


class ModelSelectionRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: ModelBindingRole
    profile_id: str
    display_name: str
    provider: str
    model_name: str
    score: float
    selection_source: ModelSelectionSource = "auto"
    reason: str = ""
    required_capabilities: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ModelSelectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "blocked"] = "completed"
    recommendations: list[ModelSelectionRecommendation] = Field(default_factory=list)
    unmatched: list[dict[str, Any]] = Field(default_factory=list)
    profile_count: int = 0
    enabled_profile_count: int = 0


def validate_pool_id(value: str, *, field_name: str) -> str:
    text = str(value or "").strip().lower()
    if not _ID_RE.fullmatch(text):
        raise ValueError(f"{field_name} must start with a lowercase letter and contain lowercase letters, digits, _, ., or -")
    return text


def mask_api_key(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "****"
    return f"{text[:4]}...{text[-4:]}"


def api_key_fingerprint(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def provider_default_capabilities(provider: str) -> ModelPoolCapabilities:
    profile = resolve_provider_profile(provider)
    capabilities = profile.capabilities
    input_modalities = ["text"]
    for modality, support in (
        ("image", capabilities.image_input),
        ("audio", capabilities.audio_input),
    ):
        if support != "unsupported":
            input_modalities.append(modality)
    return ModelPoolCapabilities(
        input_modalities=input_modalities,
        output_modalities=["text"],
        tool_calling=capabilities.tool_calling != "unsupported",
        streaming_tool_calls=capabilities.streaming_tool_calls != "unsupported",
        strict_tool_schema=capabilities.strict_tool_schema != "unsupported",
        structured_output_methods=list(capabilities.structured_output_methods),
        reasoning_supported=capabilities.reasoning != "unsupported",
        reasoning_efforts=list(capabilities.reasoning_efforts),
        reasoning_content=capabilities.reasoning_content != "unsupported",
        cache_usage=capabilities.cache_usage != "unsupported",
    )


class ModelBindingRuntimeOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid")

    temperature: float | None = Field(default=None, ge=0)
    timeout_seconds: float | None = Field(default=None, gt=0)
    max_output_tokens: int | None = Field(default=None, ge=1)
    max_input_tokens: int | None = Field(default=None, ge=1)
    multimodal: bool | None = None
    reasoning: ModelReasoningSettings | None = None
    structured_output_method: StructuredOutputMethod | None = None


class ModelProfileBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    selection_source: ModelSelectionSource = "auto"
    reason: str = ""
    required_capabilities: dict[str, Any] = Field(default_factory=dict)
    overrides: ModelBindingRuntimeOverrides = Field(default_factory=ModelBindingRuntimeOverrides)

    @field_validator("profile_id")
    @classmethod
    def _profile_id(cls, value: str) -> str:
        return validate_pool_id(value, field_name="profile_id")
