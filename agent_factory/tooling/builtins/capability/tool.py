from __future__ import annotations

from typing import Any

from agent_factory.dynamic_runtime.capability_catalog_runtime import CapabilityCatalogRuntime
from agent_factory.tooling.envelope import tool_envelope


CAPABILITY_CATALOG_RESOURCE = "capability_catalog"


def run(arguments: dict[str, Any], resources: dict[str, Any]) -> dict[str, Any]:
    catalog = resources.get(CAPABILITY_CATALOG_RESOURCE)
    if not isinstance(catalog, CapabilityCatalogRuntime):
        raise RuntimeError("capability catalog runtime is not configured")
    action = str(arguments.get("action") or "").strip()
    if action == "list_active":
        output = {"action": action, "capabilities": catalog.list_active()}
    elif action == "search":
        output = {
            "action": action,
            "capabilities": catalog.search(
                str(arguments.get("query") or ""),
                limit=int(arguments.get("limit", 10)),
            ),
        }
    elif action == "inspect":
        output = {
            "action": action,
            "capability": catalog.inspect(str(arguments.get("capability_id") or "")),
        }
    elif action == "prepare":
        values = arguments.get("capability_ids")
        if not isinstance(values, list):
            raise ValueError("capability_ids must be an array")
        output = {
            "action": action,
            "preparation": catalog.prepare(tuple(str(value) for value in values)),
        }
    else:
        raise ValueError("capability action must be search, inspect, prepare, or list_active")
    return tool_envelope(output, summary=f"capability {action} completed")
