from __future__ import annotations

from typing import Any

from combo.dynamic_runtime.capability_catalog_runtime import CapabilityCatalogRuntime
from combo.tooling.envelope import tool_envelope


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
    else:
        raise ValueError("capability action must be search or list_active")
    return tool_envelope(output, summary=f"capability {action} completed")
