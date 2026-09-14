from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from langchain_core.messages import messages_from_dict, messages_to_dict

logger = logging.getLogger(__name__)


def archive_context_history(*, store: Any, state: Any, messages: list[Any]) -> None:
    """Keep transcript evidence outside the model context and checkpoint body.

    References are checkpointed with the compressed context. Uncommitted writes
    have a deterministic key for the same reference position and are overwritten
    on retry. The archive shares the existing graph store's persistence backend.
    """
    references = state.context.compression_archive_refs
    key = str(len(references))
    store.put(_namespace(state), key, {"messages": messages_to_dict(messages)})
    references.append(key)


def conversation_projection_history(*, store: Any, state: Any, messages: list[Any]) -> list[Any]:
    """Restore the full transcript for records, never for another model call."""
    if not state.context.compression_archive_refs:
        return messages
    ordered: dict[str, Any] = {}

    def append(batch: Iterable[Any]) -> None:
        for message in batch:
            message_id = str(getattr(message, "id", "") or "")
            if not message_id:
                raise ValueError("archived conversation message has no stable id")
            ordered[message_id] = message

    for key in state.context.compression_archive_refs:
        item = store.get(_namespace(state), key)
        if item is None:
            raise RuntimeError("compressed conversation history is missing: " + key)
        append(messages_from_dict(item.value["messages"]))
    append(messages)
    return list(ordered.values())


def _namespace(state: Any) -> tuple[str, ...]:
    return ("conversation_history", state.run.session_id, state.run.runtime_instance_id)


def release_context_history(*, store: Any, state: Any) -> None:
    """Called only after a terminal transcript and its records are committed."""
    for key in state.context.compression_archive_refs:
        try:
            store.delete(_namespace(state), key)
        except Exception:
            logger.warning("Could not release committed conversation history %s", key, exc_info=True)
