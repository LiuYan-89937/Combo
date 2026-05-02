from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory_runtime import FactoryWorkspace
from agent_factory.harness import HarnessRunResult
from agent_factory.package import PackageLoader, PackageValidator


RegistryStatus = Literal["draft", "candidate", "available", "deprecated", "failed"]


class PackageRef(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    agent_name: str
    version: str
    path: Path


class RegistryRecord(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    agent_name: str
    version: str
    status: RegistryStatus = "candidate"
    package_path: Path
    package_hash: str
    registered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    harness_status: str | None = None


class RegistryIndex(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    records: list[RegistryRecord] = Field(default_factory=list)
    active: dict[str, str] = Field(default_factory=dict)


class FilesystemRegistry:
    def __init__(self, root_path: str | Path | None = None) -> None:
        if root_path is None:
            workspace = FactoryWorkspace.discover()
            workspace.ensure()
            root_path = workspace.workspace_path / "registry"
        self.root_path = Path(root_path)
        self.root_path.mkdir(parents=True, exist_ok=True)
        self.index_path = self.root_path / "index.json"
        if not self.index_path.exists():
            self._write_index(RegistryIndex())

    def register(self, package_path: str | Path, *, status: RegistryStatus = "candidate") -> RegistryRecord:
        package_path = Path(package_path)
        validation = PackageValidator().validate_full_package(package_path)
        if not validation.ok:
            raise ValueError("Package must pass full validation before registration.")
        manifest = PackageLoader().load_manifest(package_path)
        harness_status = _harness_status(package_path)
        target = self.root_path / "agents" / manifest.agent_name / manifest.version
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(package_path, target)
        record = RegistryRecord(
            agent_name=manifest.agent_name,
            version=manifest.version,
            status=status,
            package_path=target,
            package_hash=hash_package(target),
            harness_status=harness_status,
        )
        index = self.index()
        index.records = [
            item
            for item in index.records
            if not (item.agent_name == record.agent_name and item.version == record.version)
        ]
        index.records.append(record)
        if status == "available":
            index.active[record.agent_name] = record.version
        self._write_index(index)
        return record

    def index(self) -> RegistryIndex:
        return RegistryIndex.model_validate_json(self.index_path.read_text(encoding="utf-8"))

    def list(self) -> list[RegistryRecord]:
        return self.index().records

    def get(self, agent_name: str, version: str | None = None) -> RegistryRecord | None:
        index = self.index()
        selected_version = version or index.active.get(agent_name)
        if selected_version is None:
            records = [item for item in index.records if item.agent_name == agent_name]
            if not records:
                return None
            selected_version = sorted(records, key=lambda item: item.registered_at)[-1].version
        for record in index.records:
            if record.agent_name == agent_name and record.version == selected_version:
                return record
        return None

    def release(self, agent_name: str, version: str, status: RegistryStatus) -> RegistryRecord:
        index = self.index()
        for idx, record in enumerate(index.records):
            if record.agent_name == agent_name and record.version == version:
                updated = record.model_copy(update={"status": status})
                index.records[idx] = updated
                if status == "available":
                    index.active[agent_name] = version
                self._write_index(index)
                return updated
        raise ValueError(f"Registry record not found: {agent_name}@{version}")

    def rollback(self, agent_name: str, version: str) -> RegistryRecord:
        return self.release(agent_name, version, "available")

    def _write_index(self, index: RegistryIndex) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(index.model_dump_json(indent=2), encoding="utf-8")


def hash_package(package_path: str | Path) -> str:
    root = Path(package_path)
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if ".agentfactory/registry" in str(path):
            continue
        digest.update(str(path.relative_to(root)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _harness_status(package_path: Path) -> str | None:
    path = package_path / "generated" / "reports" / "harness_run.json"
    if not path.exists():
        return None
    try:
        return HarnessRunResult.model_validate_json(path.read_text(encoding="utf-8")).status
    except Exception:
        try:
            return json.loads(path.read_text(encoding="utf-8")).get("status")
        except Exception:
            return None
