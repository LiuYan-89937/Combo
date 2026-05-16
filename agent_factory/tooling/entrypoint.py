from __future__ import annotations

import importlib
import importlib.util
import inspect
from pathlib import Path
from types import ModuleType
from typing import Any, Callable
import uuid


class ToolEntrypointError(ValueError):
    pass


class ToolEntrypointLoader:
    def __init__(self, *, package_root: str | Path | None = None) -> None:
        self.package_root = Path(package_root).resolve() if package_root else None

    def load(self, entrypoint: str) -> Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]:
        target, function_name = _split_entrypoint(entrypoint)
        errors: list[str] = []
        if self.package_root is not None:
            try:
                function = self._load_package_relative(target, function_name)
                return _validate_function(function, entrypoint)
            except ToolEntrypointError as exc:
                errors.append(str(exc))
        try:
            function = self._load_import_path(target, function_name)
            return _validate_function(function, entrypoint)
        except ToolEntrypointError as exc:
            errors.append(str(exc))
        raise ToolEntrypointError("; ".join(errors) if errors else f"cannot load entrypoint: {entrypoint}")

    def _load_package_relative(self, target: str, function_name: str) -> Callable[..., Any]:
        if self.package_root is None:
            raise ToolEntrypointError("package root is not configured")
        path = (self.package_root / target).resolve()
        try:
            path.relative_to(self.package_root)
        except ValueError as exc:
            raise ToolEntrypointError(f"entrypoint escapes package root: {target}") from exc
        if not path.exists() or not path.is_file():
            raise ToolEntrypointError(f"package entrypoint file does not exist: {target}")
        if path.suffix != ".py":
            raise ToolEntrypointError(f"package entrypoint must be a Python file: {target}")
        module = _module_from_path(path)
        return _function_from_module(module, function_name)

    def _load_import_path(self, target: str, function_name: str) -> Callable[..., Any]:
        try:
            module = importlib.import_module(target)
        except Exception as exc:
            raise ToolEntrypointError(f"cannot import module {target}: {exc}") from exc
        return _function_from_module(module, function_name)


def _split_entrypoint(entrypoint: str) -> tuple[str, str]:
    if ":" not in entrypoint:
        raise ToolEntrypointError("entrypoint must use '<path_or_module>:<function>'")
    target, function_name = entrypoint.rsplit(":", 1)
    target = target.strip()
    function_name = function_name.strip()
    if not target or not function_name:
        raise ToolEntrypointError("entrypoint target and function must be non-empty")
    return target, function_name


def _module_from_path(path: Path) -> ModuleType:
    module_name = f"agent_factory_dynamic_tool_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ToolEntrypointError(f"cannot create import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ToolEntrypointError(f"cannot load package entrypoint {path}: {exc}") from exc
    return module


def _function_from_module(module: ModuleType, function_name: str) -> Callable[..., Any]:
    function = getattr(module, function_name, None)
    if not callable(function):
        raise ToolEntrypointError(f"entrypoint function is not callable: {function_name}")
    return function


def _validate_function(
    function: Callable[..., Any],
    entrypoint: str,
) -> Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]:
    if inspect.iscoroutinefunction(function):
        raise ToolEntrypointError(f"tool entrypoint cannot be async: {entrypoint}")
    signature = inspect.signature(function)
    parameters = signature.parameters
    if "arguments" not in parameters or "resources" not in parameters:
        raise ToolEntrypointError("tool entrypoint must accept arguments and resources parameters")
    return function  # type: ignore[return-value]
