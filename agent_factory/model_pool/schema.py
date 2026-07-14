from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_factory.models.protocol import ModelReasoningSettings, StructuredOutputMethod


ModelPoolProfileKind = Literal["chat", "embedding"]
ModelBindingRole = Literal["main", "task", "compression"]
ModelPoolDefaultRole = Literal["main", "task", "compression", "embedding"]
ModelBindingSource = Literal["local_registry", "local_default"]
ModelPoolModality = Literal["text", "image", "audio"]
ModelToolCapability = Literal["image_input", "audio_input"]
ModelSelectionSource = Literal["auto", "manual"]
ModelSelectionOptimizeFor = Literal["balanced", "quality", "latency", "context"]
LocalInferenceEngine = Literal["llama_cpp_rocm", "transformers_rocm"]

_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{1,127}$")
_TOOL_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def utc_now_text() -> str:
    return datetime.now(UTC).isoformat()


class LocalModelArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: str
    display_name: str
    kind: ModelPoolProfileKind
    local_path: str
    model_format: str = "transformers"
    revision: str = ""
    checksum: str = ""
    license: str = ""
    enabled: bool = True
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = Field(default_factory=utc_now_text)

    @field_validator("artifact_id")
    @classmethod
    def _artifact_id(cls, value: str) -> str:
        return validate_pool_id(value, field_name="artifact_id")

    @field_validator("display_name", "model_format")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("value must not be empty")
        return text

    @field_validator("local_path")
    @classmethod
    def _local_path(cls, value: str) -> str:
        text = str(value or "").strip()
        path = Path(text).expanduser()
        if not text or not path.is_absolute():
            raise ValueError("local_path must be an absolute path")
        return str(path)

    @field_validator("revision", "checksum", "license")
    @classmethod
    def _optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return str(value).strip()

    def resolved_path(self) -> Path:
        return Path(self.local_path).expanduser().resolve()


class ModelPoolCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_modalities: list[ModelPoolModality] = Field(default_factory=lambda: ["text"])
    output_modalities: list[ModelPoolModality] = Field(default_factory=lambda: ["text"])
    tool_calling: bool = True
    streaming_tool_calls: bool = False
    strict_tool_schema: bool = False
    structured_output_methods: list[StructuredOutputMethod] = Field(
        default_factory=lambda: ["function_calling", "json_mode"]
    )
    reasoning_supported: bool = False
    reasoning_efforts: list[str] = Field(default_factory=list)
    reasoning_content: bool = False
    cache_usage: bool = False

    @field_validator("input_modalities", "output_modalities", "structured_output_methods", "reasoning_efforts")
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


class ModelPoolLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_input_tokens: int | None = Field(default=None, ge=1)
    max_output_tokens: int | None = Field(default=None, ge=1)
    timeout_seconds: float | None = Field(default=None, gt=0)
    context_compression_threshold_tokens: int | None = Field(default=None, ge=1000)


class LlamaCppInferenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gpu_layers: int = Field(default=99, ge=0)
    parallel_slots: int = Field(default=1, ge=1)
    cache_type_k: str = "f16"
    cache_type_v: str = "f16"
    flash_attention: bool = True

    @field_validator("cache_type_k", "cache_type_v")
    @classmethod
    def _cache_type(cls, value: str) -> str:
        text = str(value or "").strip().lower()
        supported = {"f16", "bf16", "q8_0", "q4_0"}
        if text not in supported:
            raise ValueError(f"cache type must be one of: {', '.join(sorted(supported))}")
        return text


class TransformersInferenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trust_remote_code: bool = False


LocalInferenceConfig = LlamaCppInferenceConfig | TransformersInferenceConfig


class ModelPoolProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    display_name: str
    kind: ModelPoolProfileKind = "chat"
    artifact_id: str
    engine: LocalInferenceEngine
    served_model_name: str
    enabled: bool = True
    capabilities: ModelPoolCapabilities = Field(default_factory=ModelPoolCapabilities)
    limits: ModelPoolLimits = Field(default_factory=ModelPoolLimits)
    inference: LocalInferenceConfig
    embedding_dimensions: int | None = Field(default=None, ge=1)
    normalize_embeddings: bool = True
    notes: str = ""
    created_at: str = Field(default_factory=utc_now_text)
    updated_at: str = Field(default_factory=utc_now_text)

    @field_validator("profile_id", "artifact_id")
    @classmethod
    def _ids(cls, value: str) -> str:
        return validate_pool_id(value, field_name="id")

    @field_validator("display_name", "served_model_name")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("value must not be empty")
        return text

    @model_validator(mode="after")
    def _engine_matches_kind(self) -> "ModelPoolProfile":
        if self.kind == "chat":
            if self.engine != "llama_cpp_rocm":
                raise ValueError("chat profiles require engine=llama_cpp_rocm")
            if not isinstance(self.inference, LlamaCppInferenceConfig):
                raise ValueError("chat profiles require llama.cpp inference settings")
        if self.kind == "embedding":
            if self.engine != "transformers_rocm":
                raise ValueError("embedding profiles require engine=transformers_rocm")
            if not isinstance(self.inference, TransformersInferenceConfig):
                raise ValueError("embedding profiles require Transformers inference settings")
            if self.embedding_dimensions is None:
                raise ValueError("embedding profiles require embedding_dimensions")
        return self

    @property
    def model_name(self) -> str:
        return self.served_model_name

    def to_public(self, artifact: LocalModelArtifact | None = None) -> "ModelPoolProfilePublic":
        return ModelPoolProfilePublic(
            **self.model_dump(mode="json"),
            artifact=artifact,
        )


class ModelPoolProfilePublic(ModelPoolProfile):
    artifact: LocalModelArtifact | None = None


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


class ModelSelectionRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: ModelBindingRole
    profile_id: str
    display_name: str
    engine: LocalInferenceEngine
    model_name: str
    score: float
    selection_source: ModelSelectionSource = "auto"
    reason: str = ""
    required_capabilities: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ModelToolSelectionRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    capability: ModelToolCapability
    purpose: str = ""
    min_context_window_tokens: int | None = Field(default=None, ge=1)
    excluded_profile_ids: list[str] = Field(default_factory=list)
    optimize_for: ModelSelectionOptimizeFor = "balanced"
    max_candidates: int = Field(default=5, ge=1, le=20)

    @field_validator("tool_id")
    @classmethod
    def _tool_id(cls, value: str) -> str:
        tool_id = str(value or "").strip()
        if not _TOOL_ID_RE.fullmatch(tool_id):
            raise ValueError("tool_id must be snake_case")
        return tool_id

    def as_model_requirement(self) -> ModelSelectionRequirement:
        modality = "image" if self.capability == "image_input" else "audio"
        return ModelSelectionRequirement(
            role="task",
            purpose=self.purpose,
            kind="chat",
            input_modalities=[modality],
            output_modalities=["text"],
            min_context_window_tokens=self.min_context_window_tokens,
            excluded_profile_ids=self.excluded_profile_ids,
            optimize_for=self.optimize_for,
            max_candidates=self.max_candidates,
        )


class ModelToolSelectionRecommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_id: str
    capability: ModelToolCapability
    profile_id: str
    display_name: str
    engine: LocalInferenceEngine
    model_name: str
    score: float
    selection_source: ModelSelectionSource = "auto"
    reason: str = ""
    required_capabilities: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ModelSelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requirements: list[ModelSelectionRequirement] = Field(default_factory=list)
    tool_requirements: list[ModelToolSelectionRequirement] = Field(default_factory=list)


class ModelSelectionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "blocked"] = "completed"
    recommendations: list[ModelSelectionRecommendation] = Field(default_factory=list)
    tool_recommendations: list[ModelToolSelectionRecommendation] = Field(default_factory=list)
    unmatched: list[dict[str, Any]] = Field(default_factory=list)
    profile_count: int = 0
    enabled_profile_count: int = 0


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

    profile_id: str | None = None
    source: ModelBindingSource = "local_registry"
    selection_source: ModelSelectionSource = "auto"
    reason: str = ""
    required_capabilities: dict[str, Any] = Field(default_factory=dict)
    overrides: ModelBindingRuntimeOverrides = Field(default_factory=ModelBindingRuntimeOverrides)

    @field_validator("profile_id")
    @classmethod
    def _profile_id(cls, value: str | None) -> str | None:
        return validate_pool_id(value, field_name="profile_id") if value is not None else None

    @model_validator(mode="after")
    def _source_requirements(self) -> "ModelProfileBinding":
        if self.source == "local_registry" and not self.profile_id:
            raise ValueError("local_registry bindings require profile_id")
        if self.source == "local_default" and self.profile_id:
            raise ValueError("local_default bindings must not define profile_id")
        return self


class ModelToolBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str | None = None
    source: ModelBindingSource = "local_registry"
    capability: ModelToolCapability
    selection_source: ModelSelectionSource = "auto"
    reason: str = ""
    required_capabilities: dict[str, Any] = Field(default_factory=dict)
    overrides: ModelBindingRuntimeOverrides = Field(default_factory=ModelBindingRuntimeOverrides)
    description: str = ""

    @field_validator("profile_id")
    @classmethod
    def _profile_id(cls, value: str | None) -> str | None:
        return validate_pool_id(value, field_name="profile_id") if value is not None else None

    @model_validator(mode="after")
    def _source_requirements(self) -> "ModelToolBinding":
        if self.source == "local_registry" and not self.profile_id:
            raise ValueError("local_registry bindings require profile_id")
        if self.source == "local_default" and self.profile_id:
            raise ValueError("local_default bindings must not define profile_id")
        return self


def validate_pool_id(value: str, *, field_name: str) -> str:
    text = str(value or "").strip().lower()
    if not _ID_RE.fullmatch(text):
        raise ValueError(
            f"{field_name} must start with a lowercase letter and contain lowercase letters, digits, _, ., or -"
        )
    return text
