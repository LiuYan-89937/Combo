from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def resolve_resource_selector(resources: Mapping[str, Any], selector: str) -> Any:
    current: Any = resources
    for part in selector.split("."):
        if not isinstance(current, Mapping) or part not in current:
            raise KeyError(selector)
        current = current[part]
    return current
