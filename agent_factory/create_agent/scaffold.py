from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from agent_factory.assembly.schema import AgentAssemblySpec
from agent_factory.create_agent.contract_catalog import (
    default_contract_payload,
    required_contract_items,
    required_contract_paths,
)
from agent_factory.runtime_contracts.schema import AgentPackageManifest
from agent_factory.runtime_kernel.patterns.schema import GraphPatternSpec
from agent_factory.runtime_render import RenderManifest, default_node_render_spec


def ensure_base_package(root: str | Path, *, request_text: str = "") -> dict[str, Any]:
    package_root = Path(root).expanduser().resolve()
    package_root.mkdir(parents=True, exist_ok=True)
    writer = _ScaffoldWriter(package_root)

    agent_id = _agent_id(package_root)
    manifest = _manifest_payload(package_root, agent_id=agent_id, request_text=request_text)
    writer.write_json_if_changed(package_root / "agent_package.json", manifest)

    writer.write_json_if_missing_or_empty(
        package_root / "assembly_spec.json",
        _assembly_payload(agent_id=agent_id),
    )
    writer.write_json_if_missing_or_empty(
        package_root / "render_manifest.json",
        _render_payload(agent_id=agent_id),
    )
    writer.write_json_if_missing_or_empty(
        package_root / "resources.json",
        {"version": "agent_resources.v0", "resources": {}},
    )
    writer.write_json_if_missing_or_empty(
        package_root / "sandbox_contract.json",
        {"version": "sandbox_contract.v0", "backend": "runtime_default"},
    )
    writer.write_yaml_if_missing_or_empty(
        package_root / "patterns" / "main.yaml",
        _pattern_payload(),
    )
    for item in required_contract_items():
        writer.write_json_if_missing_or_empty(
            package_root / item.path,
            default_contract_payload(item.contract_key),
        )

    return {
        "status": "completed",
        "created": sorted(writer.created),
        "updated": sorted(writer.updated),
        "preserved": sorted(writer.preserved),
        "manifest_path": "agent_package.json",
        "contract_paths": required_contract_paths(),
    }


def _manifest_payload(package_root: Path, *, agent_id: str, request_text: str) -> dict[str, Any]:
    existing = _read_json_object(package_root / "agent_package.json") or {}
    agent = existing.get("agent") if isinstance(existing.get("agent"), dict) else {}
    if not agent:
        agent = {"id": agent_id, "name": "Generated Agent"}
    elif "id" not in agent:
        agent = {**agent, "id": agent_id}
    if request_text and "description" not in agent:
        agent = {**agent, "description": request_text[:240]}

    contracts = existing.get("contracts") if isinstance(existing.get("contracts"), dict) else {}
    contracts = {str(key): str(value) for key, value in contracts.items() if str(key).strip() and str(value).strip()}
    contracts.update({key: contracts.get(key, path) for key, path in required_contract_paths().items()})

    payload = {
        **existing,
        "version": existing.get("version") or "agent_package.v0",
        "factory_run_id": str(existing.get("factory_run_id") or package_root.name),
        "agent": agent,
        "runtime": existing.get("runtime") if isinstance(existing.get("runtime"), dict) else {},
        "assembly_spec_path": str(existing.get("assembly_spec_path") or "assembly_spec.json"),
        "render_manifest_path": str(existing.get("render_manifest_path") or "render_manifest.json"),
        "resources_path": str(existing.get("resources_path") or "resources.json"),
        "sandbox_contract_path": str(existing.get("sandbox_contract_path") or "sandbox_contract.json"),
        "contracts": contracts,
        "bindings": existing.get("bindings") if isinstance(existing.get("bindings"), dict) else {},
        "patterns": _unique_strings([*(existing.get("patterns") if isinstance(existing.get("patterns"), list) else []), "patterns/main.yaml"]),
        "prompts": _unique_strings(existing.get("prompts") if isinstance(existing.get("prompts"), list) else []),
        "tools": _unique_strings(existing.get("tools") if isinstance(existing.get("tools"), list) else []),
        "policies": _unique_strings(existing.get("policies") if isinstance(existing.get("policies"), list) else []),
        "strategies": _unique_strings(existing.get("strategies") if isinstance(existing.get("strategies"), list) else []),
        "formatters": _unique_strings(existing.get("formatters") if isinstance(existing.get("formatters"), list) else []),
    }
    return AgentPackageManifest.model_validate(payload).model_dump(mode="json", exclude_none=True)


def _assembly_payload(*, agent_id: str) -> dict[str, Any]:
    return AgentAssemblySpec(
        agent={"id": agent_id, "name": "Generated Agent"},
        runtime={"pattern_id": "main"},
    ).model_dump(mode="json", by_alias=True, exclude_none=True)


def _render_payload(*, agent_id: str) -> dict[str, Any]:
    return RenderManifest(
        graph_id=agent_id,
        nodes={
            "ingress": default_node_render_spec(node_id="ingress", node_type="reserved", impl="ingress"),
            "finalize": default_node_render_spec(node_id="finalize", node_type="terminal", impl="finalize"),
        },
    ).model_dump(mode="json", by_alias=True, exclude_none=True)


def _pattern_payload() -> dict[str, Any]:
    return GraphPatternSpec(
        pattern_id="main",
        kind="main",
        embeddable=False,
        version=1,
        name="Main",
        description="Minimal executable package pattern.",
        entry_node="ingress",
        nodes=[
            {"id": "ingress", "type": "reserved", "impl": "ingress"},
            {"id": "finalize", "type": "terminal", "impl": "finalize"},
        ],
        edges=[{"from": "ingress", "to": "finalize", "when": "always"}],
        termination={"success_nodes": ["finalize"]},
    ).model_dump(mode="json", by_alias=True, exclude_none=True)


class _ScaffoldWriter:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.created: list[str] = []
        self.updated: list[str] = []
        self.preserved: list[str] = []

    def write_json_if_changed(self, path: Path, payload: dict[str, Any]) -> None:
        relative = self.relative(path)
        text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        path.write_text(text, encoding="utf-8")
        (self.updated if existed else self.created).append(relative)

    def write_json_if_missing_or_empty(self, path: Path, payload: dict[str, Any]) -> None:
        if path.exists() and not _is_empty_json_object(path):
            self.preserved.append(self.relative(path))
            return
        self.write_json_if_changed(path, payload)

    def write_yaml_if_missing_or_empty(self, path: Path, payload: dict[str, Any]) -> None:
        if path.exists() and not _is_empty_yaml_object(path):
            self.preserved.append(self.relative(path))
            return
        yaml = YAML()
        yaml.default_flow_style = False
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        with path.open("w", encoding="utf-8") as handle:
            yaml.dump(payload, handle)
        (self.updated if existed else self.created).append(self.relative(path))

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root).as_posix()


def _read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in create-agent package file: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"create-agent package file must contain a JSON object: {path}")
    return value


def _is_empty_json_object(path: Path) -> bool:
    value = _read_json_object(path)
    return value == {}


def _is_empty_yaml_object(path: Path) -> bool:
    if not path.exists():
        return True
    yaml = YAML(typ="safe")
    try:
        value = yaml.load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return False
    return value == {}


def _agent_id(package_root: Path) -> str:
    raw = "agent_" + package_root.name[:12]
    return "".join(char.lower() if char.isalnum() else "_" for char in raw)


def _unique_strings(value: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
