from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from openai import APIConnectionError, APIResponseValidationError, APIStatusError, APITimeoutError


class ModelConfigurationError(RuntimeError):
    """The configured model cannot be resolved or used for this operation."""


@dataclass(frozen=True, slots=True)
class ModelProviderFailure:
    code: str
    category: Literal["provider", "unavailable", "timeout", "dependency", "conflict"]
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)


def model_provider_failure(exc: BaseException) -> ModelProviderFailure | None:
    """Interpret SDK error types and HTTP metadata without guessing from text."""
    if isinstance(exc, ModelConfigurationError):
        return ModelProviderFailure("model_configuration_failed", "dependency")
    if isinstance(exc, APITimeoutError):
        return ModelProviderFailure("model_timeout", "timeout", retryable=True)
    if isinstance(exc, APIConnectionError):
        return ModelProviderFailure("model_connection_failed", "unavailable", retryable=True)
    if isinstance(exc, APIResponseValidationError):
        return ModelProviderFailure("model_response_invalid", "provider", details={
            "http_status": exc.status_code,
            "provider_request_id": exc.response.headers.get("x-request-id"),
        })
    if not isinstance(exc, APIStatusError):
        return None

    status = exc.status_code
    body = exc.body
    error = body.get("error", body) if isinstance(body, dict) else body
    upstream = {
        key: value
        for key in ("type", "code", "param", "message")
        if isinstance(error, dict) and (value := error.get(key)) is not None
        and isinstance(value, (str, int, float, bool))
    }
    details: dict[str, Any] = {
        "http_status": status,
        "provider_request_id": exc.request_id,
        "upstream_error": upstream,
    }
    retry_after = exc.response.headers.get("retry-after")
    if retry_after is not None:
        details["retry_after"] = retry_after
    if status == 408:
        code, category, retryable = "model_timeout", "timeout", True
    elif status == 409:
        code, category, retryable = "model_request_conflict", "conflict", True
    elif status >= 500 or (status == 429 and upstream.get("type") == "server_error"):
        code, category, retryable = "model_unavailable", "unavailable", True
    elif status == 429:
        code, category, retryable = "model_rate_limited", "provider", True
    elif status in (401, 403):
        code, category, retryable = "model_authentication_failed", "provider", False
    else:
        code, category, retryable = "model_request_rejected", "provider", False

    retry_directive = exc.response.headers.get("x-should-retry")
    if retry_directive in ("true", "false"):
        retryable = retry_directive == "true"
    return ModelProviderFailure(code, category, retryable, details)
