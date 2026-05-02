from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    NOT_IMPLEMENTED = "not_implemented"
    VALIDATION_FAILED = "validation_failed"
    INVALID_ARGUMENT = "invalid_argument"
    INTERNAL_ERROR = "internal_error"


class AgentFactoryError(Exception):
    """Structured error used across application services and CLI."""

    def __init__(
        self,
        code: ErrorCode | str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = ErrorCode(code) if not isinstance(code, ErrorCode) else code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": self.details,
        }
