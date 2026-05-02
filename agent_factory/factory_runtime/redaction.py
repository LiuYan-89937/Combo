from __future__ import annotations

from typing import Any

SENSITIVE_FIELD_NAMES = {
    "api_key",
    "secret",
    "authorization",
    "auth_header",
    "tool_auth_token",
}


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in SENSITIVE_FIELD_NAMES:
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value
