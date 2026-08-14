from __future__ import annotations

from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage

from agent_factory.model_image_inputs import materialize_local_image_messages


class LocalImageChatAnthropic(ChatAnthropic):
    """Materialize host-local image references only at the provider request boundary."""

    def _get_request_payload(
        self,
        input_: Any,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict:
        messages = self._convert_input(input_).to_messages()
        messages = _with_stable_system_cache_breakpoint(messages)
        kwargs.setdefault("cache_control", {"type": "ephemeral"})
        return super()._get_request_payload(
            materialize_local_image_messages(messages),
            stop=stop,
            **kwargs,
        )


def _with_stable_system_cache_breakpoint(messages: list[Any]) -> list[Any]:
    updated = list(messages)
    for index, message in enumerate(updated):
        if not isinstance(message, SystemMessage):
            continue
        content = getattr(message, "content", "")
        if not isinstance(content, str) or not content.strip():
            return updated
        updated[index] = message.model_copy(
            update={
                "content": [
                    {
                        "type": "text",
                        "text": content,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            }
        )
        return updated
    return updated
