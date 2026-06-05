from __future__ import annotations

from pathlib import Path

from agent_factory.runtime_contracts.builder import RuntimeBuildContext


def resolve_package_runtime_path(context: RuntimeBuildContext, value: str, *, field_path: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{field_path} must not be empty")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = context.package_root / candidate
    resolved = candidate.resolve()
    package_root = context.package_root.resolve()
    try:
        resolved.relative_to(package_root)
    except ValueError as exc:
        raise ValueError(
            f"{field_path} must resolve inside the package workspace; got {raw!r}. "
            "Use a package-relative .agent_runtime/... path."
        ) from exc
    return resolved


def package_runtime_path_text(context: RuntimeBuildContext, value: str, *, field_path: str) -> str:
    return str(resolve_package_runtime_path(context, value, field_path=field_path))
