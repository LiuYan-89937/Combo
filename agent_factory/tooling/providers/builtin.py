from __future__ import annotations

import os
from collections.abc import Iterable

from agent_factory.paths import factory_artifact_path
from agent_factory.runtime_attachments import ATTACHMENT_INPUT_DIR
from agent_factory.runtime_defaults import (
    DEFAULT_BUILTIN_ALLOW_EXTERNAL_PATHS,
    DEFAULT_BUILTIN_WORKSPACE_ROOT,
)
from agent_factory.tooling.builtins.aliases import canonical_builtin_tool_ids
from agent_factory.tooling.builtins.browser.runtime import (
    BROWSER_RUNTIME_RESOURCE,
    default_browser_runtime,
)
from agent_factory.tooling.builtins.registry import (
    get_always_available_system_tool_ids,
    get_builtin_tool_ids,
    get_builtin_tool_specs,
    get_contextual_system_tool_ids,
    get_read_only_system_tool_ids,
)
from agent_factory.tooling.providers.base import ToolProviderContext, ToolProviderResult
from agent_factory.tooling.skillhub import (
    SKILLHUB_RUNTIME_RESOURCE,
    build_skillhub_runtime_resource,
)


class BuiltinToolProvider:
    provider_id = "builtin"

    def __init__(self, *, tool_ids: Iterable[str] | None = None) -> None:
        self._tool_ids = set(canonical_builtin_tool_ids(tool_ids or []))

    def discover(self, context: ToolProviderContext) -> ToolProviderResult:
        known_ids = set(get_builtin_tool_ids())
        unknown_ids = sorted(self._tool_ids - known_ids)
        if unknown_ids:
            raise ValueError("unknown builtin tool ids: " + ", ".join(unknown_ids))
        read_only_ids = get_read_only_system_tool_ids()
        specs = [
            spec.model_copy(
                update={
                    "permission_scope": "system",
                    "permission_tags": _permission_tags(spec.id, read_only_ids),
                }
            )
            for spec in get_builtin_tool_specs()
        ]
        include_browser = not self._tool_ids or any(
            tool_id.startswith("browser_") for tool_id in self._tool_ids
        )
        runtime_resources = _runtime_resources(context, include_browser=include_browser)
        if SKILLHUB_RUNTIME_RESOURCE not in runtime_resources:
            specs = [spec for spec in specs if spec.id != "skillhub"]
        if self._tool_ids:
            always_available = get_always_available_system_tool_ids()
            contextual = get_contextual_system_tool_ids()
            specs = [
                spec
                for spec in specs
                if spec.id in self._tool_ids or spec.id in always_available or spec.id in contextual
            ]
        always_available = get_always_available_system_tool_ids()
        contextual = get_contextual_system_tool_ids()
        return ToolProviderResult(
            tool_specs=specs,
            system_tool_ids=[spec.id for spec in specs if spec.id in always_available or spec.id in contextual],
            runtime_resources=runtime_resources,
        )


def _permission_tags(tool_id: str, read_only_ids: set[str]) -> list[str]:
    return ["read_only"] if tool_id in read_only_ids else []


def _runtime_resources(
    context: ToolProviderContext,
    *,
    include_browser: bool,
) -> dict[str, object]:
    resources = dict(context.resources)
    root = str(resources.get("builtin_workspace_root") or DEFAULT_BUILTIN_WORKSPACE_ROOT)
    allow_external = bool(resources.get("builtin_allow_external_paths", DEFAULT_BUILTIN_ALLOW_EXTERNAL_PATHS))
    read_only_paths = _read_only_paths(resources, root=root)
    runtime_resources: dict[str, object] = {
        "filesystem": {
            "root": root,
            "allow_external": allow_external,
            "read_only_paths": read_only_paths,
        },
        "process_runtime": {
            "root": root,
            "allow_external": allow_external,
            "read_only_paths": read_only_paths,
        },
        "background_task_root": os.getenv("AGENTFACTORY_BACKGROUND_TASK_ROOT")
        or str(factory_artifact_path("background_tasks")),
    }
    if include_browser:
        runtime_resources[BROWSER_RUNTIME_RESOURCE] = default_browser_runtime()
    skillhub = build_skillhub_runtime_resource(context.extension_root)
    if skillhub is not None:
        runtime_resources[SKILLHUB_RUNTIME_RESOURCE] = skillhub
    return runtime_resources


def _read_only_paths(resources: dict[str, object], *, root: str) -> list[str]:
    configured = resources.get("builtin_read_only_paths")
    values = (
        [str(item) for item in configured if isinstance(item, str) and item.strip()]
        if isinstance(configured, list)
        else []
    )
    default_input_path = f"{root.rstrip('/')}/{ATTACHMENT_INPUT_DIR}"
    return [*values, default_input_path]
