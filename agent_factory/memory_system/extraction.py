from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent_factory.memory_system.schema import MemoryContextPack, MemoryExtractionDecision, MemoryIntentDecision
from agent_factory.models import get_task_model, get_task_model_settings


MEMORY_EXTRACTION_SYSTEM = """You extract durable cross-session memory actions.
Only produce actions that are useful beyond the current session.
Keep memories concise, stable, and scoped to facts, preferences, decisions, constraints, or artifacts.
Do not extract transient task progress unless the user explicitly wants it remembered.
Return JSON only matching the provided schema."""


def extract_memory_actions(
    *,
    intent: MemoryIntentDecision,
    messages_delta: list[dict[str, Any]],
    related_memories: MemoryContextPack,
    model: object | None = None,
) -> MemoryExtractionDecision:
    task_model = model or get_task_model()
    if task_model is None:
        raise RuntimeError("task model is not configured")
    settings = get_task_model_settings()
    structured = task_model.with_structured_output(MemoryExtractionDecision, method="json_mode").with_config(
        tags=["nostream"]
    )
    if settings.max_tokens is not None:
        structured = structured.bind(max_tokens=settings.max_tokens)
    return structured.invoke(
        [
            SystemMessage(content=MEMORY_EXTRACTION_SYSTEM),
            HumanMessage(
                content=json.dumps(
                    {
                        "intent": intent.model_dump(mode="json"),
                        "messages_delta": messages_delta,
                        "related_memories": related_memories.model_dump(mode="json"),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            ),
        ]
    )
