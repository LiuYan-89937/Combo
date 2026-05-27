from __future__ import annotations

from typing import Any, TypeVar
import uuid

from pydantic import BaseModel
from langgraph.config import get_stream_writer

from agent_factory.context_system.factory import inject_factory_prompt_context
from agent_factory.factory_package.prompt_context import prompt_context_values
from agent_factory.models import get_main_model
from agent_factory.prompts import PromptId, get_prompt
from agent_factory.runtime_kernel.model_operations import ModelOperationService


T = TypeVar("T", bound=BaseModel)
STRUCTURED_OUTPUT_MAX_ATTEMPTS = 5


class FactoryModelCallError(RuntimeError):
    pass


def prompt_values(stage_id: str, values: dict[str, Any]) -> dict[str, Any]:
    merged = {**prompt_context_values(stage_id), **values}
    return inject_factory_prompt_context(
        stage_id=stage_id,
        values=merged,
        context_event_sink=emit_context_activity,
    )


def call_structured_model(
    *,
    stage_id: str,
    prompt_id: PromptId,
    output_model: type[T],
    values: dict[str, Any],
) -> T:
    span_id = uuid.uuid4().hex
    if "output_json_schema" not in values:
        raise FactoryModelCallError("structured model calls must include output_json_schema")
    model = get_main_model()
    if model is None:
        raise FactoryModelCallError("main model is not configured")
    prompt_value = get_prompt(prompt_id).invoke(prompt_values(stage_id, values))
    messages = prompt_value.to_messages()
    service = ModelOperationService(role="main", model=model)
    try:
        result = service.structured_json(
            output_model=output_model,
            state=None,
            prebuilt_messages=messages,
            structured_method="json_mode",
            config_tags=["nostream"],
            max_attempts=STRUCTURED_OUTPUT_MAX_ATTEMPTS,
            emit_event=emit_model_activity,
            operation_metadata={
                "prompt_id": str(getattr(prompt_id, "value", prompt_id)),
                "call_kind": "structured_json",
                "span_id": span_id,
                "schema_name": output_model.__name__,
            },
        )
        return result
    except Exception as exc:
        raise FactoryModelCallError(f"{type(exc).__name__}: {exc}") from exc


def emit_model_activity(payload: dict[str, Any]) -> None:
    try:
        writer = get_stream_writer()
        writer({"type": "model_activity", "payload": payload})
    except Exception:
        return


def emit_context_activity(payload: dict[str, Any]) -> None:
    try:
        writer = get_stream_writer()
        writer({"type": "context_event", "payload": payload})
    except Exception:
        return
