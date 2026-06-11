from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_factory.assembly.schema import AgentAssemblySpec
from agent_factory.create_agent.contract_catalog import base_contract_paths, default_contract_payload
from agent_factory.runtime_contracts.schema import AgentPackageManifest
from agent_factory.runtime_kernel.patterns.registry import PatternRegistry
from agent_factory.runtime_render import RenderManifest, default_node_render_spec


PACKAGE_ASSET_DIRECTORIES = (
    "tools",
    "nodes",
    "prompts",
    "policies",
    "strategies",
    "formatters",
    "patterns",
    "knowledge",
    "artifacts",
)

def materialize_empty_agent_package(root: str | Path, *, factory_run_id: str, user_input: str = "") -> None:
    package_root = Path(root).expanduser().resolve()
    package_root.mkdir(parents=True, exist_ok=True)
    for relative in PACKAGE_ASSET_DIRECTORIES:
        (package_root / relative).mkdir(parents=True, exist_ok=True)
    manifest_path = package_root / "agent_package.json"
    if manifest_path.exists():
        return
    manifest_agent = _agent_identity(user_input=user_input)
    assembly_agent = _assembly_agent_identity(user_input=user_input)
    contracts = base_contract_paths()
    _write_json(
        manifest_path,
        AgentPackageManifest(
            factory_run_id=factory_run_id,
            agent=manifest_agent,
            runtime={"pattern_id": "react_agent"},
            assembly_spec_path="assembly_spec.json",
            render_manifest_path="render_manifest.json",
            resources_path="resources.json",
            sandbox_contract_path="sandbox_contract.json",
            contracts=contracts,
            patterns=[],
            tools=[],
        ).model_dump(mode="json", exclude_none=True),
    )
    _write_json(
        package_root / "assembly_spec.json",
        AgentAssemblySpec(
            agent=assembly_agent,
            runtime={"pattern_id": "react_agent"},
        ).model_dump(mode="json", exclude_none=True),
    )
    _write_json(package_root / "render_manifest.json", _default_render_manifest().model_dump(mode="json"))
    _write_json(package_root / "resources.json", {})
    _write_json(package_root / "sandbox_contract.json", {"version": "sandbox_contract.v0", "resources": {}})
    for contract_key in sorted(contracts):
        _write_json(package_root / contracts[contract_key], default_contract_payload(contract_key))


def _agent_identity(*, user_input: str) -> dict[str, Any]:
    return _assembly_agent_identity(user_input=user_input)


def _assembly_agent_identity(*, user_input: str) -> dict[str, Any]:
    summary = " ".join(str(user_input or "").split())
    description = summary[:240] if summary else "Generated RuntimeKernel AgentPackage."
    return {
        "id": "generated_agent",
        "name": "Generated Agent",
        "description": description,
        "version": "0.1.0",
    }


def _default_render_manifest() -> RenderManifest:
    pattern = PatternRegistry(
        builtins_dir=Path(__file__).resolve().parents[1] / "runtime_kernel" / "patterns" / "builtins"
    ).get("react_agent")
    return RenderManifest(
        graph_id=pattern.pattern_id,
        nodes={
            node.id: default_node_render_spec(node_id=node.id, node_type=node.type, impl=node.impl)
            for node in pattern.nodes
        },
    )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
