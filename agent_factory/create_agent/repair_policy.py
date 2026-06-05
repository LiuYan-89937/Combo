from __future__ import annotations

from dataclasses import dataclass

from agent_factory.create_agent.contract_catalog import RUNTIME_INDEX_RESOURCES, contract_resources, contract_skill
from agent_factory.create_agent.models import PackageRepairBundle, PackageRepairTarget


@dataclass(frozen=True, slots=True)
class RepairRecommendation:
    skill: str
    resources: list[str]


@dataclass(frozen=True, slots=True)
class CreateAgentRepairPolicy:
    def manifest_missing_bundle(self) -> PackageRepairBundle:
        recommendation = self.recommendation("package.manifest", ["agent_package.json"])
        return PackageRepairBundle(
            bundle_id="materialize_base_package",
            kind="manifest_missing",
            repair_action="materialize_base_package",
            machine_applicable=True,
            target_files=["agent_package.json"],
            recommended_skill=recommendation.skill,
            recommended_resources=recommendation.resources,
            summary="Create the deterministic RuntimeKernel package scaffold before semantic customization.",
        )

    def manifest_contract_targets(
        self,
        *,
        missing_contracts: list[str],
        missing_files: list[tuple[str, str]],
    ) -> list[PackageRepairTarget]:
        targets = [
            PackageRepairTarget(
                contract_key=contract_key,
                target_file=f"contracts/{contract_key}.json",
                recommended_skill=contract_skill(contract_key),
                recommended_resources=contract_resources(contract_key),
            )
            for contract_key in missing_contracts
        ]
        targets.extend(
            PackageRepairTarget(
                contract_key=contract_key,
                target_file=relative_path,
                recommended_skill=contract_skill(contract_key),
                recommended_resources=contract_resources(contract_key),
            )
            for contract_key, relative_path in missing_files
        )
        return targets

    def manifest_contract_bundle(
        self,
        *,
        missing_contracts: list[str],
        missing_files: list[tuple[str, str]],
        target_files: list[str],
        targets: list[PackageRepairTarget],
        summary: str,
    ) -> PackageRepairBundle:
        bundle_kind = "missing_required_contracts" if missing_contracts else "missing_referenced_files"
        return PackageRepairBundle(
            bundle_id="materialize_required_contracts",
            kind=bundle_kind,
            repair_action="materialize_required_contracts",
            machine_applicable=True,
            target_files=target_files,
            targets=targets,
            recommended_skill="02-runtime-contract-index",
            recommended_resources=list(RUNTIME_INDEX_RESOURCES),
            inputs={
                "missing_contracts": missing_contracts,
                "missing_files": [{"contract_key": key, "target_file": path} for key, path in missing_files],
            },
            summary=summary,
        )

    def runtime_path_bundle(self, repair_input: dict[str, str]) -> PackageRepairBundle:
        target_file = repair_input["target_file"]
        contract_key = repair_input["contract_key"]
        recommendation = RepairRecommendation(
            skill=contract_skill(contract_key),
            resources=contract_resources(contract_key),
        )
        return PackageRepairBundle(
            bundle_id=f"normalize_runtime_path_{contract_key}_{repair_input['field_path'].replace('.', '_')}",
            kind="runtime_path_contract_repair",
            repair_action="normalize_runtime_contract_paths",
            machine_applicable=True,
            target_files=[target_file],
            targets=[
                PackageRepairTarget(
                    contract_key=contract_key,
                    target_file=target_file,
                    recommended_skill=recommendation.skill,
                    recommended_resources=recommendation.resources,
                )
            ],
            recommended_skill=recommendation.skill,
            recommended_resources=recommendation.resources,
            inputs=repair_input,
            summary=(
                f"Normalize {contract_key}.{repair_input['field_path']} from "
                f"{repair_input['current_value']!r} to {repair_input['replacement_value']!r}."
            ),
        )

    def generic_bundle(self, *, where: str, target_files: list[str], exc: Exception) -> PackageRepairBundle:
        recommendation = self.recommendation(where, target_files)
        kind = {
            "runtime_contracts.build": "runtime_contract_build",
            "assembly.compile": "assembly_compile",
            "python_syntax.compile": "python_syntax",
        }.get(where, "generic_repair")
        action = "fix_python_syntax" if where == "python_syntax.compile" else "read_skill_resources"
        return PackageRepairBundle(
            bundle_id=f"{where.replace('.', '_')}_repair",
            kind=kind,  # type: ignore[arg-type]
            repair_action=action,  # type: ignore[arg-type]
            machine_applicable=False,
            target_files=target_files,
            recommended_skill=recommendation.skill,
            recommended_resources=recommendation.resources,
            summary=f"{where} failed with {type(exc).__name__}. Load the recommended skill resources before editing.",
        )

    def recommendation(self, where: str, target_files: list[str]) -> RepairRecommendation:
        skill = self.recommended_skill(where, target_files)
        return RepairRecommendation(skill=skill, resources=self.recommended_resources(skill, target_files))

    def recommended_skill(self, where: str, target_files: list[str]) -> str:
        targets = " ".join(target_files)
        if where == "runtime_contracts.build":
            return "02-runtime-contract-index"
        if where == "assembly.compile":
            return "13-assembly-and-patterns"
        if "tools/" in targets:
            return "09-package-tools"
        if "nodes/" in targets:
            return "10-package-nodes"
        return "01-package-manifest"

    def recommended_resources(self, skill: str, target_files: list[str]) -> list[str]:
        targets = " ".join(target_files)
        if skill == "01-package-manifest":
            return [
                "references/agent_package.schema.json",
                "examples/agent_package.minimal.json",
                "references/agent_package.repair_hints.md",
            ]
        if skill == "02-runtime-contract-index":
            return list(RUNTIME_INDEX_RESOURCES)
        if skill == "09-package-tools":
            artifact = "package_tool" if "tools/" in targets else "tool_contract"
            return [
                f"references/{artifact}.schema.json",
                f"examples/{artifact}.minimal.json",
                f"references/{artifact}.repair_hints.md",
            ]
        if skill == "10-package-nodes":
            return [
                "references/package_node.schema.json",
                "examples/package_node.minimal.json",
                "references/package_node.repair_hints.md",
            ]
        if skill == "13-assembly-and-patterns":
            return [
                "references/assembly_spec.schema.json",
                "examples/assembly_spec.minimal.json",
                "references/pattern.schema.json",
                "references/assembly_spec.repair_hints.md",
            ]
        return ["references/contract.repair_hints.md"]

    def expected_for_where(self, where: str) -> str:
        return {
            "package.load": "AgentPackageLoader can load agent_package.json and referenced package files.",
            "runtime_contracts.build": "RuntimeBuildPlanner can build all declared RuntimeContracts.",
            "assembly.compile": "AgentAssemblyCompiler can compile the declared assembly and patterns.",
        }.get(where, "validation check passes")

    def repair_hint(self, where: str) -> str:
        return {
            "package.load": "Repair manifest paths and package structure, then rerun package validation.",
            "runtime_contracts.build": "Repair contract schema or required contract files using the relevant contract skill.",
            "assembly.compile": "Repair assembly, patterns, node impl ids, bindings, or state references.",
        }.get(where, "Repair the target files indicated by the validation issue.")
