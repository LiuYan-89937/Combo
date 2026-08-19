from __future__ import annotations

from typing import Any

from combo.models.adapters.base import (
    OpenAIChatCompletionsAdapter,
    reasoning_effort,
)


class GenericOpenAICompatibleChatAdapter(OpenAIChatCompletionsAdapter):
    def request_parameters(self, settings: Any) -> dict[str, Any]:
        effort = reasoning_effort(settings)
        return {"reasoning_effort": effort} if effort else {}


class OpenAIChatAdapter(GenericOpenAICompatibleChatAdapter):
    pass
