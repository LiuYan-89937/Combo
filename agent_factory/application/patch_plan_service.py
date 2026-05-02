from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field
from ruamel.yaml import YAML

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory.package_artifacts import PackageArtifactGenerator
from agent_factory.package import PackageLoader, PackageValidator
from agent_factory.specs import AgentPackagePrimitives


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
        return PatchPlan(
            agent_name=manifest.agent_name,
            base_package_path=package_path,
            target_version=target_version,
            changes=[
                PatchChange(
                    id="add-intent-repair-return",
                    path="instructions.yaml",
                    action="modify",
                    risk_level="medium",
                    summary="Add repair_return intent handling guidance.",
                ),
                PatchChange(
                    id="generated-tool-repair-ticket-create",
                    path="generated/draft_tools/repair_ticket_create.py",
                    action="add",
                    risk_level="high",
                    requires_approval=True,
                    summary="Add draft tool for repair ticket creation.",
                ),
                PatchChange(
                    id="harness-repair-ticket-confirm",
                    path="harness.yaml",
                    action="modify",
                    risk_level="medium",
                    summary="Add repair ticket confirmation scenario.",
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
        self._add_repair_tool(output_path)
        self._add_repair_harness(output_path)
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

    def _add_repair_tool(self, package_path: Path) -> None:
        primitives = self.loader.load_primitives(package_path)
        data = primitives.model_dump(mode="json", by_alias=True)
        toolsets = data["toolsets"]["toolsets"]
        if toolsets:
            exposed = toolsets[0].setdefault("exposed_tools", [])
            if "repair_ticket_create" not in exposed:
                exposed.append("repair_ticket_create")
        primitives = AgentPackagePrimitives.model_validate(data)
        PackageArtifactGenerator().generate_tool_scripts(package_path, primitives)
        PackageArtifactGenerator().generate_tool_tests(package_path, primitives)
        PackageArtifactGenerator().generate_package_specs(package_path, primitives)
        with (package_path / "toolsets.yaml").open("w", encoding="utf-8") as file:
            self._yaml.dump(data["toolsets"], file)

    def _add_repair_harness(self, package_path: Path) -> None:
        path = package_path / "harness.yaml"
        data = self._yaml.load(path.read_text(encoding="utf-8")) or {}
        scenarios = data.setdefault("scenarios", [])
        if not any(item.get("id") == "repair_ticket_confirm_001" for item in scenarios if isinstance(item, dict)):
            scenarios.append(
                {
                    "id": "repair_ticket_confirm_001",
                    "name": "Repair return requires confirmation",
                    "turns": [{"user": "我要返厂维修"}],
                    "expected": {
                        "expected_intent": "repair_return",
                        "selected_tool": "repair_ticket_create",
                        "must_confirm": True,
                        "forbidden_direct_execution": True,
                    },
                    "observe": {"trace": True, "tool_calls": True, "interrupts": True},
                }
            )
        with path.open("w", encoding="utf-8") as file:
            self._yaml.dump(data, file)
