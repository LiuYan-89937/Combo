from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Literal

from agent_factory.assembly.schema import AgentAssemblySpec
from agent_factory.runtime_contracts import MemoryContract, ModelContract
from agent_factory.tooling.spec import ToolSpec


ToolDescriptionKind = Literal["model_tool", "package_tool"]


class AgentPackageConfigurationEditor:
    """Persist user-editable package configuration through validated package sources."""

    def update_tool_description(
        self,
        package_root: Path,
        *,
        tool_kind: ToolDescriptionKind,
        tool_id: str,
        description: str,
    ) -> None:
        normalized_id = str(tool_id or "").strip()
        if not normalized_id:
            raise ValueError("tool_id must not be empty")
        normalized_description = str(description or "").strip()
        if tool_kind == "model_tool":
            self._update_model_tool_description(package_root, normalized_id, normalized_description)
            return
        if tool_kind == "package_tool":
            self._update_package_tool_description(package_root, normalized_id, normalized_description)
            return
        raise ValueError(f"unsupported tool kind: {tool_kind}")

    def update_memory_write_interval(self, package_root: Path, write_interval_turns: int) -> None:
        contract_path = package_root / "contracts" / "memory.json"
        document = _read_json_document(contract_path)
        config = document.get("config")
        if not isinstance(config, dict):
            raise ValueError("memory contract config must be an object")
        memory_system = config.get("memory_system")
        if not isinstance(memory_system, dict):
            raise ValueError("memory contract must declare memory_system")
        background = memory_system.get("background")
        if not isinstance(background, dict):
            raise ValueError("memory contract must declare background configuration")
        background["write_interval_turns"] = write_interval_turns
        validated = MemoryContract.model_validate(document).model_dump(mode="json", exclude_none=True)
        _write_documents_atomically({contract_path: validated})

    def _update_model_tool_description(self, package_root: Path, tool_id: str, description: str) -> None:
        contract_path = package_root / "contracts" / "model.json"
        document = _read_json_document(contract_path)
        config = document.get("config")
        if not isinstance(config, dict):
            raise ValueError("model contract config must be an object")
        bindings = config.get("tool_bindings")
        if not isinstance(bindings, dict) or tool_id not in bindings:
            raise ValueError(f"model tool binding is not declared by package: {tool_id}")
        binding = bindings[tool_id]
        if not isinstance(binding, dict):
            raise ValueError(f"model tool binding must be an object: {tool_id}")
        binding["description"] = description
        validated = ModelContract.model_validate(document).model_dump(mode="json", exclude_none=True)
        _write_documents_atomically({contract_path: validated})

    def _update_package_tool_description(self, package_root: Path, tool_id: str, description: str) -> None:
        manifest_path = package_root / "tools" / tool_id / "manifest.json"
        assembly_path = package_root / "assembly_spec.json"
        manifest = _read_json_document(manifest_path)
        if str(manifest.get("id") or "").strip() != tool_id:
            raise ValueError(f"package tool manifest id does not match requested tool: {tool_id}")
        manifest["description"] = description
        validated_manifest = ToolSpec.model_validate(manifest).model_dump(mode="json", exclude_none=True)

        assembly = _read_json_document(assembly_path)
        tools = assembly.get("tools")
        if not isinstance(tools, list):
            raise ValueError("assembly tools must be an array")
        matched = False
        for tool in tools:
            if isinstance(tool, dict) and str(tool.get("id") or "").strip() == tool_id:
                tool["description"] = description
                matched = True
                break
        if not matched:
            raise ValueError(f"package tool is missing from assembly index: {tool_id}")
        validated_assembly = AgentAssemblySpec.model_validate(assembly).model_dump(mode="json", exclude_none=True)
        _write_documents_atomically(
            {
                manifest_path: validated_manifest,
                assembly_path: validated_assembly,
            }
        )


def _read_json_document(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"package configuration file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"package configuration file must contain an object: {path}")
    return payload


def _write_documents_atomically(documents: dict[Path, dict[str, Any]]) -> None:
    originals = {path: path.read_bytes() if path.exists() else None for path in documents}
    staged: dict[Path, Path] = {}
    try:
        for path, payload in documents.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
                staged[path] = Path(handle.name)
        for path, temporary_path in staged.items():
            os.replace(temporary_path, path)
        staged.clear()
    except Exception:
        for path, original in originals.items():
            if original is None:
                path.unlink(missing_ok=True)
                continue
            with NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
                handle.write(original)
                handle.flush()
                os.fsync(handle.fileno())
                rollback_path = Path(handle.name)
            os.replace(rollback_path, path)
        raise
    finally:
        for temporary_path in staged.values():
            temporary_path.unlink(missing_ok=True)
