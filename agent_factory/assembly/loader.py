from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from agent_factory.assembly.schema import AgentAssemblySpec
from agent_factory.runtime_render import RenderManifest


class AgentAssemblyLoader:
    def __init__(self) -> None:
        self._yaml = YAML(typ="safe")

    def load_path(self, path: str | Path) -> AgentAssemblySpec:
        source = Path(path)
        if source.suffix.lower() == ".json":
            data = json.loads(source.read_text(encoding="utf-8"))
        else:
            data = self._yaml.load(source.read_text(encoding="utf-8")) or {}
        if source.name == "agent_package.json":
            data = _load_package_assembly(source, data)
        else:
            data = _attach_build_render_manifest(source, data)
        return AgentAssemblySpec.model_validate(data)


def _load_package_assembly(source: Path, package_manifest: dict[str, Any]) -> dict[str, Any]:
    assembly_path = _package_relative_path(source.parent, package_manifest, "assembly_spec_path")
    render_manifest_path = _package_relative_path(source.parent, package_manifest, "render_manifest_path")
    assembly_data = json.loads(assembly_path.read_text(encoding="utf-8"))
    render_manifest = RenderManifest.model_validate_json(render_manifest_path.read_text(encoding="utf-8"))
    return _inject_render_manifest(assembly_data, render_manifest, render_manifest_path)


def _attach_build_render_manifest(source: Path, data: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(data, dict):
        return data
    metadata = dict(data.get("metadata") or {})
    if metadata.get("render_manifest"):
        return data
    render_manifest_path = source.parent / "render_manifest.json"
    if not render_manifest_path.is_file():
        return data
    render_manifest = RenderManifest.model_validate_json(render_manifest_path.read_text(encoding="utf-8"))
    return _inject_render_manifest(data, render_manifest, render_manifest_path)


def _inject_render_manifest(
    assembly_data: dict[str, Any],
    render_manifest: RenderManifest,
    render_manifest_path: Path,
) -> dict[str, Any]:
    metadata = dict(assembly_data.get("metadata") or {})
    metadata.update(
        {
            "render_manifest_version": render_manifest.version,
            "render_manifest_path": str(render_manifest_path),
            "render_node_ids": sorted(render_manifest.nodes),
            "render_manifest": render_manifest.model_dump(mode="json"),
        }
    )
    return {**assembly_data, "metadata": metadata}


def _package_relative_path(root: Path, manifest: dict[str, Any], key: str) -> Path:
    value = str(manifest.get(key) or "")
    if not value:
        raise ValueError(f"agent_package.json missing {key}")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"agent_package.json invalid {key}: {value}")
    return root / path
