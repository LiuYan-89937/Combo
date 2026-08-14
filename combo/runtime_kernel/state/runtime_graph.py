from __future__ import annotations

from typing import Any

from combo.runtime_kernel.state.checkpoint_projection import runtime_checkpoint_payload
from combo.runtime_kernel.state.schema import RuntimeState


def runtime_state_from_graph(raw_state: dict[str, Any]) -> RuntimeState:
    return RuntimeState.model_validate(raw_state.get("runtime") or {})


def runtime_graph_patch(state: RuntimeState, *, messages: list[Any] | None = None) -> dict[str, Any]:
    patch: dict[str, Any] = {"runtime": runtime_checkpoint_payload(state, mode="json")}
    if messages:
        patch["messages"] = messages
    return patch


def split_graph_patch(patch: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
    messages = list(patch.get("messages") or [])
    return messages, {key: value for key, value in patch.items() if key != "messages"}


def validate_patch_sections(impl_id: str, patch: dict[str, Any], writable_sections: set[str]) -> None:
    illegal = set(patch).difference(writable_sections)
    if illegal:
        raise ValueError(f"{impl_id} attempted to write disallowed sections: {', '.join(sorted(illegal))}")
