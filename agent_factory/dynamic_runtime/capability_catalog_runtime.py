from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
import json

from agent_factory.dynamic_runtime.capability_resolution_store import CapabilityResolutionReceiptStore
from agent_factory.dynamic_runtime.capability_store import ActiveCapability, CapabilityStore
from agent_factory.runtime_protocol import CapabilityTrustLevel


class CapabilityCatalogRuntime:
    """Read-only control-plane view used by the stable main-agent capability tool."""

    def __init__(
        self,
        *,
        store: CapabilityStore,
        health_receipts: CapabilityResolutionReceiptStore,
        allowed_trust_levels: tuple[CapabilityTrustLevel, ...],
    ) -> None:
        if not allowed_trust_levels:
            raise ValueError("capability catalog requires allowed trust levels")
        self._store = store
        self._health_receipts = health_receipts
        self._allowed_trust_levels = frozenset(allowed_trust_levels)

    def list_active(self) -> list[dict[str, object]]:
        return [self._summary(item) for item in self._eligible()]

    def search(self, query: str, *, limit: int) -> list[dict[str, object]]:
        terms = tuple(part for part in _normalize(query).split() if part)
        if not terms:
            raise ValueError("capability search query must not be empty")
        if limit < 1:
            raise ValueError("capability search limit must be positive")
        matches: list[tuple[float, ActiveCapability]] = []
        for item in self._eligible():
            document = item.index_revision.document
            fields = (
                _normalize(document.display_name),
                _normalize(document.description),
                *(_normalize(keyword) for keyword in document.keywords),
            )
            matched = sum(1 for term in terms if any(term in field for field in fields))
            if matched:
                matches.append((matched / len(terms), item))
        matches.sort(key=lambda entry: (-entry[0], entry[1].revision.capability_id))
        return [
            {**self._summary(item), "score": score}
            for score, item in matches[:limit]
        ]

    def inspect(self, capability_id: str) -> dict[str, object]:
        item = self._by_id().get(_required_text(capability_id, "capability_id"))
        if item is None:
            raise LookupError(f"active capability not found: {capability_id}")
        revision = item.revision
        return {
            **self._summary(item),
            "source_uri": revision.source_uri,
            "resolved_version": revision.resolved_version,
            "dependencies": [
                dependency.model_dump(mode="json")
                for dependency in revision.content.dependencies
            ],
            "resources": [resource.model_dump(mode="json") for resource in revision.content.resources],
            "definition_schema": revision.content.definition_schema,
        }

    def prepare(self, capability_ids: tuple[str, ...]) -> dict[str, object]:
        requested = tuple(dict.fromkeys(_required_text(value, "capability_id") for value in capability_ids))
        if not requested:
            raise ValueError("capability preparation requires at least one capability ID")
        active = self._by_id()
        selected: dict[str, ActiveCapability] = {}
        visiting: list[str] = []

        def include(capability_id: str) -> None:
            if capability_id in selected:
                return
            item = active.get(capability_id)
            if item is None:
                raise LookupError(f"active capability not found: {capability_id}")
            if capability_id in visiting:
                start = visiting.index(capability_id)
                raise ValueError("capability dependency cycle: " + " -> ".join((*visiting[start:], capability_id)))
            health = self._health_receipts.latest_health(
                capability_id=capability_id,
                revision=item.revision.revision,
                content_digest=item.revision.content_digest,
            )
            if health is None or health.status != "healthy":
                raise RuntimeError(f"capability revision is not healthy: {capability_id}")
            if health.valid_until is not None and datetime.fromisoformat(health.valid_until) <= datetime.now(UTC):
                raise RuntimeError(f"capability health receipt expired: {capability_id}")
            visiting.append(capability_id)
            try:
                for dependency in item.revision.content.dependencies:
                    if dependency.required:
                        include(dependency.capability_id)
            finally:
                visiting.pop()
            selected[capability_id] = item

        for capability_id in requested:
            include(capability_id)
        references = [
            {
                "capability_id": item.revision.capability_id,
                "kind": item.revision.kind,
                "revision": item.revision.revision,
                "resolved_version": item.revision.resolved_version,
                "content_digest": item.revision.content_digest,
            }
            for item in sorted(selected.values(), key=lambda value: value.revision.capability_id)
        ]
        return {
            "requested_capability_ids": list(requested),
            "capability_revisions": references,
            "preparation_digest": _digest(references),
        }

    def _eligible(self) -> tuple[ActiveCapability, ...]:
        return tuple(
            item
            for item in self._store.active_capabilities()
            if item.revision.trust_level in self._allowed_trust_levels
        )

    def _by_id(self) -> dict[str, ActiveCapability]:
        return {item.revision.capability_id: item for item in self._eligible()}

    @staticmethod
    def _summary(item: ActiveCapability) -> dict[str, object]:
        revision = item.revision
        return {
            "name": revision.content.display_name,
            "kind": revision.kind,
            "description": revision.content.description,
        }


def _normalize(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _required_text(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must not be empty")
    return text


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()
