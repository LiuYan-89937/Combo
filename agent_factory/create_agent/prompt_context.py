from __future__ import annotations

from langchain_core.messages import BaseMessage


def project_messages_for_prompt(messages: list[BaseMessage]) -> list[BaseMessage]:
    return list(messages)
