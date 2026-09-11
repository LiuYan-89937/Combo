from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from combo.models.content import content_to_text
from combo.models.message_layout import system_messages_first
from combo.tooling.execution_context import RuntimeModelGenerationInterrupted


_DEFAULT_STRUCTURED_METHOD = "json_mode"
StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class StructuredOutputInvocation(Generic[StructuredOutputT]):
    model: Any
    messages: tuple[Any, ...]
    method: str
    output_model: type[StructuredOutputT]
    output_json_schema: str


@dataclass(frozen=True, slots=True)
class StructuredOutputExecution(Generic[StructuredOutputT]):
    value: StructuredOutputT
    raw: Any
    attempt_count: int
    messages: tuple[Any, ...]


def prepare_structured_output_invocation(
    *,
    model: Any,
    output_model: type[StructuredOutputT],
    messages: list[Any],
    model_metadata: dict[str, Any],
    requested_method: str | None = None,
    config_tags: list[str] | None = None,
) -> StructuredOutputInvocation[StructuredOutputT]:
    method = _effective_structured_method(
        requested=requested_method,
        model_metadata=model_metadata,
    )
    output_json_schema = _schema_payload(output_model)
    request_messages = _structured_request_messages(
        messages=list(messages),
        output_model=output_model,
        output_json_schema=output_json_schema,
        structured_method=method,
    )
    return StructuredOutputInvocation(
        model=_structured_model(
            model=model,
            output_model=output_model,
            method=method,
            config_tags=_structured_config_tags(config_tags),
        ),
        messages=tuple(system_messages_first(request_messages)),
        method=method,
        output_model=output_model,
        output_json_schema=output_json_schema,
    )


def execute_structured_output_invocation(
    invocation: StructuredOutputInvocation[StructuredOutputT],
    *,
    config: dict[str, Any] | None = None,
    max_attempts: int = 3,
    invoke_model: Callable[[Any, tuple[Any, ...], int], Any] | None = None,
    before_attempt: Callable[[int, int, tuple[Any, ...]], None] | None = None,
    on_attempt_failure: Callable[[Exception, int, int], None] | None = None,
) -> StructuredOutputExecution[StructuredOutputT]:
    attempts = max(1, int(max_attempts))
    request_messages = list(invocation.messages)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        attempt_messages = tuple(request_messages)
        if before_attempt is not None:
            before_attempt(attempt, attempts, attempt_messages)
        try:
            response = (
                invoke_model(invocation.model, attempt_messages, attempt)
                if invoke_model is not None
                else invocation.model.invoke(list(attempt_messages), config=config)
            )
            value, raw = _validate_structured_response(
                response,
                output_model=invocation.output_model,
            )
            return StructuredOutputExecution(
                value=value,
                raw=raw,
                attempt_count=attempt,
                messages=attempt_messages,
            )
        except RuntimeModelGenerationInterrupted:
            raise
        except Exception as exc:
            last_error = exc
            if on_attempt_failure is not None:
                on_attempt_failure(exc, attempt, attempts)
            if attempt < attempts:
                request_messages.append(
                    HumanMessage(
                        content=_structured_retry_instruction(
                            output_model=invocation.output_model,
                            error=exc,
                            attempt=attempt,
                            max_attempts=attempts,
                            output_json_schema=invocation.output_json_schema,
                        )
                    )
                )
    raise RuntimeError(
        f"structured model operation failed after {attempts} attempts: {last_error}"
    ) from last_error


def _structured_model(
    *,
    model: Any,
    output_model: type[BaseModel],
    method: str | None,
    config_tags: list[str] | None,
) -> Any:
    structured = (
        model.with_structured_output(output_model, method=method, include_raw=True)
        if method
        else model.with_structured_output(output_model, include_raw=True)
    )
    if config_tags and hasattr(structured, "with_config"):
        structured = structured.with_config(tags=list(config_tags))
    return structured


def _validate_structured_response(
    response: Any,
    *,
    output_model: type[StructuredOutputT],
) -> tuple[StructuredOutputT, Any]:
    if isinstance(response, output_model):
        return response, response

    raw = response
    candidate = response
    parsing_error: Any = None
    if isinstance(response, dict) and "raw" in response:
        raw = response.get("raw")
        candidate = response.get("parsed")
        parsing_error = response.get("parsing_error")

    if isinstance(candidate, output_model):
        return candidate, raw
    if candidate is not None:
        return output_model.model_validate(candidate), raw

    content = content_to_text(getattr(raw, "content", raw)).strip()
    if content:
        return output_model.model_validate_json(content), raw
    if parsing_error is not None:
        raise parsing_error
    raise ValueError("structured model response did not contain parsed data or JSON text")


def _structured_config_tags(config_tags: list[str] | None) -> list[str]:
    tags = ["nostream"]
    for tag in config_tags or []:
        item = str(tag).strip()
        if item and item not in tags:
            tags.append(item)
    return tags


def _effective_structured_method(*, requested: str | None, model_metadata: dict[str, Any]) -> str:
    method = str(requested or model_metadata.get("structured_output_method") or "").strip()
    if not method:
        method = str(
            model_metadata.get("default_structured_output_method")
            or _DEFAULT_STRUCTURED_METHOD
        ).strip()
    supported = {
        str(item)
        for item in (model_metadata.get("structured_output_methods") or [])
        if str(item).strip()
    }
    if supported and method not in supported:
        provider = str(model_metadata.get("provider") or "model")
        supported_text = ", ".join(sorted(supported))
        raise RuntimeError(
            f"structured output method {method!r} is not supported by {provider}; "
            f"supported methods: {supported_text}"
        )
    return method or _DEFAULT_STRUCTURED_METHOD


def _structured_request_messages(
    *,
    messages: list[Any],
    output_model: type[BaseModel],
    output_json_schema: str,
    structured_method: str,
) -> list[Any]:
    if structured_method != "json_mode":
        return messages
    return [
        *messages,
        HumanMessage(
            content=_structured_json_mode_instruction(
                output_model=output_model,
                output_json_schema=output_json_schema,
            )
        ),
    ]


def _schema_payload(output_model: type[BaseModel]) -> str:
    try:
        return json.dumps(output_model.model_json_schema(), ensure_ascii=False, sort_keys=True)
    except Exception:
        return output_model.__name__


def _structured_json_mode_instruction(
    *,
    output_model: type[BaseModel],
    output_json_schema: str,
) -> str:
    return (
        "Return JSON only. Do not include markdown fences, comments, or explanatory text.\n"
        "The JSON response must validate against the schema below.\n"
        f"Schema name: {output_model.__name__}\n"
        f"Output JSON schema:\n{output_json_schema}"
    )


def _structured_retry_instruction(
    *,
    output_model: type[BaseModel],
    error: Exception,
    attempt: int,
    max_attempts: int,
    output_json_schema: Any,
) -> str:
    return (
        "The previous structured JSON output failed schema validation.\n"
        "Regenerate the full response as JSON only. Do not explain the error.\n"
        "You must obey every JSON schema constraint, including required fields, enum values, "
        "minItems, maxItems, field types, numeric ranges, and extra=forbid.\n"
        f"Schema name: {output_model.__name__}\n"
        f"Validation observation from attempt {attempt}/{max_attempts}:"
        f"\n{type(error).__name__}: {error}\n\n"
        f"Output JSON schema:\n{output_json_schema}"
    )

