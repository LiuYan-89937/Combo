from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.tooling.builtins.registry import get_builtin_tool_specs
from agent_factory.tooling.spec import ToolSpec


class CapabilityItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source: str
    description: str = ""
    runtime_inheritable: bool = False


class SchedulerCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schedule_types: list[str] = Field(default_factory=lambda: ["cron", "interval", "date"])
    target_types: list[str] = Field(default_factory=lambda: ["graph_run", "script_run", "tool_call"])
    feedback_modes: list[str] = Field(default_factory=lambda: ["llm_summary"])
    failure_actions: list[str] = Field(default_factory=lambda: ["pause"])


class CapabilityInventory(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = "capability_inventory.v0"
    manufacturing_tools: list[CapabilityItem] = Field(default_factory=list)
    factory_extension_tools: list[CapabilityItem] = Field(default_factory=list)
    runtime_builtin_candidates: list[CapabilityItem] = Field(default_factory=list)
    inherited_extension_candidates: list[CapabilityItem] = Field(default_factory=list)
    scheduler_capabilities: SchedulerCapabilities = Field(default_factory=SchedulerCapabilities)
    boundary_note: str = (
        "Capabilities not present in confirmed runtime tools, inherited extension candidates, "
        "or verified package tools are not supported yet. Do not promise them, and do not ask "
        "the user for accounts, tokens, or configuration for them as if they already exist."
    )


def build_capability_inventory(
    *,
    manufacturing_specs: list[ToolSpec],
    extension_specs: list[ToolSpec],
) -> CapabilityInventory:
    manufacturing_tools = [
        _tool_item(spec, source="manufacturing", runtime_inheritable=False)
        for spec in manufacturing_specs
    ]
    factory_extension_tools = [
        _tool_item(spec, source=_extension_source(spec), runtime_inheritable=False)
        for spec in extension_specs
    ]
    runtime_builtin_candidates = [
        _tool_item(spec, source="runtime_builtin_candidate", runtime_inheritable=True)
        for spec in get_builtin_tool_specs()
    ]
    inherited_extension_candidates = [
        _tool_item(spec, source=_extension_source(spec), runtime_inheritable=True)
        for spec in extension_specs
    ]
    return CapabilityInventory(
        manufacturing_tools=_dedupe_items(manufacturing_tools),
        factory_extension_tools=_dedupe_items(factory_extension_tools),
        runtime_builtin_candidates=_dedupe_items(runtime_builtin_candidates),
        inherited_extension_candidates=_dedupe_items(inherited_extension_candidates),
    )


def render_capability_inventory(inventory: dict[str, Any] | CapabilityInventory, *, package_root: str | Path) -> str:
    value = inventory if isinstance(inventory, CapabilityInventory) else CapabilityInventory.model_validate(inventory)
    root = Path(package_root).expanduser().resolve()
    lines = [
        "Runtime Capability Inventory:",
        "Boundary rule: before asking the user for a resource or account, check this inventory. "
        "If a capability is not listed as a confirmed runtime capability, inherited extension candidate, "
        "or verified package tool, describe it as not yet confirmed/supported instead of asking for its credentials.",
        "",
        "Manufacturing tools (create-agent only; do not expose by default to the produced Agent):",
        *_item_lines(value.manufacturing_tools, empty="none"),
        "",
        "Factory extension tools currently available during manufacturing:",
        *_item_lines(value.factory_extension_tools, empty="none"),
        "",
        "Runtime builtin candidates (usable only if the produced package declares them in contracts/tools.json):",
        *_item_lines(value.runtime_builtin_candidates, empty="none"),
        "",
        "Inherited MCP/Skill extension candidates (candidate only until tools_system chooses to inherit them):",
        *_item_lines(value.inherited_extension_candidates, empty="none"),
        "",
        "Current package runtime tool facts:",
        *_current_runtime_tool_lines(root),
        "",
        "Current resource facts summary (secrets redacted):",
        *_resource_fact_lines(root),
        "",
        "Scheduler capabilities:",
        f"- schedule_types={value.scheduler_capabilities.schedule_types}",
        f"- target_types={value.scheduler_capabilities.target_types}",
        f"- feedback_modes={value.scheduler_capabilities.feedback_modes}",
        f"- failure_actions={value.scheduler_capabilities.failure_actions}",
        "",
        f"Boundary note: {value.boundary_note}",
    ]
    return "\n".join(lines)


def _tool_item(spec: ToolSpec, *, source: str, runtime_inheritable: bool) -> CapabilityItem:
    return CapabilityItem(
        id=spec.id,
        source=source,
        description=_compact(spec.description, limit=140),
        runtime_inheritable=runtime_inheritable,
    )


def _extension_source(spec: ToolSpec) -> str:
    if spec.entrypoint.startswith("mcp:"):
        return "mcp_extension_candidate"
    return "skill_or_extension_candidate"


def _dedupe_items(items: list[CapabilityItem]) -> list[CapabilityItem]:
    seen: set[str] = set()
    result: list[CapabilityItem] = []
    for item in sorted(items, key=lambda value: value.id):
        if item.id in seen:
            continue
        seen.add(item.id)
        result.append(item)
    return result


def _item_lines(items: list[CapabilityItem], *, empty: str) -> list[str]:
    if not items:
        return [f"- {empty}"]
    lines: list[str] = []
    for item in items[:24]:
        suffix = "runtime-inheritable candidate" if item.runtime_inheritable else "manufacturing only"
        description = f" | {item.description}" if item.description else ""
        lines.append(f"- {item.id} [{item.source}; {suffix}]{description}")
    if len(items) > 24:
        lines.append(f"- ... {len(items) - 24} more")
    return lines


def _current_runtime_tool_lines(root: Path) -> list[str]:
    lines: list[str] = []
    tools_contract = _read_json_object(root / "contracts" / "tools.json")
    config = tools_contract.get("config") if isinstance(tools_contract.get("config"), dict) else {}
    if tools_contract:
        builtin_enabled = bool(config.get("builtin_tools_enabled", True))
        builtin_ids = config.get("builtin_tool_ids")
        if builtin_enabled:
            if isinstance(builtin_ids, list) and builtin_ids:
                lines.append(f"- declared_builtin_tools={[_compact(item, limit=80) for item in builtin_ids]}")
            else:
                lines.append("- declared_builtin_tools=all implemented builtin tools")
        else:
            lines.append("- declared_builtin_tools=disabled")
        lines.append(f"- package_tools_enabled={bool(config.get('package_tools_enabled', True))}")
        lines.append(f"- instance_extensions_enabled={bool(config.get('instance_extensions_enabled', True))}")
    else:
        lines.append("- contracts/tools.json not present yet")
    package_tools = _package_tool_lines(root)
    lines.extend(package_tools if package_tools else ["- verified package tools: none"])
    return lines


def _package_tool_lines(root: Path) -> list[str]:
    tools_root = root / "tools"
    if not tools_root.is_dir():
        return []
    lines: list[str] = []
    for manifest_path in sorted(tools_root.glob("*/manifest.json"))[:24]:
        payload = _read_json_object(manifest_path)
        tool_id = str(payload.get("id") or manifest_path.parent.name)
        description = _compact(payload.get("description") or "", limit=120)
        lines.append(f"- package_tool={tool_id}" + (f" | {description}" if description else ""))
    return lines


def _resource_fact_lines(root: Path) -> list[str]:
    payload = _read_json_object(root / ".factory" / "resources.json")
    facts = payload.get("facts") if isinstance(payload.get("facts"), list) else []
    if not facts:
        return ["- none"]
    lines: list[str] = []
    for item in facts[:24]:
        if not isinstance(item, dict):
            continue
        key = _compact(item.get("key") or "", limit=100)
        source = _compact(item.get("source") or "", limit=40)
        secret = bool(item.get("secret"))
        if secret:
            summary = "<secret redacted>"
        else:
            summary = _compact(item.get("value"), limit=100)
        lines.append(f"- {key}: {summary} | source={source or 'unknown'} | secret={secret}")
    if len(facts) > 24:
        lines.append(f"- ... {len(facts) - 24} more")
    return lines or ["- none"]


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _compact(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)]}…"
