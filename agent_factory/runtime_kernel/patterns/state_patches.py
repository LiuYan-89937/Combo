from __future__ import annotations

from typing import Any

from agent_factory.runtime_kernel.errors import RuntimeKernelError
from agent_factory.runtime_kernel.state import RuntimeState
from agent_factory.runtime_kernel.state.runtime_graph import (
    runtime_graph_patch,
    runtime_state_from_graph,
    split_graph_patch,
    validate_patch_sections,
)
from agent_factory.runtime_kernel.state_contracts import PackageStateManager


def validate_wrapper_patch_sections(
    wrapper_id: str,
    writable_sections: set[str],
    patch: dict[str, Any],
) -> None:
    illegal = set(patch).difference(writable_sections)
    if illegal:
        raise ValueError(
            f"{wrapper_id} attempted to write disallowed sections: {', '.join(sorted(illegal))}"
        )


def validate_package_state_patch(
    manager: PackageStateManager | None,
    node_id: str,
    patch: dict[str, Any],
) -> None:
    if "package_state" not in patch:
        return
    if manager is None:
        raise RuntimeKernelError(f"node {node_id} attempted to write package_state without a state contract")
    manager.validate_patch(node_id=node_id, patch=patch["package_state"])


def merge_patches(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in extra.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged
