from __future__ import annotations

from typing import Any

from langchain_anthropic import ChatAnthropic

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
        return super()._get_request_payload(
            materialize_local_image_messages(messages),
            stop=stop,
            **kwargs,
        )
