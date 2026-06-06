from __future__ import annotations

from typing import Any

from agent_factory.tooling.skills.skill_tool_protocol import (
    limit_value,
    persist_registry,
    registry_from_resources,
    repair_resource_mode,
    required_string,
    resource_mode,
    resource_paths,
)


class SkillToolActionRunner:
    def __init__(self, resources: dict[str, Any]) -> None:
        self.resources = resources
        self.registry = registry_from_resources(resources)

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = str(arguments.get("action") or "").strip()
        if action == "list":
            return self._list(action)
        if action == "search":
            return self._search(action, arguments)
        if action == "list_loaded":
            return self._list_loaded(action, arguments)
        name = required_string(arguments, "name")
        if action == "describe":
            return self._describe(action, name, arguments)
        if action == "load":
            return self._load(action, name, arguments)
        if action == "read_repair_resources":
            return self._read_repair_resources(action, name, arguments)
        if action == "read_resource":
            return self._read_resource(action, name, arguments)
        raise ValueError("action must be one of: list, search, describe, load, list_loaded, read_resource, read_repair_resources")

    def _list(self, action: str) -> dict[str, Any]:
        return _output(
            action=action,
            message="Available skills metadata.",
            skills=self.registry.list_metadata(),
        )

    def _search(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        query = required_string(arguments, "query")
        limit = limit_value(arguments.get("limit"))
        return _output(
            action=action,
            message=f"Skill search results for: {query}",
            skills=self.registry.search(query, limit=limit),
        )

    def _list_loaded(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        current_system = required_string(arguments, "current_system")
        return _output(
            action=action,
            message=f"Loaded skill state for system: {current_system}",
            loaded_state=self.registry.list_loaded(current_system=current_system),
        )

    def _describe(self, action: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        current_system = required_string(arguments, "current_system")
        described = self.registry.describe(name, current_system=current_system)
        persist_registry(self.resources, self.registry)
        return _output(
            action=action,
            message=f"Skill described: {name}",
            skill=described,
            loaded_state=self.registry.list_loaded(current_system=current_system),
        )

    def _load(self, action: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        current_system = required_string(arguments, "current_system")
        reason = required_string(arguments, "reason")
        loaded = self.registry.load(name, current_system=current_system, reason=reason)
        persist_registry(self.resources, self.registry)
        return _output(
            action=action,
            message=f"Skill loaded: {name}",
            skill=loaded.model_dump(mode="json"),
            loaded_state=self.registry.list_loaded(current_system=current_system),
        )

    def _read_repair_resources(self, action: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        current_system = required_string(arguments, "current_system")
        paths = resource_paths(arguments.get("paths"))
        self.registry.describe(name, current_system=current_system)
        persist_registry(self.resources, self.registry)
        return _output(
            action=action,
            message=f"Skill repair resources loaded: {name}",
            resource={
                "name": name,
                "resources": [
                    self.registry.read_resource(
                        name,
                        path,
                        current_system=current_system,
                        mode=repair_resource_mode(path),
                    )
                    for path in paths
                ],
            },
            loaded_state=self.registry.list_loaded(current_system=current_system),
        )

    def _read_resource(self, action: str, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        current_system = required_string(arguments, "current_system")
        path = required_string(arguments, "path")
        mode = resource_mode(arguments.get("mode"))
        pointer = str(arguments.get("pointer") or "").strip()
        return _output(
            action=action,
            message=f"Skill resource loaded: {name}/{path} ({mode})",
            resource=self.registry.read_resource(
                name,
                path,
                current_system=current_system,
                mode=mode,
                pointer=pointer,
            ),
            loaded_state=self.registry.list_loaded(current_system=current_system),
        )


def _output(
    *,
    action: str,
    message: str,
    skills: list[dict[str, Any]] | None = None,
    skill: dict[str, Any] | None = None,
    resource: dict[str, Any] | None = None,
    loaded_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "action": action,
        "message": message,
        "skills": skills or [],
        "skill": skill,
        "resource": resource,
        "loaded_state": loaded_state,
    }
