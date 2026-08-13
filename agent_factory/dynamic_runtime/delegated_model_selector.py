from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, field_validator

from agent_factory.model_pool import (
    ModelPoolProfile,
    ModelPoolStore,
)
from agent_factory.model_pool.resolver import resolve_available_chat_model
from agent_factory.models.embedding_model import resolve_embedding_model_profile
from agent_factory.runtime_kernel.model_operations import prepare_structured_output_invocation


DelegatedModelSelectionSource = Literal["task_model", "hybrid", "keyword", "inherited"]


@dataclass(frozen=True, slots=True)
class DelegatedModelSelection:
    profile_id: str
    source: DelegatedModelSelectionSource
    reason: str


class _TaskModelDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    reason: str

    @field_validator("profile_id", "reason")
    @classmethod
    def _required_text(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("model selection values must not be empty")
        return text


class DelegatedTaskModelSelector:
    """Select a frozen child model through task-model judgment with semantic fallbacks."""

    def __init__(self, store: ModelPoolStore) -> None:
        self._store = store

    def select(
        self,
        *,
        task_description: str,
        strategy: str,
        fallback_profile_id: str,
    ) -> DelegatedModelSelection:
        candidates = [
            profile
            for profile in self._store.list_profiles()
            if profile.enabled and profile.kind == "chat"
        ]
        if not candidates:
            return DelegatedModelSelection(
                profile_id=fallback_profile_id,
                source="inherited",
                reason="No enabled chat model profile is available for delegated model selection.",
            )

        task_model_selection = self._select_with_task_model(task_description, strategy, candidates)
        if task_model_selection is not None:
            return task_model_selection

        return self._select_with_semantic_fallback(task_description, candidates)

    def _select_with_task_model(
        self,
        task_description: str,
        strategy: str,
        candidates: list[ModelPoolProfile],
    ) -> DelegatedModelSelection | None:
        resolved = resolve_available_chat_model("task", store=self._store)
        if resolved is None:
            return None
        candidate_payload = [_candidate_payload(profile) for profile in candidates]
        try:
            invocation = prepare_structured_output_invocation(
                model=resolved.model,
                output_model=_TaskModelDecision,
                messages=[
                    SystemMessage(
                        content=(
                            "Select exactly one model profile for the delegated task. Evaluate the complete "
                            "task description against each candidate's declared description, notes, capabilities, "
                            "limits, and pricing. Return only a profile_id present in the supplied candidates and "
                            "a concise factual reason. Do not invent identifiers."
                        )
                    ),
                    HumanMessage(
                        content=json.dumps(
                            {
                                "task_description": task_description,
                                "execution_strategy": strategy,
                                "candidates": candidate_payload,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                    ),
                ],
                model_metadata=resolved.settings.metadata(),
                config_tags=["delegated-model-selection"],
            )
            raw = invocation.model.invoke(
                list(invocation.messages),
                config={
                    "metadata": {
                        "operation": "delegated_model_selection",
                        "task_model_profile_id": resolved.profile_id,
                    }
                },
            )
            decision = raw if isinstance(raw, _TaskModelDecision) else _TaskModelDecision.model_validate(raw)
        except Exception:
            return None
        allowed_ids = {profile.profile_id for profile in candidates}
        if decision.profile_id not in allowed_ids:
            return None
        return DelegatedModelSelection(
            profile_id=decision.profile_id,
            source="task_model",
            reason=decision.reason,
        )

    def _select_with_semantic_fallback(
        self,
        task_description: str,
        candidates: list[ModelPoolProfile],
    ) -> DelegatedModelSelection:
        keyword_scores = [
            _keyword_similarity(task_description, _candidate_document(profile))
            for profile in candidates
        ]
        profile_id = self._store.embedding_binding()
        if not profile_id:
            return _highest_scoring_selection(candidates, keyword_scores, source="keyword")
        try:
            embedding = resolve_embedding_model_profile(profile_id, store=self._store)
            documents = [_candidate_document(profile) for profile in candidates]
            task_vector = [float(value) for value in embedding.model.embed_query(task_description)]
            document_vectors = [
                [float(value) for value in vector]
                for vector in embedding.model.embed_documents(documents)
            ]
            embedding_scores = [_cosine_similarity(task_vector, vector) for vector in document_vectors]
        except Exception:
            return _highest_scoring_selection(candidates, keyword_scores, source="keyword")
        if not embedding_scores or len(embedding_scores) != len(candidates):
            return _highest_scoring_selection(candidates, keyword_scores, source="keyword")
        hybrid_scores = [
            (((embedding_score + 1.0) / 2.0) + keyword_score) / 2.0
            for embedding_score, keyword_score in zip(embedding_scores, keyword_scores, strict=True)
        ]
        return _highest_scoring_selection(
            candidates,
            hybrid_scores,
            source="hybrid",
        )


def _candidate_payload(profile: ModelPoolProfile) -> dict[str, object]:
    return {
        "profile_id": profile.profile_id,
        "display_name": profile.display_name,
        "model_name": profile.model_name,
        "provider": profile.provider,
        "description": profile.description,
        "notes": profile.notes,
        "capabilities": profile.capabilities.model_dump(mode="json"),
        "limits": profile.limits.model_dump(mode="json"),
        "pricing": profile.pricing.model_dump(mode="json"),
    }


def _candidate_document(profile: ModelPoolProfile) -> str:
    return json.dumps(_candidate_payload(profile), ensure_ascii=False, sort_keys=True)


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        raise ValueError("embedding vectors must have equal non-zero dimensions")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)


def _keyword_similarity(query: str, document: str) -> float:
    query_terms = _semantic_terms(query)
    if not query_terms:
        return 0.0
    return len(query_terms & _semantic_terms(document)) / len(query_terms)


def _semantic_terms(value: str) -> set[str]:
    normalized = str(value or "").strip().lower()
    latin_terms = set(re.findall(r"[a-z0-9][a-z0-9_+.-]{1,}", normalized))
    cjk_terms = {
        run[index : index + 2]
        for run in re.findall(r"[\u3400-\u9fff]+", normalized)
        for index in range(max(0, len(run) - 1))
    }
    return latin_terms | cjk_terms


def _highest_scoring_selection(
    candidates: list[ModelPoolProfile],
    scores: list[float],
    *,
    source: Literal["hybrid", "keyword"],
) -> DelegatedModelSelection:
    selected_index = max(range(len(scores)), key=lambda index: (scores[index], -index))
    selected = candidates[selected_index]
    label = "embedding and keyword" if source == "hybrid" else "keyword"
    return DelegatedModelSelection(
        profile_id=selected.profile_id,
        source=source,
        reason=f"Highest {label} relevance to the delegated task ({scores[selected_index]:.4f}).",
    )
