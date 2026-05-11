from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

from agent_factory.factory_graph.prompt_context import prompt_context_values
from agent_factory.models import get_main_model, get_main_model_settings
from agent_factory.prompts import PromptId, get_prompt


T = TypeVar("T", bound=BaseModel)


class FactoryModelCallError(RuntimeError):
    pass


def prompt_values(stage_id: str, values: dict[str, Any]) -> dict[str, Any]:
    return {**prompt_context_values(stage_id), **values}


def call_structured_model(
    *,
    stage_id: str,
    prompt_id: PromptId,
    output_model: type[T],
    values: dict[str, Any],
) -> T:
    model = get_main_model()
    settings = get_main_model_settings()
    if model is None:
        raise FactoryModelCallError("main model is not configured")
    try:
        prompt_value = get_prompt(prompt_id).invoke(prompt_values(stage_id, values))
        structured_model = model.with_structured_output(output_model, method="json_mode").with_config(
            tags=["nostream"]
        )
        if settings.max_tokens is not None:
            structured_model = structured_model.bind(max_tokens=settings.max_tokens)
        return structured_model.invoke(prompt_value)
    except Exception as exc:
        raise FactoryModelCallError(f"{type(exc).__name__}: {exc}") from exc


def call_text_model(
    *,
    stage_id: str,
    prompt_id: PromptId,
    values: dict[str, Any],
) -> str:
    model = get_main_model()
    settings = get_main_model_settings()
    if model is None:
        raise FactoryModelCallError("main model is not configured")
    try:
        prompt_value = get_prompt(prompt_id).invoke(prompt_values(stage_id, values))
        configured_model = model.with_config(tags=["nostream"])
        if settings.max_tokens is not None:
            configured_model = configured_model.bind(max_tokens=settings.max_tokens)
        response = configured_model.invoke(prompt_value)
        content = getattr(response, "content", "")
        text = content if isinstance(content, str) else str(content)
        if not text.strip():
            raise FactoryModelCallError("model returned empty content")
        return text.strip()
    except FactoryModelCallError:
        raise
    except Exception as exc:
        raise FactoryModelCallError(f"{type(exc).__name__}: {exc}") from exc


def model_error_patch(stage_id: str, message: str) -> dict[str, Any]:
    return {
        "current_stage": stage_id,
        "status": "failed",
        "graph_control": {"action": "end"},
        "errors": [{"where": stage_id, "message": message}],
        "stage_log": [
            {
                "stage_id": stage_id,
                "status": "failed",
                "message": message,
            }
        ],
    }
