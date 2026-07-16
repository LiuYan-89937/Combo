from __future__ import annotations

from pathlib import Path

from agent_factory.runtime_defaults import DEFAULT_BUILTIN_WORKSPACE_ROOT


def workspace_path_candidate(value: str, *, root: Path) -> Path:
    """Resolve relative paths and the stable virtual workspace alias against a runtime root."""
    requested = Path(value).expanduser()
    if not requested.is_absolute():
        return root / requested

    virtual_root = Path(DEFAULT_BUILTIN_WORKSPACE_ROOT)
    try:
        relative = requested.relative_to(virtual_root)
    except ValueError:
        return requested
    return root / relative
