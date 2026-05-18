from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from agent_factory.memory_system.schema import MemoryContextPack, MemoryConversationSegment, MemoryExtractionDecision
from agent_factory.models import get_task_model, get_task_model_settings


MEMORY_EXTRACTION_MAX_ATTEMPTS = 5


MEMORY_EXTRACTION_SYSTEM = """You extract durable cross-session memory actions from a conversation segment.

Memory extraction policy:
- Read the whole segment before deciding. The user does not need to use explicit words like "remember".
- Extract only information useful beyond this session: stable preferences, decisions, constraints, durable facts, reusable procedures, and important artifacts.
- Classify every add/update action as one memory_type:
  - semantic: durable facts, preferences, constraints, decisions, and artifact references.
  - episodic: important events or outcomes from this session that are worth recalling later.
  - procedural: reusable ways of working, workflows, commands, or project-specific operating procedures.
- Use related_memories to deduplicate. Prefer update when a memory should replace or refine an existing item.
- delete requires merge_target_id and should only be used when the segment clearly invalidates an existing memory.
- noop if the segment contains only transient progress, greetings, raw logs, tool output, or details that should not be stored.
- Never store secrets, credentials, API keys, raw private data, or large copied text.

Return JSON only. The JSON must match the provided schema exactly."""


def extract_memory_actions(
    *,
    segment: MemoryConversationSegment,
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
    messages = [
        SystemMessage(content=MEMORY_EXTRACTION_SYSTEM),
        HumanMessage(
            content=json.dumps(
                {
                    "conversation_segment": segment.model_dump(mode="json"),
                    "related_memories": related_memories.model_dump(mode="json"),
                    "output_json_schema": MemoryExtractionDecision.model_json_schema(),
                },
                ensure_ascii=False,
                indent=2,
            )
        ),
    ]
    last_error: Exception | None = None
    for attempt in range(1, MEMORY_EXTRACTION_MAX_ATTEMPTS + 1):
        try:
            return structured.invoke(messages)
        except Exception as exc:
            last_error = exc
            if attempt >= MEMORY_EXTRACTION_MAX_ATTEMPTS:
                break
            messages.append(
                HumanMessage(
                    content=(
                        "The previous memory extraction output failed validation.\n"
                        "Regenerate the full JSON only, obeying every schema constraint.\n"
                        f"Validation observation from attempt {attempt}/{MEMORY_EXTRACTION_MAX_ATTEMPTS}:\n"
                        f"{type(exc).__name__}: {exc}\n\n"
                        f"Output JSON schema:\n{json.dumps(MemoryExtractionDecision.model_json_schema(), ensure_ascii=False)}"
                    )
                )
            )
    raise last_error or RuntimeError("memory extraction did not return a result")
