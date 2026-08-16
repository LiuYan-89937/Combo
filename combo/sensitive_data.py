from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit


_SENSITIVE_NAME = re.compile(
    r"(?i)(?:^|[_-])(api[_-]?key|authorization|access[_-]?token|refresh[_-]?token|secret|password)(?:$|[_-])"
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(api[_-]?key|authorization|access[_-]?token|refresh[_-]?token|secret|password)"
    r"\s*[:=]\s*[^\s,;]+"
)
_HTTP_URL = re.compile(r"https?://[^\s<>'\"]+")


def redact_sensitive_text(value: object) -> str:
    text = str(value)
    text = _SENSITIVE_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    return _HTTP_URL.sub(_redact_url_match, text)


def redact_sensitive_value(value: Any, *, field_name: str | None = None) -> Any:
    if field_name is not None and _SENSITIVE_NAME.search(field_name):
        return "[redacted]"
    if isinstance(value, dict):
        return {
            str(key): redact_sensitive_value(item, field_name=str(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_value(item) for item in value)
    if isinstance(value, str):
        return redact_sensitive_text(value)
    return value


def _redact_url_match(match: re.Match[str]) -> str:
    raw = match.group(0)
    trailing = ""
    while raw and raw[-1] in ").,]}":
        trailing = raw[-1] + trailing
        raw = raw[:-1]
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return "[redacted-url]" + trailing
    if not parsed.query:
        return raw + trailing
    redacted = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "[redacted]", parsed.fragment))
    return redacted + trailing
