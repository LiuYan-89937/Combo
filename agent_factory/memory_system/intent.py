from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent_factory.memory_system.schema import MemoryIntentDecision
from agent_factory.models import get_task_model, get_task_model_settings


MEMORY_INTENT_SYSTEM = """You are the cross-session memory intent classifier for FastAgentFactory RuntimeKernel.
Classify whether the user explicitly asks the agent to remember, forget, or update durable cross-session memory.
Do not use keyword rules. Infer intent from the message content and context.
Return JSON only matching the provided schema."""


def detect_memory_intent(
    *,
    messages_delta: list[dict[str, Any]],
    model: object | None = None,
) -> MemoryIntentDecision:
    task_model = model or get_task_model()
    if task_model is None:
        raise RuntimeError("task model is not configured")
    settings = get_task_model_settings()
    structured = task_model.with_structured_output(MemoryIntentDecision, method="json_mode").with_config(
        tags=["nostream"]
    )
    if settings.max_tokens is not None:
        structured = structured.bind(max_tokens=settings.max_tokens)
    return structured.invoke(
        [
            SystemMessage(content=MEMORY_INTENT_SYSTEM),
            HumanMessage(content=_messages_text(messages_delta)),
        ]
    )


def _messages_text(messages_delta: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in messages_delta:
        role = str(item.get("role") or item.get("type") or "message")
        content = str(item.get("content") or "")
        if content.strip():
            lines.append(f"{role}: {content}")
    return "\n".join(lines) or "(empty turn)"
