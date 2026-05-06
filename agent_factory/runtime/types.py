from __future__ import annotations

from pydantic import ConfigDict

from agent_factory.core.types import JsonDumpMixin


class RuntimeTokenUsage(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


class RuntimeErrorInfo(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    type: str
    message: str
    status_code: int | None = None
    retryable: bool = False
    provider_error_code: str | None = None
