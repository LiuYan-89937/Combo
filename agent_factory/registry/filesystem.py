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
    provenance: "PackageProvenance | None" = None
    promotion_gate: "PromotionGate | None" = None


class PackageProvenance(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    created_by: str = "agentfactory"
    factory_version: str = "0.1.0"
    model_profile: str | None = None
    source_requirement_hash: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    build_reports: list[str] = Field(default_factory=list)
    harness_reports: list[str] = Field(default_factory=list)
    upgrade_request_id: str | None = None
    patch_plan_id: str | None = None
    approval_ids: list[str] = Field(default_factory=list)
    package_diff_path: str | None = None


class PromotionGate(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    package_validation_passed: bool = False
    harness_passed: bool = False
    high_risk_approvals_done: bool = True
    no_blocking_readiness: bool = False
    package_hash_stable: bool = False
    compatibility_checked: bool = True

    @property
    def passed(self) -> bool:
        return all(
            [
                self.package_validation_passed,
                self.harness_passed,
                self.high_risk_approvals_done,
                self.no_blocking_readiness,
                self.package_hash_stable,
                self.compatibility_checked,
            ]
        )


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
        package_hash = hash_package(target)
        gate = _promotion_gate(target, package_hash=package_hash)
        if status == "available" and not gate.passed:
            raise ValueError("Package must pass PromotionGate before release as available.")
        record = RegistryRecord(
            agent_name=manifest.agent_name,
            version=manifest.version,
            status=status,
            package_path=target,
            package_hash=package_hash,
            harness_status=harness_status,
            provenance=_package_provenance(target),
            promotion_gate=gate,
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
                gate = _promotion_gate(record.package_path, package_hash=hash_package(record.package_path))
                if status == "available" and not gate.passed:
                    raise ValueError("Package must pass PromotionGate before release as available.")
                updated = record.model_copy(update={"status": status, "promotion_gate": gate})
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


def _promotion_gate(package_path: Path, *, package_hash: str) -> PromotionGate:
    validation = PackageValidator().validate_full_package(package_path)
    readiness = _readiness_status(package_path)
    return PromotionGate(
        package_validation_passed=validation.ok,
        harness_passed=_harness_status(package_path) == "passed",
        high_risk_approvals_done=_high_risk_approvals_done(package_path),
        no_blocking_readiness=readiness in {None, "ready", "mock_only_allowed"},
        package_hash_stable=package_hash == hash_package(package_path),
        compatibility_checked=True,
    )


def _package_provenance(package_path: Path) -> PackageProvenance:
    reports_root = package_path / "generated" / "reports"
    build_reports = [
        str(path.relative_to(package_path))
        for path in sorted(reports_root.glob("*.json"))
        if path.name != "harness_run.json"
    ] if reports_root.exists() else []
    harness_reports = [
        str(path.relative_to(package_path))
        for path in sorted(reports_root.glob("harness*.json"))
    ] if reports_root.exists() else []
    evidence_refs = []
    for filename in ["research_brief.json", "research_completeness.json", "web_research_raw.json"]:
        path = reports_root / filename
        if path.exists():
            evidence_refs.append(str(path.relative_to(package_path)))
    lifecycle = _upgrade_lifecycle(package_path)
    return PackageProvenance(
        source_requirement_hash=_source_requirement_hash(package_path),
        evidence_refs=evidence_refs,
        build_reports=build_reports,
        harness_reports=harness_reports,
        upgrade_request_id=lifecycle.get("upgrade_request_id") if lifecycle else None,
        patch_plan_id=lifecycle.get("plan_id") if lifecycle else None,
        approval_ids=[
            str(item.get("approval_id"))
            for item in lifecycle.get("approvals", [])
            if isinstance(item, dict) and item.get("approval_id")
        ] if lifecycle else [],
        package_diff_path="generated/reports/upgrade_lifecycle.json" if lifecycle else None,
    )


def _source_requirement_hash(package_path: Path) -> str | None:
    candidates = [
        package_path / "instructions.yaml",
        package_path / "package.yaml",
    ]
    digest = hashlib.sha256()
    found = False
    for path in candidates:
        if not path.exists():
            continue
        digest.update(path.read_bytes())
        found = True
    return digest.hexdigest() if found else None


def _readiness_status(package_path: Path) -> str | None:
    path = package_path / "readiness.yaml"
    if not path.exists():
        return None
    try:
        from ruamel.yaml import YAML

        data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
        return str(data.get("status")) if isinstance(data, dict) else None
    except Exception:
        return None


def _high_risk_approvals_done(package_path: Path) -> bool:
    try:
        package = PackageLoader().load_full_package(package_path)
    except Exception:
        return False
    for tool in package.generated_tools:
        if str(tool.risk_level) in {"high", "critical"} and tool.approval.required:
            return False
    lifecycle = _upgrade_lifecycle(package_path)
    if lifecycle:
        required = {
            str(change.get("id"))
            for change in lifecycle.get("changes", [])
            if isinstance(change, dict)
            and (
                change.get("requires_approval")
                or str(change.get("risk_level")) in {"high", "critical"}
            )
        }
        approved = {
            str(approval.get("change_id"))
            for approval in lifecycle.get("approvals", [])
            if isinstance(approval, dict) and approval.get("decision") == "approved"
        }
        if not required.issubset(approved):
            return False
    return True


def _upgrade_lifecycle(package_path: Path) -> dict | None:
    path = package_path / "generated" / "reports" / "upgrade_lifecycle.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None
