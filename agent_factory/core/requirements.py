from __future__ import annotations


_INPUT_MARKERS = {"/done", "/end", "/cancel", "/abort"}


def sanitize_requirement_text(text: str) -> str:
    """Normalize user requirement text before it enters Factory production."""

    lines = []
    for line in text.splitlines():
        if line.strip().lower() in _INPUT_MARKERS:
            continue
        lines.append(line)
    return "\n".join(lines).strip()
