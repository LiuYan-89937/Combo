from __future__ import annotations

from combo.runtime_kernel.planning import RUNTIME_PLAN_TOOL_ID
from combo.runtime_kernel.state import RuntimeState
from combo.runtime_protocol import CapabilitySnapshot


class CapabilityStateError(RuntimeError):
    pass


def bind_capability_snapshot(
    state: RuntimeState,
    snapshot: CapabilitySnapshot,
    *,
    runtime_instance_id: str,
) -> RuntimeState:
    """Bind one immutable capability snapshot to a fresh runtime state."""

    instance_id = str(runtime_instance_id or "").strip()
    if not instance_id:
        raise CapabilityStateError("capability snapshot binding requires runtime_instance_id")
    if RUNTIME_PLAN_TOOL_ID in snapshot.tool_ids:
        raise CapabilityStateError(
            "runtime_plan is owned by the fixed plan graph and cannot be selected as a capability"
        )
    current_id = str(state.tools.capability_snapshot_id or "").strip()
    current_digest = str(state.tools.capability_snapshot_digest or "").strip()
    if current_id and current_id != snapshot.snapshot_id:
        raise CapabilityStateError("runtime state is already bound to a different capability snapshot")
    if current_digest and current_digest != snapshot.content_digest:
        raise CapabilityStateError("runtime state capability snapshot digest cannot be replaced")
    current_tools = tuple(state.tools.available_tools)
    if current_tools and current_tools != snapshot.tool_ids:
        raise CapabilityStateError("runtime state tool projection differs from its capability snapshot")

    updated = state.model_copy(deep=True)
    current_instance_id = str(updated.run.runtime_instance_id or "").strip()
    if current_instance_id and current_instance_id != instance_id:
        raise CapabilityStateError("runtime state is already bound to a different runtime instance")
    updated.run.runtime_instance_id = instance_id
    updated.run.run_id = instance_id
    updated.tools.capability_snapshot_id = snapshot.snapshot_id
    updated.tools.capability_snapshot_digest = snapshot.content_digest
    updated.tools.available_tools = list(snapshot.tool_ids)
    return updated


def require_bound_tool_ids(state: RuntimeState) -> list[str]:
    snapshot_id = str(state.tools.capability_snapshot_id or "").strip()
    snapshot_digest = str(state.tools.capability_snapshot_digest or "").strip()
    if not snapshot_id or not snapshot_digest:
        raise CapabilityStateError("runtime state requires a bound capability snapshot")
    return list(state.tools.available_tools)
