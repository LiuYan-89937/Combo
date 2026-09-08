from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, field_validator

from combo.model_pool import ModelPoolStore
from combo.model_pool.resolver import resolve_available_chat_model
from combo.runtime_kernel.model_operations import (
    execute_structured_output_invocation,
    prepare_structured_output_invocation,
)


MAX_MERMAID_SOURCE_CHARS = 100_000
MAX_MERMAID_ERROR_CHARS = 8_000


class MermaidRepairResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1, max_length=MAX_MERMAID_SOURCE_CHARS)

    @field_validator("source")
    @classmethod
    def _source_is_plain_mermaid(cls, value: str) -> str:
        source = str(value or "").strip()
        if source.startswith("```") or source.endswith("```"):
            raise ValueError("repaired Mermaid source must not contain a Markdown fence")
        return source


def repair_mermaid_source(
    source: str,
    *,
    parser_error: str,
    store: ModelPoolStore,
) -> MermaidRepairResult:
    normalized_source = str(source or "").strip()
    if not normalized_source:
        raise ValueError("Mermaid source must not be empty")
    if len(normalized_source) > MAX_MERMAID_SOURCE_CHARS:
        raise ValueError("Mermaid source exceeds the repair limit")
    resolved = resolve_available_chat_model("task", store=store)
    if resolved is None:
        raise RuntimeError("task_model_not_configured")
    invocation = prepare_structured_output_invocation(
        model=resolved.model,
        output_model=MermaidRepairResult,
        messages=[
            SystemMessage(
                content=(
                    "You repair Mermaid diagram source after the Mermaid parser rejects it. "
                    "Return only the requested structured object. Preserve the diagram type, "
                    "node identifiers, labels, edges, direction, and business meaning. Make only "
                    "the syntax changes required for Mermaid to parse the source. Quote or escape "
                    "label text when punctuation conflicts with Mermaid grammar. Do not add a "
                    "Markdown code fence, explanation, comments, styling, or new content."
                )
            ),
            HumanMessage(
                content=json.dumps(
                    {
                        "source": normalized_source,
                        "parser_error": str(parser_error or "")[:MAX_MERMAID_ERROR_CHARS],
                    },
                    ensure_ascii=False,
                )
            ),
        ],
        model_metadata=resolved.settings.metadata(),
        config_tags=["mermaid-syntax-repair"],
    )
    result = execute_structured_output_invocation(
        invocation,
        config={
            "metadata": {
                "operation": "mermaid_syntax_repair",
                "task_model_profile_id": resolved.profile_id,
            }
        },
    )
    return result.value
