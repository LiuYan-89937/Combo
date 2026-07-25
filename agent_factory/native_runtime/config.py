"""Configuration for native runtime mode selection."""

import os


def is_native_runtime_enabled() -> bool:
    """
    Check if native runtime mode is enabled (no Docker).

    Set AGENTFACTORY_NATIVE_RUNTIME=1 to enable native mode.
    """
    value = os.environ.get("AGENTFACTORY_NATIVE_RUNTIME", "").strip().lower()
    return value in ("1", "true", "yes", "on")


def should_use_docker() -> bool:
    """Check if Docker mode should be used (default: true for backward compatibility)."""
    return not is_native_runtime_enabled()
