from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ContextSourceId = Literal[
    "cross_session_memory",
    "resources",
    "artifacts",
    "scheduler",
    "knowledge",
    "trace",
]
ContextCandidateKind = Literal[
    "memory",
    "resource",
    "artifact",
    "scheduler",
    "knowledge",
    "trace",
]
ContextEventStatus = Literal["started", "completed", "failed", "skipped"]


class CompressionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    trigger_token_threshold: int = Field(default=200000, ge=1000)
    keep_recent_messages: int = Field(default=12, ge=2, le=128)


class RetrievalPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    source_ids: list[ContextSourceId] = Field(
        default_factory=lambda: [
            "cross_session_memory",
            "resources",
            "scheduler",
        ]
    )
    max_candidates: int = Field(default=24, ge=1, le=128)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)

    @field_validator("source_ids")
    @classmethod
    def _dedupe_sources(cls, value: list[ContextSourceId]) -> list[ContextSourceId]:
        result: list[ContextSourceId] = []
        seen: set[str] = set()
        for item in value:
            if item not in seen:
                result.append(item)
                seen.add(item)
        return result


class AssemblyPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_items_total: int = Field(default=8, ge=1, le=64)
    max_tokens_total: int = Field(default=1200, ge=100, le=32000)
    per_source_limits: dict[str, int] = Field(
        default_factory=lambda: {
            "cross_session_memory": 4,
            "resources": 4,
            "scheduler": 3,
            "artifacts": 3,
            "knowledge": 6,
            "trace": 3,
        }
    )


class ContextPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["context_policy.v0"] = "context_policy.v0"
    compression: CompressionPolicy = Field(default_factory=CompressionPolicy)
    retrieval: RetrievalPolicy = Field(default_factory=RetrievalPolicy)
    assembly: AssemblyPolicy = Field(default_factory=AssemblyPolicy)


class ContextContractConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["context_system.v0"] = "context_system.v0"
    enabled: bool = True
    default_policy: ContextPolicy = Field(default_factory=ContextPolicy)
    node_policies: dict[str, ContextPolicy] = Field(default_factory=dict)

    @field_validator("node_policies")
    @classmethod
    def _node_ids_not_empty(cls, value: dict[str, ContextPolicy]) -> dict[str, ContextPolicy]:
        for node_id in value:
            if not str(node_id).strip():
                raise ValueError("node_policies keys must not be empty")
        return value


class ContextQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    impl: str
    text: str = ""
    user_input: str | None = None


class ContextCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    source_id: str
    kind: ContextCandidateKind
    content: str
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    token_estimate: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LLMContextFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["llm_context_frame.v0"] = "llm_context_frame.v0"
    node_id: str
    query: str
    items: list[ContextCandidate] = Field(default_factory=list)
    token_estimate: int = 0
    text: str = ""


class ContextCompressionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ContextEventStatus
    node_id: str | None = None
    original_message_count: int = 0
    compressed_message_count: int = 0
    token_estimate_before: int = 0
    token_estimate_after: int = 0
    token_count_method: str | None = None
    token_count_error: str | None = None
    summary_token_estimate: int = 0
    error: str | None = None
    duration_ms: int = 0


class ContextRetrievalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ContextEventStatus
    node_id: str | None = None
    source_counts: dict[str, int] = Field(default_factory=dict)
    candidate_count: int = 0
    selected_count: int = 0
    token_estimate: int = 0
    error: str | None = None
    duration_ms: int = 0


class ContextInjectionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ContextEventStatus
    node_id: str | None = None
    item_count: int = 0
    token_estimate: int = 0
    error: str | None = None
    duration_ms: int = 0
