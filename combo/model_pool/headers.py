"""Custom credential request headers: built-in variables, templates, rendering.

A credential may carry a list of extra request headers that are applied to every
provider request made with that credential. Header values are templates that may
reference a small set of built-in variables:

- ``session_id``  the conversation session that triggered the request
- ``model_id``    the model pool profile that resolved the credential

Unknown variables are rejected at validation time. Variables that have no value
in the current context (for example a connection test, where there is no
conversation) fall back to the header's ``default_value``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Protocol

HEADER_NAME_RE = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")
_PLACEHOLDER_RE = re.compile(r"\$\{(?P<name>[a-z][a-z0-9_]*)\}")

SESSION_ID_VARIABLE = "session_id"
MODEL_ID_VARIABLE = "model_id"
BUILTIN_HEADER_VARIABLES: tuple[str, ...] = (SESSION_ID_VARIABLE, MODEL_ID_VARIABLE)


class CredentialHeaderLike(Protocol):
    name: str
    value: str
    default_value: str


def validate_header_name(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("custom header name must not be empty")
    if not HEADER_NAME_RE.fullmatch(text):
        raise ValueError(f"invalid custom header name: {text!r}")
    return text


def referenced_variables(template: str) -> list[str]:
    return [match.group("name") for match in _PLACEHOLDER_RE.finditer(str(template or ""))]


def validate_header_template(template: str) -> str:
    text = str(template or "")
    unknown = sorted({name for name in referenced_variables(text) if name not in BUILTIN_HEADER_VARIABLES})
    if unknown:
        raise ValueError(
            "unknown custom header variable(s): "
            + ", ".join(unknown)
            + "; supported: "
            + ", ".join(BUILTIN_HEADER_VARIABLES)
        )
    return text


def credential_header_variables(
    *,
    profile_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, str]:
    return {
        MODEL_ID_VARIABLE: str(profile_id or ""),
        SESSION_ID_VARIABLE: str(session_id or ""),
    }


def render_header_value(
    template: str,
    *,
    variables: Mapping[str, str] | None = None,
    default_value: str = "",
) -> str:
    context = variables or {}
    fallback = str(default_value or "")

    def _replace(match) -> str:
        return str(context.get(match.group("name")) or "") or fallback

    return _PLACEHOLDER_RE.sub(_replace, str(template or ""))


def render_credential_headers(
    headers: Iterable[CredentialHeaderLike] | None,
    *,
    variables: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Render configured headers into a plain name->value mapping.

    Headers that render to an empty value are dropped so a merely declared
    template never sends a blank header to the provider. Later entries win when
    the same header name is configured twice.
    """

    context = {key: str(value) for key, value in (variables or {}).items()}
    rendered: dict[str, str] = {}
    for header in headers or ():
        value = render_header_value(
            header.value,
            variables=context,
            default_value=header.default_value,
        )
        if value:
            rendered[header.name] = value
    return rendered
