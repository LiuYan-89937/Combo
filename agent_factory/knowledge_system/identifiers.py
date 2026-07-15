from __future__ import annotations

import re


SOURCE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_INVALID_SOURCE_ID_CHARACTER_RE = re.compile(r"[^a-z0-9]+")
_REPEATED_SEPARATOR_RE = re.compile(r"_+")


def build_source_id(value: str, *, fallback: str, suffix: str | None = None) -> str:
    """Build an ASCII snake_case identifier accepted by knowledge manifests."""
    base = _source_id_fragment(value) or _source_id_fragment(fallback)
    if not base:
        raise ValueError("source_id fallback must contain ASCII letters or digits")
    if not base[0].isalpha():
        base = f"source_{base}"

    suffix_fragment = _source_id_fragment(suffix or "")
    reserved = len(suffix_fragment) + 1 if suffix_fragment else 0
    available_base_length = 64 - reserved
    if available_base_length < 1:
        raise ValueError("source_id suffix is too long")
    base = base[:available_base_length].rstrip("_")
    source_id = f"{base}_{suffix_fragment}" if suffix_fragment else base
    if len(source_id) < 2:
        source_id = f"{source_id}_source"
    if not SOURCE_ID_RE.fullmatch(source_id):
        raise ValueError("unable to build a valid knowledge source_id")
    return source_id


def _source_id_fragment(value: str) -> str:
    lowered = str(value or "").strip().lower()
    cleaned = _INVALID_SOURCE_ID_CHARACTER_RE.sub("_", lowered)
    return _REPEATED_SEPARATOR_RE.sub("_", cleaned).strip("_")
