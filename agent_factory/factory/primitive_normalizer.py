from __future__ import annotations

from copy import deepcopy
from typing import Any
import re


SENSITIVE_FIELD_NAMES = (
    "api_key",
    "secret",
    "authorization",
    "auth_header",
    "tool_auth_token",
)
_SENSITIVE_SET = set(SENSITIVE_FIELD_NAMES)


def normalize_primitives_candidate(raw_data: object) -> dict[str, Any] | list[Any] | None:
    """Apply deterministic Factory-owned fixes before Pydantic validation.

    The model owns the draft content, but Factory owns invariant safety policy. In
    particular, sensitive observability fields must never be explicitly allowed
    and must always remain forbidden.
    """

    if isinstance(raw_data, list):
        return deepcopy(raw_data)
    if not isinstance(raw_data, dict):
        return None

    data = deepcopy(raw_data)
    observability = data.get("observability")
    if isinstance(observability, dict):
        _normalize_observability(observability)
    return data


def _normalize_observability(observability: dict[str, Any]) -> None:
    extra_forbidden = []
    for value in observability.get("forbidden_fields") or []:
        canonical = _canonical_field_name(value)
        if canonical and canonical not in _SENSITIVE_SET:
            extra_forbidden.append(str(value).strip())

    observability["forbidden_fields"] = [
        *SENSITIVE_FIELD_NAMES,
        *_dedupe(extra_forbidden),
    ]
    allowed = observability.get("allowed_sensitive_fields") or []
    observability["allowed_sensitive_fields"] = [
        str(value).strip()
        for value in allowed
        if _canonical_field_name(value) not in _SENSITIVE_SET
    ]


def _canonical_field_name(value: object) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9_]+", "_", text).strip("_")
    return text


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
