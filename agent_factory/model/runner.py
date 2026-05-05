from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any, Literal

from pydantic import ConfigDict, Field

from agent_factory.core.types import JsonDumpMixin
from agent_factory.model.router import ModelRouter
from agent_factory.model.types import (
    LLMRequest,
    LLMResponse,
    ModelError,
    StructuredOutputResult,
)


class ModelCallTraceSpan(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    operation: str = "model.generate"
    provider: str = "unknown"
    model: str | None = None
    status: Literal["completed", "failed"] = "completed"
    attempt_count: int = 1
    duration_ms: int = 0
    error_type: str | None = None
    retryable: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelCallRunner:
    """Unified model-call safety layer for Factory and Agent runtime calls."""

    def __init__(
        self,
        router: ModelRouter,
        *,
        max_retries: int = 2,
        initial_backoff_seconds: float = 0.05,
    ) -> None:
        self.router = router
        self.max_retries = max_retries
        self.initial_backoff_seconds = initial_backoff_seconds
        self.last_span: ModelCallTraceSpan | None = None

    @classmethod
    def from_service(cls, service: Any) -> "ModelCallRunner":
        runner = getattr(service, "runner", None)
        if isinstance(runner, cls):
            return runner
        return cls(service.router)

    async def generate(
        self,
        request: LLMRequest,
        *,
        timeout_seconds: float | None = None,
        empty_content_retries: int = 1,
    ) -> LLMResponse:
        adapter = self.router.adapter_for()
        started = time.monotonic()
        response: LLMResponse | None = None
        error: ModelError | None = None
        attempt = 0
        retryable_errors = 0
        empty_responses = 0
        while True:
            attempt += 1
            try:
                if timeout_seconds is None:
                    response = await adapter.generate(request)
                else:
                    response = await asyncio.wait_for(
                        adapter.generate(request),
                        timeout=timeout_seconds,
                    )
            except TimeoutError:
                response = LLMResponse(
                    provider=getattr(adapter, "provider", "unknown"),
                    error=ModelError(
                        type="model_call_timeout",
                        message="Model call timed out.",
                        retryable=True,
                    ),
                )
            if response.error:
                error = _redacted_error(response.error)
                response = response.model_copy(update={"error": error})
                if not error.retryable or retryable_errors >= self.max_retries:
                    break
                retryable_errors += 1
            elif response.content.strip() or response.tool_call_proposals:
                error = None
                break
            else:
                error = ModelError(
                    type="empty_content",
                    message="Model returned empty content.",
                    retryable=True,
                )
                response = response.model_copy(update={"error": None})
                if empty_responses >= empty_content_retries:
                    break
                empty_responses += 1
            await asyncio.sleep(self.initial_backoff_seconds * (2 ** max(0, attempt - 1)))

        assert response is not None
        duration_ms = int((time.monotonic() - started) * 1000)
        self.last_span = ModelCallTraceSpan(
            provider=response.provider,
            model=response.model or request.model,
            status="failed" if error and response.error else "completed",
            attempt_count=attempt,
            duration_ms=duration_ms,
            error_type=error.type if error and response.error else None,
            retryable=bool(error.retryable) if error and response.error else False,
            metadata=_redact_secrets(request.metadata),
        )
        return response

    async def generate_structured(
        self,
        request: LLMRequest,
        *,
        schema: dict[str, Any] | None = None,
        schema_name: str | None = None,
        strict: bool = True,
        max_empty_content_retries: int = 2,
    ) -> StructuredOutputResult:
        json_schema = schema or request.json_schema
        structured_request = request.model_copy(
            update={
                "response_format": "json_schema" if json_schema else "json_object",
                "json_schema": json_schema,
                "json_schema_name": schema_name or request.json_schema_name,
                "json_schema_strict": strict if schema is not None else request.json_schema_strict,
            }
        )
        response = await self.generate(
            structured_request,
            empty_content_retries=max_empty_content_retries,
        )
        if response.error:
            return StructuredOutputResult(response=response, error=response.error)
        if not response.content.strip():
            error = ModelError(
                type="structured_output_empty_content",
                message="Model returned empty structured content after retry.",
                retryable=True,
            )
            return StructuredOutputResult(response=response, error=error)
        return _parse_structured_response(response)


def _redacted_error(error: ModelError) -> ModelError:
    data = error.model_dump(mode="json")
    data["message"] = str(_redact_secrets({"message": error.message})["message"])
    return ModelError.model_validate(data)


def _redact_secrets(value: Any) -> Any:
    sensitive = re.compile(r"(?i)(api[_-]?key|authorization|secret|token|jwt)")
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if sensitive.search(str(key)) else _redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    if isinstance(value, str):
        return re.sub(
            r"(?i)(api[_-]?key|authorization|secret|token|jwt)\s*[:=]\s*[^\s,;]+",
            r"\1=[REDACTED]",
            value,
        )
    return value


def _extract_json_candidate(content: str) -> str | None:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", content, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        content = fenced.group(1)
    content = content.strip()
    for opener, closer in [("{", "}"), ("[", "]")]:
        start = content.find(opener)
        if start < 0:
            continue
        depth = 0
        in_string = False
        escape = False
        for index, char in enumerate(content[start:], start=start):
            if escape:
                escape = False
                continue
            if char == "\\":
                escape = True
                continue
            if char == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    return content[start : index + 1]
    return None


def _parse_structured_response(response: LLMResponse) -> StructuredOutputResult:
    try:
        parsed = json.loads(response.content)
    except json.JSONDecodeError:
        candidate = _extract_json_candidate(response.content)
        if candidate is None:
            error = ModelError(
                type="structured_output_parse_error",
                message="Model response was not valid JSON.",
            )
            return StructuredOutputResult(response=response, error=error)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            error = ModelError(
                type="structured_output_parse_error",
                message="Model response was not valid JSON.",
            )
            return StructuredOutputResult(response=response, error=error)
    if not isinstance(parsed, (dict, list)):
        error = ModelError(
            type="structured_output_type_error",
            message="Model structured output must be a JSON object or array.",
        )
        return StructuredOutputResult(response=response, error=error)
    return StructuredOutputResult(data=parsed, response=response)
