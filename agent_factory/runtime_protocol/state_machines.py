from __future__ import annotations

from collections.abc import Mapping

from agent_factory.runtime_protocol.commands import CommandStatus
from agent_factory.runtime_protocol.conversation import ConversationTurnStatus
from agent_factory.runtime_protocol.contracts import RuntimeInstanceStatus
from agent_factory.runtime_protocol.lifecycle import (
    ApplicationGenerationStatus,
    CutoverStatus,
    DeleteStatus,
    DeliveryStatus,
)
from agent_factory.runtime_protocol.tool_calls import ToolCallStatus


class InvalidStateTransition(ValueError):
    pass


RUNTIME_INSTANCE_TRANSITIONS: Mapping[RuntimeInstanceStatus, frozenset[RuntimeInstanceStatus]] = {
    "created": frozenset({"queued", "cancelled"}),
    "queued": frozenset({"running", "cancelling", "cancelled", "failed"}),
    "running": frozenset({"waiting_approval", "waiting_external", "cancelling", "completed", "failed", "cancelled"}),
    "waiting_approval": frozenset({"running", "cancelling", "failed", "cancelled"}),
    "waiting_external": frozenset({"running", "cancelling", "failed", "cancelled"}),
    "cancelling": frozenset({"cancelled", "failed"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}

CONVERSATION_TURN_TRANSITIONS: Mapping[
    ConversationTurnStatus,
    frozenset[ConversationTurnStatus],
] = {
    "queued": frozenset({"running", "completed", "failed", "cancelled"}),
    "running": frozenset({"waiting_approval", "waiting_external", "completed", "failed", "cancelled"}),
    "waiting_approval": frozenset({"running", "failed", "cancelled"}),
    "waiting_external": frozenset({"running", "failed", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}

COMMAND_TRANSITIONS: Mapping[CommandStatus, frozenset[CommandStatus]] = {
    "received": frozenset({"queued", "rejected", "cancelled"}),
    "queued": frozenset({"running", "cancelled", "rejected"}),
    "running": frozenset({"completed", "failed", "cancelled", "rejected"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
    "rejected": frozenset(),
}

TOOL_CALL_TRANSITIONS: Mapping[ToolCallStatus, frozenset[ToolCallStatus]] = {
    "proposed": frozenset({"waiting_approval", "running", "rejected", "cancelled"}),
    "waiting_approval": frozenset({"running", "rejected", "cancelled", "timed_out"}),
    "running": frozenset({"completed", "failed", "cancelled", "timed_out"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
    "rejected": frozenset(),
    "timed_out": frozenset(),
}

APPLICATION_GENERATION_TRANSITIONS: Mapping[
    ApplicationGenerationStatus,
    frozenset[ApplicationGenerationStatus],
] = {
    "starting": frozenset({"active", "closed", "crashed"}),
    "active": frozenset({"quiescing", "crashed"}),
    "quiescing": frozenset({"closed", "crashed"}),
    "closed": frozenset(),
    "crashed": frozenset(),
}

CUTOVER_TRANSITIONS: Mapping[CutoverStatus, frozenset[CutoverStatus]] = {
    "preparing": frozenset({"verifying", "failed", "rolled_back"}),
    "verifying": frozenset({"committed", "failed", "rolled_back"}),
    "committed": frozenset(),
    "failed": frozenset({"rolled_back"}),
    "rolled_back": frozenset(),
}

DELIVERY_TRANSITIONS: Mapping[DeliveryStatus, frozenset[DeliveryStatus]] = {
    "prepared": frozenset({"finalizing", "compensating", "failed"}),
    "finalizing": frozenset({"committed", "compensating", "failed"}),
    "committed": frozenset(),
    "compensating": frozenset({"compensated", "failed"}),
    "compensated": frozenset(),
    "failed": frozenset({"compensating"}),
}

DELETE_TRANSITIONS: Mapping[DeleteStatus, frozenset[DeleteStatus]] = {
    "planned": frozenset({"frozen", "failed"}),
    "frozen": frozenset({"deleting", "failed"}),
    "deleting": frozenset({"completed", "failed"}),
    "completed": frozenset(),
    "failed": frozenset({"deleting"}),
}


def require_transition(current: str, target: str, transitions: Mapping[str, frozenset[str]], *, machine: str) -> None:
    allowed = transitions.get(current)
    if allowed is None:
        raise InvalidStateTransition(f"unknown {machine} state: {current}")
    if target not in allowed:
        raise InvalidStateTransition(f"invalid {machine} transition: {current} -> {target}")
