from __future__ import annotations

import asyncio

import httpx
from pydantic import ValidationError

from combo.exception_details import exception_chain
from combo.models.errors import model_provider_failure
from combo.runtime_protocol.errors import RuntimeFailure
from combo.runtime_protocol.interruption import (
    RuntimeModelGenerationInterrupted,
    RuntimeToolExecutionCancelled,
)


class RuntimeFailureError(RuntimeError):
    """Carry a serialized failure across boundaries that cannot retain exceptions."""

    def __init__(self, failure: RuntimeFailure) -> None:
        super().__init__(failure.details.get("message") or failure.code)
        self.failure = failure


def runtime_failure_from_exception(exc: BaseException) -> RuntimeFailure:
    chain = tuple(exception_chain(exc))
    for cause in chain:
        if isinstance(cause, RuntimeFailureError):
            return cause.failure
    details = {
        "exception_type": type(exc).__name__,
        "message": str(exc).strip() or type(exc).__name__,
        "causes": [
            {"exception_type": type(cause).__name__, "message": str(cause)}
            for cause in chain[1:]
        ],
    }
    if any(isinstance(cause, (
        asyncio.CancelledError, RuntimeModelGenerationInterrupted, RuntimeToolExecutionCancelled,
    )) for cause in chain):
        return RuntimeFailure(
            code="runtime_cancelled", category="cancelled", terminal_status="cancelled",
            user_message_key="runtime.cancelled", details=details,
        )
    for cause in chain:
        provider = model_provider_failure(cause)
        if provider is not None:
            return RuntimeFailure(
                code=provider.code, category=provider.category, retryable=provider.retryable,
                user_message_key=f"runtime.error.{provider.code}",
                details={**details, **provider.details},
            )
        if isinstance(cause, ValidationError):
            details["validation_errors"] = cause.errors(
                include_url=False, include_input=False, include_context=False,
            )
    if any(isinstance(cause, (TimeoutError, httpx.TimeoutException)) for cause in chain):
        code, category, retryable = "runtime_timeout", "timeout", True
    elif any(isinstance(cause, (ConnectionError, httpx.TransportError)) for cause in chain):
        code, category, retryable = "runtime_connection_failed", "unavailable", True
    elif any(isinstance(cause, (ValueError, LookupError)) for cause in chain):
        code, category, retryable = "runtime_validation_failed", "validation", False
    else:
        code, category, retryable = "runtime_internal_error", "internal", False
    return RuntimeFailure(
        code=code, category=category, retryable=retryable,
        user_message_key=f"runtime.error.{code}", details=details,
    )
