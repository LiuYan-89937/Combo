from __future__ import annotations

from typing import Any, TypeVar
import uuid

from langchain_core.messages import HumanMessage
from pydantic import BaseModel
from langgraph.config import get_stream_writer

from agent_factory.context_system.factory import inject_factory_prompt_context
from agent_factory.factory_package.prompt_context import prompt_context_values
from agent_factory.models import get_main_model, get_main_model_settings
from agent_factory.prompts import PromptId, get_prompt


T = TypeVar("T", bound=BaseModel)
STRUCTURED_OUTPUT_MAX_ATTEMPTS = 5


class FactoryModelCallError(RuntimeError):
    pass


def prompt_values(stage_id: str, values: dict[str, Any]) -> dict[str, Any]:
    merged = {**prompt_context_values(stage_id), **values}
    return inject_factory_prompt_context(stage_id=stage_id, values=merged)


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
    settings = get_main_model_settings()
    if model is None:
        raise FactoryModelCallError("main model is not configured")
    prompt_value = get_prompt(prompt_id).invoke(prompt_values(stage_id, values))
    messages = prompt_value.to_messages()
    structured_model = model.with_structured_output(output_model, method="json_mode").with_config(
        tags=["nostream"]
    )
    if settings.max_tokens is not None:
        structured_model = structured_model.bind(max_tokens=settings.max_tokens)
    last_error: Exception | None = None
    try:
        for attempt in range(1, STRUCTURED_OUTPUT_MAX_ATTEMPTS + 1):
            emit_model_activity(
                model_activity_started(
                    prompt_id=prompt_id,
                    call_kind="structured_json",
                    span_id=span_id,
                    schema_name=output_model.__name__,
                    attempt=attempt,
                    max_attempts=STRUCTURED_OUTPUT_MAX_ATTEMPTS,
                )
            )
            try:
                result = structured_model.invoke(messages)
                emit_model_activity(
                    model_activity_completed(
                        prompt_id=prompt_id,
                        call_kind="structured_json",
                        span_id=span_id,
                        output_summary=f"{output_model.__name__} attempt={attempt}",
                    )
                )
                return result
            except Exception as exc:
                last_error = exc
                if attempt >= STRUCTURED_OUTPUT_MAX_ATTEMPTS:
                    break
                messages.append(
                    HumanMessage(
                        content=_structured_retry_instruction(
                            output_model=output_model,
                            error=exc,
                            attempt=attempt,
                            max_attempts=STRUCTURED_OUTPUT_MAX_ATTEMPTS,
                            output_json_schema=str(values["output_json_schema"]),
                        )
                    )
                )
        raise last_error or FactoryModelCallError("structured model did not return a result")
    except Exception as exc:
        emit_model_activity(
            model_activity_failed(
                prompt_id=prompt_id,
                call_kind="structured_json",
                span_id=span_id,
                message=f"{type(exc).__name__}: {exc}",
            )
        )
        raise FactoryModelCallError(f"{type(exc).__name__}: {exc}") from exc


def _structured_retry_instruction(
    *,
    output_model: type[BaseModel],
    error: Exception,
    attempt: int,
    max_attempts: int,
    output_json_schema: str,
) -> str:
    return (
        "The previous structured JSON output failed schema validation.\n"
        "Regenerate the full response as JSON only. Do not explain the error.\n"
        "You must obey every JSON schema constraint, including required fields, enum values, "
        "minItems, maxItems, field types, numeric ranges, and extra=forbid.\n"
        f"Schema name: {output_model.__name__}\n"
        f"Validation observation from attempt {attempt}/{max_attempts}:\n{type(error).__name__}: {error}\n\n"
        f"Output JSON schema:\n{output_json_schema}"
    )


def call_text_model(
    *,
    stage_id: str,
    prompt_id: PromptId,
    values: dict[str, Any],
) -> str:
    span_id = uuid.uuid4().hex
    model = get_main_model()
    settings = get_main_model_settings()
    if model is None:
        raise FactoryModelCallError("main model is not configured")
    try:
        emit_model_activity(model_activity_started(prompt_id=prompt_id, call_kind="text", span_id=span_id))
        prompt_value = get_prompt(prompt_id).invoke(prompt_values(stage_id, values))
        configured_model = model
        if settings.max_tokens is not None:
            configured_model = configured_model.bind(max_tokens=settings.max_tokens)
        response = configured_model.invoke(prompt_value)
        content = getattr(response, "content", "")
        text = content if isinstance(content, str) else str(content)
        if not text.strip():
            raise FactoryModelCallError("model returned empty content")
        emit_model_activity(
            model_activity_completed(
                prompt_id=prompt_id,
                call_kind="text",
                span_id=span_id,
                output_summary=f"{len(text.strip())} chars",
            )
        )
        return text.strip()
    except FactoryModelCallError:
        emit_model_activity(
            model_activity_failed(
                prompt_id=prompt_id,
                call_kind="text",
                span_id=span_id,
                message="model returned empty content",
            )
        )
        raise
    except Exception as exc:
        emit_model_activity(
            model_activity_failed(
                prompt_id=prompt_id,
                call_kind="text",
                span_id=span_id,
                message=f"{type(exc).__name__}: {exc}",
            )
        )
        raise FactoryModelCallError(f"{type(exc).__name__}: {exc}") from exc


def model_activity_started(
    *,
    prompt_id: PromptId | str,
    call_kind: str,
    span_id: str | None = None,
    schema_name: str | None = None,
    attempt: int | None = None,
    max_attempts: int | None = None,
) -> dict[str, Any]:
    payload = {
        "event_type": "model_call_started",
        "span_id": span_id or uuid.uuid4().hex,
        "prompt_id": str(getattr(prompt_id, "value", prompt_id)),
        "call_kind": call_kind,
    }
    if schema_name:
        payload["schema_name"] = schema_name
    if attempt is not None:
        payload["attempt"] = attempt
    if max_attempts is not None:
        payload["max_attempts"] = max_attempts
    return payload


def model_activity_completed(
    *,
    prompt_id: PromptId | str,
    call_kind: str,
    span_id: str,
    output_summary: str | None = None,
) -> dict[str, Any]:
    return {
        "event_type": "model_call_completed",
        "span_id": span_id,
        "prompt_id": str(getattr(prompt_id, "value", prompt_id)),
        "call_kind": call_kind,
        "output_summary": output_summary or "",
    }


def model_activity_failed(*, prompt_id: PromptId | str, call_kind: str, span_id: str, message: str) -> dict[str, Any]:
    return {
        "event_type": "model_call_failed",
        "span_id": span_id,
        "prompt_id": str(getattr(prompt_id, "value", prompt_id)),
        "call_kind": call_kind,
        "message": message,
    }


def emit_model_activity(payload: dict[str, Any]) -> None:
    try:
        writer = get_stream_writer()
        writer({"type": "model_activity", "payload": payload})
    except Exception:
        return


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
