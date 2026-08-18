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
    elif action == "search_mcp":
        raw_kinds = arguments.get("kinds") or []
        if not isinstance(raw_kinds, list):
            raise ValueError("kinds must be an array")
        output = {
            "action": action,
            "items": catalog.search_mcp(
                str(arguments.get("server_name") or ""),
                str(arguments.get("query") or ""),
                kinds=tuple(str(value) for value in raw_kinds),
                limit=int(arguments.get("limit", 10)),
            ),
        }
    elif action == "describe":
        output = {
            "action": action,
            "capability": catalog.describe(
                name=str(arguments.get("name") or ""),
                kind=_optional_text(arguments.get("kind")),
                server_name=_optional_text(arguments.get("server_name")),
            ),
        }
    else:
        raise ValueError("capability action must be search, search_mcp, describe, or list_active")
    return tool_envelope(output, summary=f"capability {action} completed")


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None
