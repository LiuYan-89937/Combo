from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent_factory.model_pool.schema import (
    ModelPoolCredential,
    ModelPoolProfile,
    ModelSelectionRecommendation,
    ModelSelectionRequirement,
    ModelSelectionRequest,
    ModelSelectionResult,
    ModelToolSelectionRecommendation,
)
from agent_factory.model_pool.store import ModelPoolStore


@dataclass(frozen=True, slots=True)
class _Candidate:
    profile: ModelPoolProfile
    credential: ModelPoolCredential
    score: float
    reason: str
    warnings: list[str]


class ModelPoolSelector:
    def __init__(self, store: ModelPoolStore | None = None) -> None:
        self.store = store or ModelPoolStore()

    def select(self, request: ModelSelectionRequest) -> ModelSelectionResult:
        profiles = self.store.list_profiles()
        enabled_profiles = [profile for profile in profiles if profile.enabled]
        recommendations: list[ModelSelectionRecommendation] = []
        tool_recommendations: list[ModelToolSelectionRecommendation] = []
        unmatched: list[dict[str, Any]] = []
        for requirement in request.requirements:
            candidates = self._rank_candidates(requirement, enabled_profiles)
            if not candidates:
                unmatched.append(
                    {
                        "role": requirement.role,
                        "purpose": requirement.purpose,
                        "required_capabilities": _requirement_payload(requirement),
                        "reason": "No enabled model profile matches the required capabilities.",
                    }
                )
                continue
            selected = candidates[0]
            recommendations.append(
                ModelSelectionRecommendation(
                    role=requirement.role,
                    profile_id=selected.profile.profile_id,
                    display_name=selected.profile.display_name,
                    provider=selected.profile.provider,
                    model_name=selected.profile.model_name,
                    score=round(selected.score, 6),
                    reason=selected.reason,
                    required_capabilities=_requirement_payload(requirement),
                    warnings=selected.warnings,
                )
            )
        for requirement in request.tool_requirements:
            model_requirement = requirement.as_model_requirement()
            candidates = self._rank_candidates(model_requirement, enabled_profiles)
            if not candidates:
                unmatched.append(
                    {
                        "tool_id": requirement.tool_id,
                        "capability": requirement.capability,
                        "purpose": requirement.purpose,
                        "required_capabilities": _requirement_payload(model_requirement),
                        "reason": "No enabled model profile matches the required auxiliary model tool capability.",
                    }
                )
                continue
            selected = candidates[0]
            tool_recommendations.append(
                ModelToolSelectionRecommendation(
                    tool_id=requirement.tool_id,
                    capability=requirement.capability,
                    profile_id=selected.profile.profile_id,
                    display_name=selected.profile.display_name,
                    provider=selected.profile.provider,
                    model_name=selected.profile.model_name,
                    score=round(selected.score, 6),
                    reason=selected.reason,
                    required_capabilities=_requirement_payload(model_requirement),
                    warnings=selected.warnings,
                )
            )
        return ModelSelectionResult(
            status="blocked" if unmatched else "completed",
            recommendations=recommendations,
            tool_recommendations=tool_recommendations,
            unmatched=unmatched,
            profile_count=len(profiles),
            enabled_profile_count=len(enabled_profiles),
        )

    def _rank_candidates(
        self,
        requirement: ModelSelectionRequirement,
        profiles: list[ModelPoolProfile],
    ) -> list[_Candidate]:
        candidates: list[_Candidate] = []
        excluded = set(requirement.excluded_profile_ids)
        for profile in profiles:
            if profile.profile_id in excluded:
                continue
            if requirement.kind and profile.kind != requirement.kind:
                continue
            credential = self.store.get_credential(profile.credential_id)
            if credential is None or not credential.enabled or not credential.api_key:
                continue
            missing = _missing_capabilities(requirement, profile)
            if missing:
                continue
            score = _score_profile(requirement, profile)
            reason = _selection_reason(requirement, profile)
            warnings = _candidate_warnings(requirement, profile)
            candidates.append(_Candidate(profile=profile, credential=credential, score=score, reason=reason, warnings=warnings))
        return sorted(candidates, key=lambda item: (-item.score, item.profile.profile_id))


def _missing_capabilities(requirement: ModelSelectionRequirement, profile: ModelPoolProfile) -> list[str]:
    capabilities = profile.capabilities
    missing: list[str] = []
    inputs = set(capabilities.input_modalities)
    outputs = set(capabilities.output_modalities)
    for item in requirement.input_modalities:
        if item not in inputs:
            missing.append(f"input:{item}")
    for item in requirement.output_modalities:
        if item not in outputs:
            missing.append(f"output:{item}")
    if requirement.tool_calling is True and not capabilities.tool_calling:
        missing.append("tool_calling")
    if requirement.reasoning_required is True and not capabilities.reasoning_supported:
        missing.append("reasoning")
    if requirement.structured_output_methods:
        supported = set(capabilities.structured_output_methods)
        if not any(method in supported for method in requirement.structured_output_methods):
            missing.append("structured_output")
    if requirement.min_context_window_tokens:
        limit = profile.limits.max_input_tokens
        if limit is None or limit < requirement.min_context_window_tokens:
            missing.append("context_window")
    return missing


def _score_profile(requirement: ModelSelectionRequirement, profile: ModelPoolProfile) -> float:
    score = 0.5
    if requirement.tool_calling is True and profile.capabilities.tool_calling:
        score += 0.08
    if requirement.reasoning_required is True and profile.capabilities.reasoning_supported:
        score += 0.08
    if requirement.min_context_window_tokens and profile.limits.max_input_tokens:
        ratio = min(profile.limits.max_input_tokens / requirement.min_context_window_tokens, 4.0)
        score += 0.04 * ratio
    if requirement.optimize_for == "context" and profile.limits.max_input_tokens:
        score += min(profile.limits.max_input_tokens / 1_000_000, 1.0) * 0.2
    if requirement.optimize_for == "cost":
        score += _cost_score(profile)
    if requirement.optimize_for == "quality":
        score += 0.04 * len(profile.capabilities.structured_output_methods)
        if profile.capabilities.strict_tool_schema:
            score += 0.05
    if requirement.optimize_for == "latency" and profile.limits.timeout_seconds:
        score += max(0.0, 0.12 - min(profile.limits.timeout_seconds, 120.0) / 1000.0)
    return score


def _cost_score(profile: ModelPoolProfile) -> float:
    input_price = profile.pricing.input_per_1m_tokens
    output_price = profile.pricing.output_per_1m_tokens
    if input_price is None and output_price is None:
        return 0.0
    total = float(input_price or 0.0) + float(output_price or 0.0)
    return max(0.0, 0.2 - min(total, 20.0) / 100.0)


def _selection_reason(requirement: ModelSelectionRequirement, profile: ModelPoolProfile) -> str:
    parts = [f"Selected {profile.display_name} for {requirement.role}."]
    if requirement.purpose:
        parts.append(requirement.purpose)
    if requirement.input_modalities:
        parts.append("Required inputs: " + ", ".join(requirement.input_modalities) + ".")
    if requirement.tool_calling:
        parts.append("Tool calling is required.")
    if requirement.reasoning_required:
        parts.append("Reasoning support is required.")
    return " ".join(parts)


def _candidate_warnings(requirement: ModelSelectionRequirement, profile: ModelPoolProfile) -> list[str]:
    warnings: list[str] = []
    if requirement.structured_output_methods and not profile.capabilities.strict_tool_schema:
        warnings.append("Profile does not advertise strict tool schema support.")
    if profile.pricing.input_per_1m_tokens is None or profile.pricing.output_per_1m_tokens is None:
        warnings.append("Pricing is incomplete, so cost ranking is approximate.")
    return warnings


def _requirement_payload(requirement: ModelSelectionRequirement) -> dict[str, Any]:
    return requirement.model_dump(mode="json", exclude_none=True)
