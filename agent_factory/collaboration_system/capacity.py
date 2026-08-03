from __future__ import annotations

from agent_factory.local_inference.capacity import (
    ChatInferenceCapacity,
    inspect_chat_inference_capacity,
)


def inspect_configured_inference_capacity() -> ChatInferenceCapacity:
    """Return the shared chat inference capacity used by collaboration dispatch.

    The local inference capacity probe reads the active chat model profile's
    ``parallel_slots`` setting and enriches it with live llama-server occupancy
    when the inference endpoint is reachable. Collaboration worker limits are
    applied separately by the collaboration service.
    """

    return inspect_chat_inference_capacity()
