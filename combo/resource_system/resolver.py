from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from combo.resource_system.schema import ResourceDescriptor
from combo.resource_system.store import ResourceStore, ResourceStoreError


RESOURCE_RESOLVER_KEY = "resource_resolver"


@dataclass(frozen=True, slots=True)
class CapabilityResourceResolver:
    descriptors: dict[str, ResourceDescriptor]
    store: ResourceStore

    def owns(self, selector: str) -> bool:
        return selector.split(".", 1)[0] in self.descriptors

    def resolve(self, resource_id: str) -> Any:
        descriptor = self.descriptors.get(resource_id)
        if descriptor is None:
            raise ResourceStoreError(f"resource is not present in the capability snapshot: {resource_id}")
        return self.store.resolve(descriptor)

    def resolve_selector(self, selector: str) -> Any:
        resource_id, *path = [item for item in selector.split(".") if item]
        value = self.resolve(resource_id)
        for part in path:
            if not isinstance(value, dict) or part not in value:
                raise ResourceStoreError(f"resource_required: {resource_id}")
            value = value[part]
        return value
