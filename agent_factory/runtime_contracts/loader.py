from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_factory.assembly.schema import AgentAssemblySpec
from agent_factory.runtime_contracts.schema import AgentPackageManifest
from agent_factory.runtime_kernel.patterns.loader import PatternLoader
from agent_factory.runtime_kernel.patterns.schema import GraphPatternSpec
from agent_factory.runtime_render import RenderManifest


@dataclass(frozen=True, slots=True)
class LoadedAgentPackage:
    package_root: Path
    manifest_path: Path
    manifest: AgentPackageManifest
    assembly_spec: AgentAssemblySpec
    render_manifest: RenderManifest
    resources: dict[str, Any]
    sandbox_contract: dict[str, Any]
    contracts: dict[str, dict[str, Any]]
    patterns: list[GraphPatternSpec]


class AgentPackageLoader:
    def load_path(self, path: str | Path) -> LoadedAgentPackage:
        manifest_path = Path(path)
        manifest = AgentPackageManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        package_root = manifest_path.parent

        assembly_spec = AgentAssemblySpec.model_validate_json(
            _read_package_file(package_root, manifest.assembly_spec_path)
        )
        render_manifest = RenderManifest.model_validate_json(
            _read_package_file(package_root, manifest.render_manifest_path)
        )
        resources = _json_object(_read_package_file(package_root, manifest.resources_path), "resources")
        sandbox_contract = _json_object(_read_package_file(package_root, manifest.sandbox_contract_path), "sandbox_contract")
        contracts = {
            key: _json_object(_read_package_file(package_root, value), f"contracts.{key}")
            for key, value in manifest.contracts.items()
        }
        pattern_loader = PatternLoader()
        patterns = [
            pattern_loader.load_path(_package_file_path(package_root, value))
            for value in manifest.patterns
        ]
        return LoadedAgentPackage(
            package_root=package_root,
            manifest_path=manifest_path,
            manifest=manifest,
            assembly_spec=assembly_spec,
            render_manifest=render_manifest,
            resources=resources,
            sandbox_contract=sandbox_contract,
            contracts=contracts,
            patterns=patterns,
        )


def _read_package_file(package_root: Path, relative_path: str) -> str:
    return _package_file_path(package_root, relative_path).read_text(encoding="utf-8")


def _package_file_path(package_root: Path, relative_path: str) -> Path:
    target = (package_root / relative_path).resolve()
    root = package_root.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"package path escapes package root: {relative_path}") from exc
    if not target.is_file():
        raise FileNotFoundError(f"package file not found: {relative_path}")
    return target


def _json_object(content: str, label: str) -> dict[str, Any]:
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value
