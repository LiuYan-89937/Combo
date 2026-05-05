from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field
from ruamel.yaml import YAML

from agent_factory.core.types import JsonDumpMixin
from agent_factory.package import PackageLoader, PackageValidator


class PatchChange(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    id: str
    path: str
    action: Literal["add", "modify", "delete"]
    risk_level: str = "medium"
    requires_approval: bool = False
    summary: str


class PatchPlan(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "0.1"
    kind: str = "PatchPlan"
    plan_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    agent_name: str
    base_package_path: Path
    target_version: str
    changes: list[PatchChange] = Field(default_factory=list)


class PatchPlanService:
    def __init__(self, loader: PackageLoader | None = None) -> None:
        self.loader = loader or PackageLoader()
        self._yaml = YAML()

    def plan_upgrade(
        self,
        package_path: Path,
        *,
        prompt: str,
        target_version: str = "1.1.0",
    ) -> PatchPlan:
        manifest = self.loader.load_manifest(package_path)
        change_id = _safe_change_id(prompt)
        return PatchPlan(
            agent_name=manifest.agent_name,
            base_package_path=package_path,
            target_version=target_version,
            changes=[
                PatchChange(
                    id=f"{change_id}-instructions",
                    path="instructions.yaml",
                    action="modify",
                    risk_level="medium",
                    summary=f"Update agent guidance for requested upgrade: {prompt}",
                ),
                PatchChange(
                    id=f"{change_id}-harness",
                    path="harness.yaml",
                    action="modify",
                    risk_level="medium",
                    summary="Add or update Harness coverage for the requested upgrade.",
                ),
            ],
        )

    def write_plan(self, plan: PatchPlan, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            self._yaml.dump(plan.model_dump(mode="json"), file)
        return path

    def apply_plan(self, plan: PatchPlan, output_path: Path) -> Path:
        if output_path.exists():
            shutil.rmtree(output_path)
        shutil.copytree(plan.base_package_path, output_path)
        self._apply_version(output_path, plan.target_version)
        self._write_upgrade_notes(output_path, plan)
        PackageValidator().validate_full_package(output_path)
        return output_path

    def _apply_version(self, package_path: Path, version: str) -> None:
        for filename in ["package.yaml", "instructions.yaml"]:
            path = package_path / filename
            data = self._yaml.load(path.read_text(encoding="utf-8")) or {}
            if filename == "package.yaml":
                data["version"] = version
                data["status"] = "candidate"
            metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
            metadata["version"] = version
            data["metadata"] = metadata
            with path.open("w", encoding="utf-8") as file:
                self._yaml.dump(data, file)

    def _write_upgrade_notes(self, package_path: Path, plan: PatchPlan) -> None:
        path = package_path / "upgrade_notes.yaml"
        with path.open("w", encoding="utf-8") as file:
            self._yaml.dump(plan.model_dump(mode="json"), file)


def _safe_change_id(value: str) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")
    while "--" in normalized:
        normalized = normalized.replace("--", "-")
    return normalized[:48] or "requested-upgrade"
