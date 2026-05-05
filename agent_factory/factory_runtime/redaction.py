from __future__ import annotations

from typing import Any

SENSITIVE_FIELD_NAMES = {
    "api_key",
    "secret",
    "authorization",
    "auth_header",
    "tool_auth_token",
}
SENSITIVE_KEY_MARKERS = {
    "api_key",
    "secret",
    "token",
    "jwt",
    "credential",
    "authorization",
    "auth_header",
    "appcode",
    "password",
}


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            lowered = key.lower()
            if lowered in SENSITIVE_FIELD_NAMES or any(marker in lowered for marker in SENSITIVE_KEY_MARKERS):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = redact_secrets(item)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    return value
