from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Protocol

from agent_factory.dynamic_runtime.capability_adapters import (
    CapabilityAdapterRegistry,
    CapabilityRuntimeProjection,
)
from agent_factory.dynamic_runtime.capability_store import ActiveCapability, CapabilityStore
from agent_factory.dynamic_runtime.model_service import ResolvedRuntimePolicy
from agent_factory.runtime_protocol import (
    CapabilityDependencyRef,
    CapabilityProjectionSnapshot,
    CapabilityRevision,
    CapabilityRevisionRef,
    CapabilitySelection,
    CapabilitySnapshot,
    CapabilityToolAliasBinding,
    CommandEnvelope,
    DependencyEnvironmentRef,
    RouteDecision,
)


class CapabilityResolutionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CapabilitySearchMatch:
    capability_id: str
    score: float
    reason: str

    def __post_init__(self) -> None:
        _require_text(self.capability_id, "capability search match capability_id")
        if not isfinite(self.score):
            raise ValueError("capability search match score must be finite")
        _require_text(self.reason, "capability search match reason")


@dataclass(frozen=True, slots=True)
class CapabilityResolutionDecision:
    capability_id: str
    revision: int
    content_digest: str
    allowed: bool
    reason: str
    evidence_id: str

    def __post_init__(self) -> None:
        _require_text(self.capability_id, "capability decision capability_id")
        if self.revision < 1:
            raise ValueError("capability decision revision must be positive")
        _require_text(self.content_digest, "capability decision content_digest")
        _require_text(self.reason, "capability decision reason")
        _require_text(self.evidence_id, "capability decision evidence_id")


class CapabilitySearchIndex(Protocol):
    def search(
        self,
        *,
        requirements: tuple[str, ...],
        candidates: tuple[ActiveCapability, ...],
    ) -> tuple[CapabilitySearchMatch, ...]:
        ...


class CapabilityPolicyEvaluator(Protocol):
    def evaluate(
        self,
        *,
        principal_id: str,
        policy: ResolvedRuntimePolicy,
        capability: ActiveCapability,
        workspace_id: str,
    ) -> CapabilityResolutionDecision:
        ...


class CapabilityCompatibilityResolver(Protocol):
    def evaluate(
        self,
        *,
        policy: ResolvedRuntimePolicy,
        capability: CapabilityRevision,
        workspace_id: str,
    ) -> CapabilityResolutionDecision:
        ...

    def dependency_satisfies(
        self,
        *,
        dependency: CapabilityDependencyRef,
        capability: CapabilityRevision,
    ) -> CapabilityResolutionDecision:
        ...


class CapabilityHealthResolver(Protocol):
    def current(self, *, capability: CapabilityRevision) -> CapabilityResolutionDecision:
        """Return an existing health receipt without performing live probing."""
        ...


class DependencyEnvironmentResolver(Protocol):
    def current(
        self,
        *,
        dependencies: tuple[CapabilityRevision, ...],
        projections: tuple[CapabilityRuntimeProjection, ...],
    ) -> DependencyEnvironmentRef | None:
        """Return an already prepared immutable environment pointer."""
        ...


class MainTurnCapabilityResolverProtocol(Protocol):
    async def resolve(
        self,
        *,
        envelope: CommandEnvelope,
        route: RouteDecision,
        policy: ResolvedRuntimePolicy,
        workspace_id: str,
    ) -> CapabilitySnapshot:
        ...


class MainTurnCapabilityResolver:
    """Resolve one immutable capability surface from published authorities only."""

    def __init__(
        self,
        *,
        store: CapabilityStore,
        search_index: CapabilitySearchIndex,
        policy_evaluator: CapabilityPolicyEvaluator,
        compatibility: CapabilityCompatibilityResolver,
        health: CapabilityHealthResolver,
        dependency_environments: DependencyEnvironmentResolver,
        adapters: CapabilityAdapterRegistry,
    ) -> None:
        self._store = store
        self._search_index = search_index
        self._policy_evaluator = policy_evaluator
        self._compatibility = compatibility
        self._health = health
        self._dependency_environments = dependency_environments
        self._adapters = adapters
        self._adapters.require_complete()

    async def resolve(
        self,
        *,
        envelope: CommandEnvelope,
        route: RouteDecision,
        policy: ResolvedRuntimePolicy,
        workspace_id: str,
    ) -> CapabilitySnapshot:
        principal_id = _require_text(envelope.principal_id, "command principal_id")
        resolved_workspace_id = _require_text(workspace_id, "workspace_id")
        if policy.snapshot.principal_id != principal_id:
            raise CapabilityResolutionError("runtime policy principal differs from command principal")

        active = self._store.active_capabilities()
        active_by_id = {item.revision.capability_id: item for item in active}
        if len(active_by_id) != len(active):
            raise CapabilityResolutionError("active capability store returned duplicate capability IDs")
        matches = self._search_index.search(
            requirements=route.capability_requirements,
            candidates=active,
        )
        matches_by_id = _unique_search_matches(matches)

        selected: dict[str, ActiveCapability] = {}
        rejected: dict[str, CapabilitySelection] = {}
        scores: dict[str, float | None] = {}
        reasons: dict[str, str] = {}
        evidence_ids: dict[str, set[str]] = {}
        visiting: list[str] = []
        accepted_roots: set[str] = set()

        def select(capability_id: str, *, score: float | None, reason: str) -> bool:
            if capability_id in selected:
                if score is not None:
                    current = scores.get(capability_id)
                    scores[capability_id] = score if current is None else max(current, score)
                    reasons[capability_id] = reason
                return True
            if capability_id in rejected:
                return False
            active_capability = active_by_id.get(capability_id)
            if active_capability is None:
                raise CapabilityResolutionError(
                    f"capability index returned a capability outside the active store snapshot: {capability_id}"
                )
            if capability_id in visiting:
                cycle_start = visiting.index(capability_id)
                cycle = " -> ".join([*visiting[cycle_start:], capability_id])
                raise CapabilityResolutionError(f"active capability dependency cycle: {cycle}")

            revision = active_capability.revision
            decisions = (
                _verified_decision(
                    self._policy_evaluator.evaluate(
                        principal_id=principal_id,
                        policy=policy,
                        capability=active_capability,
                        workspace_id=resolved_workspace_id,
                    ),
                    revision,
                    owner="policy evaluator",
                ),
                _verified_decision(
                    self._compatibility.evaluate(
                        policy=policy,
                        capability=revision,
                        workspace_id=resolved_workspace_id,
                    ),
                    revision,
                    owner="compatibility resolver",
                ),
                _verified_decision(
                    self._health.current(capability=revision),
                    revision,
                    owner="health resolver",
                ),
            )
            evidence_ids.setdefault(capability_id, set()).update(
                item.evidence_id for item in decisions
            )
            evidence_ids[capability_id].add(active_capability.index_revision.index_revision_id)
            gate = _first_rejection(*decisions)
            if gate is not None:
                rejected[capability_id] = _rejected_selection(
                    revision,
                    gate.reason,
                    score,
                    evidence_ids=evidence_ids[capability_id],
                )
                return False

            visiting.append(capability_id)
            try:
                for dependency in revision.content.dependencies:
                    target = active_by_id.get(dependency.capability_id)
                    if target is None:
                        if dependency.required:
                            rejected[capability_id] = _rejected_selection(
                                revision,
                                f"required dependency is not active: {dependency.capability_id}",
                                score,
                                evidence_ids=evidence_ids[capability_id],
                            )
                            return False
                        continue
                    constraint = _verified_decision(
                        self._compatibility.dependency_satisfies(
                            dependency=dependency,
                            capability=target.revision,
                        ),
                        target.revision,
                        owner="dependency compatibility resolver",
                    )
                    evidence_ids[capability_id].add(constraint.evidence_id)
                    if not constraint.allowed:
                        if dependency.required:
                            rejected[capability_id] = _rejected_selection(
                                revision,
                                f"required dependency rejected: {dependency.capability_id}: {constraint.reason}",
                                score,
                                evidence_ids=evidence_ids[capability_id],
                            )
                            return False
                        continue
                    if not select(
                        dependency.capability_id,
                        score=None,
                        reason=f"required by {capability_id}",
                    ) and dependency.required:
                        rejected[capability_id] = _rejected_selection(
                            revision,
                            f"required dependency unavailable: {dependency.capability_id}",
                            score,
                            evidence_ids=evidence_ids[capability_id],
                        )
                        return False
            finally:
                visiting.pop()

            selected[capability_id] = active_capability
            scores[capability_id] = score
            reasons[capability_id] = reason
            return True

        for match in sorted(matches_by_id.values(), key=lambda item: (-item.score, item.capability_id)):
            if select(match.capability_id, score=match.score, reason=match.reason):
                accepted_roots.add(match.capability_id)

        reachable = _reachable_selected_capabilities(accepted_roots, selected)
        selected = {
            capability_id: capability
            for capability_id, capability in selected.items()
            if capability_id in reachable
        }

        ordered_active = tuple(
            selected[capability_id]
            for capability_id in sorted(
                selected,
                key=lambda item: (
                    selected[item].revision.kind,
                    selected[item].revision.namespace,
                    item,
                ),
            )
        )
        projections = tuple(self._adapters.project(item.revision) for item in ordered_active)
        projection_snapshots = tuple(
            _projection_snapshot(
                projection,
                adapter_id=self._adapters.adapter(projection.kind).adapter_id,
                adapter_revision=self._adapters.adapter(projection.kind).adapter_revision,
            )
            for projection in projections
        )
        tool_ids, tool_aliases = _tool_surface(projections)
        dependency_revisions = tuple(
            item.revision for item in ordered_active if item.revision.kind == "dependency"
        )
        environment = self._dependency_environments.current(
            dependencies=dependency_revisions,
            projections=projections,
        )
        _verify_dependency_environment(environment, dependency_revisions)

        selections = [
            CapabilitySelection(
                capability_id=item.revision.capability_id,
                kind=item.revision.kind,
                status="selected",
                reason=reasons[item.revision.capability_id],
                evidence_ids=tuple(sorted(evidence_ids[item.revision.capability_id])),
                score=scores[item.revision.capability_id],
                resolved=_revision_ref(item.revision),
            )
            for item in ordered_active
        ]
        selections.extend(
            rejected[capability_id]
            for capability_id in sorted(rejected)
            if capability_id not in selected
        )
        return CapabilitySnapshot(
            selections=tuple(selections),
            projections=projection_snapshots,
            tool_ids=tool_ids,
            tool_aliases=tool_aliases,
            dependency_environment=environment,
        )


def _unique_search_matches(
    matches: tuple[CapabilitySearchMatch, ...],
) -> dict[str, CapabilitySearchMatch]:
    unique: dict[str, CapabilitySearchMatch] = {}
    for match in matches:
        previous = unique.get(match.capability_id)
        if previous is not None and previous != match:
            raise CapabilityResolutionError(
                f"capability search index returned conflicting matches: {match.capability_id}"
            )
        unique[match.capability_id] = match
    return unique


def _reachable_selected_capabilities(
    roots: set[str],
    selected: dict[str, ActiveCapability],
) -> set[str]:
    reachable: set[str] = set()
    pending = list(sorted(roots, reverse=True))
    while pending:
        capability_id = pending.pop()
        if capability_id in reachable:
            continue
        capability = selected.get(capability_id)
        if capability is None:
            raise CapabilityResolutionError(
                f"accepted capability root is absent from the selected closure: {capability_id}"
            )
        reachable.add(capability_id)
        pending.extend(
            dependency.capability_id
            for dependency in capability.revision.content.dependencies
            if dependency.capability_id in selected and dependency.capability_id not in reachable
        )
    return reachable


def _verified_decision(
    decision: CapabilityResolutionDecision,
    revision: CapabilityRevision,
    *,
    owner: str,
) -> CapabilityResolutionDecision:
    if (
        decision.capability_id != revision.capability_id
        or decision.revision != revision.revision
        or decision.content_digest != revision.content_digest
    ):
        raise CapabilityResolutionError(f"{owner} returned a decision for a different capability revision")
    return decision


def _first_rejection(
    *decisions: CapabilityResolutionDecision,
) -> CapabilityResolutionDecision | None:
    return next((item for item in decisions if not item.allowed), None)


def _rejected_selection(
    revision: CapabilityRevision,
    reason: str,
    score: float | None,
    *,
    evidence_ids: set[str],
) -> CapabilitySelection:
    return CapabilitySelection(
        capability_id=revision.capability_id,
        kind=revision.kind,
        status="rejected",
        reason=reason,
        evidence_ids=tuple(sorted(evidence_ids)),
        score=score,
    )


def _revision_ref(revision: CapabilityRevision) -> CapabilityRevisionRef:
    return CapabilityRevisionRef(
        capability_id=revision.capability_id,
        kind=revision.kind,
        resolved_version=revision.resolved_version,
        revision=revision.revision,
        content_digest=revision.content_digest,
    )


def _tool_surface(
    projections: tuple[CapabilityRuntimeProjection, ...],
) -> tuple[tuple[str, ...], tuple[CapabilityToolAliasBinding, ...]]:
    tool_ids: list[str] = []
    aliases: dict[str, CapabilityToolAliasBinding] = {}
    for projection in projections:
        if not projection.model_tool_ids:
            continue
        for alias in projection.model_tool_ids:
            owner = aliases.get(alias)
            if owner is not None and owner.capability_id != projection.capability_id:
                raise CapabilityResolutionError(
                    f"model tool alias collision between capability revisions: {alias}"
                )
            binding = CapabilityToolAliasBinding(
                model_alias=alias,
                capability_id=projection.capability_id,
                kind=projection.kind,
                revision=projection.revision,
                content_digest=projection.content_digest,
            )
            aliases[alias] = binding
            tool_ids.append(alias)
    return tuple(tool_ids), tuple(aliases[alias] for alias in tool_ids)


def _projection_snapshot(
    projection: CapabilityRuntimeProjection,
    *,
    adapter_id: str,
    adapter_revision: str,
) -> CapabilityProjectionSnapshot:
    return CapabilityProjectionSnapshot(
        capability_id=projection.capability_id,
        kind=projection.kind,
        revision=projection.revision,
        content_digest=projection.content_digest,
        adapter_id=adapter_id,
        adapter_revision=adapter_revision,
        runtime_definition_schema=projection.runtime_definition_schema,
        runtime_definition=projection.runtime_definition,
        model_prompt_fragments=projection.model_prompt_fragments,
        model_tool_ids=projection.model_tool_ids,
    )


def _verify_dependency_environment(
    environment: DependencyEnvironmentRef | None,
    dependencies: tuple[CapabilityRevision, ...],
) -> None:
    if not dependencies:
        if environment is not None:
            raise CapabilityResolutionError(
                "dependency environment resolver returned an environment without selected dependencies"
            )
        return
    if environment is None:
        raise CapabilityResolutionError("selected dependencies do not have a prepared environment")
    expected = {
        (item.capability_id, item.revision, item.content_digest)
        for item in dependencies
    }
    actual = {
        (item.capability_id, item.revision, item.content_digest)
        for item in environment.capability_refs
    }
    if actual != expected:
        raise CapabilityResolutionError(
            "dependency environment pointer does not match the selected dependency revisions"
        )


def _require_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text
