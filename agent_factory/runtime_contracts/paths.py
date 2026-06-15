from __future__ import annotations

from pathlib import Path

from agent_factory.runtime_contracts.builder import RuntimeBuildContext


def resolve_package_runtime_path(context: RuntimeBuildContext, value: str, *, field_path: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError(f"{field_path} must not be empty")
    runtime_relative = _runtime_relative_path(raw)
    if runtime_relative is not None and context.runtime_root is not None:
        return (context.runtime_root / runtime_relative).resolve()
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


def _runtime_relative_path(value: str) -> Path | None:
    marker = ".agent_runtime"
    if value == marker:
        return Path()
    prefix = marker + "/"
    if value.startswith(prefix):
        return Path(value.removeprefix(prefix))
    return None
