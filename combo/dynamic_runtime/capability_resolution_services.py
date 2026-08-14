from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json
from math import isfinite
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from combo.dynamic_runtime.capability_adapters import CapabilityRuntimeProjection
from combo.dynamic_runtime.capability_definitions import (
    CapabilityPlatform,
    DependencyDefinition,
    ToolDefinition,
)
from combo.dynamic_runtime.capability_resolution_store import (
    CapabilityResolutionReceiptStore,
)
from combo.dynamic_runtime.capability_resolver import (
    CapabilityCompatibilityResolver,
    CapabilityHealthResolver,
    CapabilityPolicyEvaluator,
    CapabilityResolutionDecision,
    DependencyEnvironmentResolver,
)
from combo.dynamic_runtime.capability_store import ActiveCapability
from combo.dynamic_runtime.model_service import ResolvedRuntimePolicy
from combo.runtime_protocol import (
    CapabilityDependencyRef,
    CapabilityRevision,
    CapabilityRevisionRef,
    CapabilityTrustLevel,
    DependencyEnvironmentRef,
)


@dataclass(frozen=True, slots=True)
class CapabilitySearchConfig:
    maximum_results: int
    minimum_score: float
    reciprocal_rank_constant: int
    lexical_weight: float
    vector_weight: float
    exact_match_bonus: float
    receipt_retention_limit: int

    def __post_init__(self) -> None:
        if self.maximum_results < 1:
            raise ValueError("capability search maximum_results must be positive")
        if self.reciprocal_rank_constant < 1:
            raise ValueError("capability search reciprocal_rank_constant must be positive")
        if self.receipt_retention_limit < 1:
            raise ValueError("capability search receipt_retention_limit must be positive")
        numeric = (self.minimum_score, self.lexical_weight, self.vector_weight, self.exact_match_bonus)
        if any(not isfinite(value) or value < 0 for value in numeric):
            raise ValueError("capability search scores and weights must be finite and non-negative")
        if self.minimum_score > 1:
            raise ValueError("capability search minimum_score cannot exceed 1")
        if self.lexical_weight <= 0 or self.vector_weight <= 0:
            raise ValueError("capability search lexical and vector weights must be positive")


@dataclass(frozen=True, slots=True)
class CapabilityResolutionConfig:
    search: CapabilitySearchConfig
    host_platform: CapabilityPlatform
    host_python_abi: str | None
    allowed_trust_levels: tuple[CapabilityTrustLevel, ...]

    def __post_init__(self) -> None:
        if self.host_platform == "any":
            raise ValueError("capability resolution host_platform must be concrete")
        abi = str(self.host_python_abi or "").strip() or None
        trust_levels = tuple(self.allowed_trust_levels)
        if not trust_levels:
            raise ValueError("capability resolution allowed_trust_levels must not be empty")
        if len(trust_levels) != len(set(trust_levels)):
            raise ValueError("capability resolution allowed_trust_levels must be unique")
        object.__setattr__(self, "host_python_abi", abi)
        object.__setattr__(self, "allowed_trust_levels", trust_levels)


class ActiveCapabilityPolicyEvaluator(CapabilityPolicyEvaluator):
    """Evaluate active revision trust against the frozen principal policy."""

    def __init__(self, *, allowed_trust_levels: tuple[CapabilityTrustLevel, ...]) -> None:
        self._allowed_trust_levels = frozenset(allowed_trust_levels)

    def evaluate(
        self,
        *,
        principal_id: str,
        policy: ResolvedRuntimePolicy,
        capability: ActiveCapability,
        workspace_id: str,
    ) -> CapabilityResolutionDecision:
        revision = capability.revision
        identity = {
            "principal_id": principal_id,
            "workspace_id": workspace_id,
            "policy_id": policy.snapshot.source_policy_id,
            "policy_revision": policy.snapshot.source_policy_revision,
            "activation_revision": capability.activation.activation_revision,
            "capability_id": revision.capability_id,
            "capability_revision": revision.revision,
            "content_digest": revision.content_digest,
            "trust_level": revision.trust_level,
            "allowed_trust_levels": sorted(self._allowed_trust_levels),
        }
        principal_matches = policy.snapshot.principal_id == principal_id
        trust_allowed = revision.trust_level in self._allowed_trust_levels
        allowed = principal_matches and trust_allowed
        if not principal_matches:
            reason = "runtime policy principal does not match capability request principal"
        elif not trust_allowed:
            reason = f"capability trust level is not allowed by the resolution policy: {revision.trust_level}"
        else:
            reason = "active capability revision is allowed by the frozen principal policy"
        return _decision(
            revision,
            allowed=allowed,
            reason=reason,
            evidence_id=_evidence_id("capability-policy", identity),
        )


class PublishedCapabilityCompatibilityResolver(CapabilityCompatibilityResolver):
    """Evaluate platform, modality, kind, and version constraints without I/O."""

    def __init__(self, *, host_platform: CapabilityPlatform, host_python_abi: str | None) -> None:
        self._host_platform = host_platform
        self._host_python_abi = host_python_abi

    def evaluate(
        self,
        *,
        policy: ResolvedRuntimePolicy,
        capability: CapabilityRevision,
        workspace_id: str,
    ) -> CapabilityResolutionDecision:
        allowed = True
        reason = "capability is compatible with the frozen model and host platform"
        details: dict[str, object] = {
            "workspace_id": workspace_id,
            "host_platform": self._host_platform,
            "host_python_abi": self._host_python_abi,
            "model_input_modalities": sorted(policy.chat_model.input_modalities),
        }
        if capability.kind == "tool":
            tool = ToolDefinition.model_validate(capability.content.definition)
            platform_allowed = "any" in tool.platforms or self._host_platform in tool.platforms
            missing_modalities = sorted(
                set(tool.required_input_modalities) - set(policy.chat_model.input_modalities)
            )
            details.update(
                {
                    "declared_platforms": list(tool.platforms),
                    "required_input_modalities": list(tool.required_input_modalities),
                    "missing_input_modalities": missing_modalities,
                }
            )
            if not platform_allowed:
                allowed = False
                reason = "tool capability does not support the current host platform"
            elif missing_modalities:
                allowed = False
                reason = "tool capability requires unsupported model input modalities"
        elif capability.kind == "dependency":
            dependency = DependencyDefinition.model_validate(capability.content.definition)
            details.update(
                {
                    "declared_platform": dependency.platform,
                    "declared_python_abi": dependency.python_abi,
                }
            )
            if dependency.platform not in {"any", self._host_platform}:
                allowed = False
                reason = "dependency capability does not support the current host platform"
            elif (
                dependency.python_abi is not None
                and dependency.python_abi != self._host_python_abi
            ):
                allowed = False
                reason = "dependency capability requires a different Python ABI"
        return _decision(
            capability,
            allowed=allowed,
            reason=reason,
            evidence_id=_evidence_id(
                "capability-compatibility",
                {
                    "capability_id": capability.capability_id,
                    "revision": capability.revision,
                    "content_digest": capability.content_digest,
                    **details,
                },
            ),
        )

    def dependency_satisfies(
        self,
        *,
        dependency: CapabilityDependencyRef,
        capability: CapabilityRevision,
    ) -> CapabilityResolutionDecision:
        kind_matches = dependency.kind == capability.kind
        version_matches, version_reason = _version_satisfies(
            capability.resolved_version,
            dependency.version_constraint,
        )
        allowed = kind_matches and version_matches
        reason = (
            "dependency kind and version constraint are satisfied"
            if allowed
            else (
                "dependency kind differs from published capability kind"
                if not kind_matches
                else version_reason
            )
        )
        return _decision(
            capability,
            allowed=allowed,
            reason=reason,
            evidence_id=_evidence_id(
                "capability-dependency",
                {
                    "dependency": dependency.model_dump(mode="json"),
                    "capability_id": capability.capability_id,
                    "kind": capability.kind,
                    "resolved_version": capability.resolved_version,
                    "revision": capability.revision,
                    "content_digest": capability.content_digest,
                },
            ),
        )


class ReceiptBackedCapabilityHealthResolver(CapabilityHealthResolver):
    def __init__(self, store: CapabilityResolutionReceiptStore) -> None:
        self._store = store

    def current(self, *, capability: CapabilityRevision) -> CapabilityResolutionDecision:
        receipt = self._store.latest_health(
            capability_id=capability.capability_id,
            revision=capability.revision,
            content_digest=capability.content_digest,
        )
        if receipt is None:
            return _decision(
                capability,
                allowed=False,
                reason="capability revision has no health receipt",
                evidence_id=_evidence_id(
                    "capability-health-missing",
                    _revision_identity(capability),
                ),
            )
        expired = receipt.valid_until is not None and _parse_utc(receipt.valid_until) <= datetime.now(UTC)
        allowed = receipt.status == "healthy" and not expired
        reason = (
            "capability health receipt is current and healthy"
            if allowed
            else (
                "capability health receipt has expired"
                if expired
                else "capability health receipt reports unhealthy"
            )
        )
        return _decision(
            capability,
            allowed=allowed,
            reason=reason,
            evidence_id=receipt.receipt_id,
        )


class ReceiptBackedDependencyEnvironmentResolver(DependencyEnvironmentResolver):
    def __init__(self, store: CapabilityResolutionReceiptStore) -> None:
        self._store = store

    def current(
        self,
        *,
        dependencies: tuple[CapabilityRevision, ...],
        projections: tuple[CapabilityRuntimeProjection, ...],
    ) -> DependencyEnvironmentRef | None:
        if not dependencies:
            return None
        refs = tuple(
            CapabilityRevisionRef(
                capability_id=item.capability_id,
                kind=item.kind,
                resolved_version=item.resolved_version,
                revision=item.revision,
                content_digest=item.content_digest,
            )
            for item in sorted(
                dependencies,
                key=lambda item: (item.capability_id, item.revision, item.content_digest),
            )
        )
        closure_digest = _canonical_digest(
            [item.model_dump(mode="json") for item in refs]
        )
        dependency_projection_payload = [
            item.model_dump(mode="json")
            for item in sorted(
                (item for item in projections if item.kind == "dependency"),
                key=lambda item: item.capability_id,
            )
        ]
        projection_digest = _canonical_digest(dependency_projection_payload)
        receipt = self._store.latest_environment(
            dependency_closure_digest=closure_digest,
            projection_digest=projection_digest,
        )
        if receipt is None or receipt.status != "ready":
            return None
        if tuple(
            sorted(
                receipt.environment.capability_refs,
                key=lambda item: (item.capability_id, item.revision, item.content_digest),
            )
        ) != refs:
            raise RuntimeError("dependency environment receipt references differ from selected revisions")
        return receipt.environment


def _version_satisfies(resolved_version: str, constraint: str) -> tuple[bool, str]:
    normalized = str(constraint or "").strip()
    if normalized == "*":
        return True, "dependency accepts every published version"
    if normalized.startswith("==="):
        expected = normalized[3:]
        if not expected:
            return False, "arbitrary exact dependency version must not be empty"
        if str(resolved_version or "").strip() == expected:
            return True, "arbitrary exact dependency version is satisfied"
        return False, "published capability version differs from the required exact version"
    try:
        specifier = SpecifierSet(normalized)
        version = Version(str(resolved_version or "").strip())
    except (InvalidSpecifier, InvalidVersion):
        return False, "dependency version or constraint is not a valid PEP 440 value"
    if version in specifier:
        return True, "dependency version constraint is satisfied"
    return False, "published capability version does not satisfy dependency constraint"


def _decision(
    revision: CapabilityRevision,
    *,
    allowed: bool,
    reason: str,
    evidence_id: str,
) -> CapabilityResolutionDecision:
    return CapabilityResolutionDecision(
        capability_id=revision.capability_id,
        revision=revision.revision,
        content_digest=revision.content_digest,
        allowed=allowed,
        reason=reason,
        evidence_id=evidence_id,
    )


def _revision_identity(revision: CapabilityRevision) -> dict[str, object]:
    return {
        "capability_id": revision.capability_id,
        "kind": revision.kind,
        "revision": revision.revision,
        "content_digest": revision.content_digest,
    }


def _evidence_id(domain: str, payload: object) -> str:
    return f"{domain}:{_canonical_digest(payload)}"


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("capability health valid_until must include a timezone")
    return parsed.astimezone(UTC)
