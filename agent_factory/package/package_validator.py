from __future__ import annotations

from pathlib import Path

from agent_factory.package.package_loader import (
    OPTIONAL_CONDITION_FILES,
    REQUIRED_FULL_PACKAGE_FILES,
    REQUIRED_PRIMITIVE_FILES,
    PackageLoadError,
    PackageLoader,
)
from agent_factory.specs import AgentPackagePrimitives, ValidationReport, ValidationSeverity


class PackageValidator:
    def __init__(self, loader: PackageLoader | None = None):
        self.loader = loader or PackageLoader()

    def validate_primitives(self, root_path: str | Path) -> ValidationReport:
        root = Path(root_path)
        report = ValidationReport(root_path=root)

        for filename in REQUIRED_PRIMITIVE_FILES:
            if not (root / filename).exists():
                report.add(
                    ValidationSeverity.FATAL,
                    "missing_required_file",
                    f"Missing required AgentPackage primitive file: {filename}",
                    file=filename,
                )

        if any(issue.severity == ValidationSeverity.FATAL for issue in report.issues):
            return report

        try:
            primitives = self.loader.load_primitives(root)
        except PackageLoadError as error:
            report.issues.extend(error.issues)
            return report

        self._semantic_validation(primitives, report)
        return report

    def validate_full_package(self, root_path: str | Path, *, strict: bool = False) -> ValidationReport:
        root = Path(root_path)
        report = self.validate_primitives(root)

        for filename in REQUIRED_FULL_PACKAGE_FILES:
            if not (root / filename).exists():
                report.add(
                    ValidationSeverity.FATAL,
                    "missing_required_file",
                    f"Missing required AgentPackage file: {filename}",
                    file=filename,
                )

        for filename in OPTIONAL_CONDITION_FILES:
            if not (root / filename).exists():
                report.add(
                    ValidationSeverity.FATAL if strict else ValidationSeverity.WARNING,
                    "missing_condition_file",
                    f"Missing AgentPackage condition file: {filename}",
                    file=filename,
                )

        if any(issue.severity == ValidationSeverity.FATAL for issue in report.issues):
            return report

        try:
            package = self.loader.load_full_package(root)
        except PackageLoadError as error:
            report.issues.extend(error.issues)
            return report

        self._full_semantic_validation(package, report)
        return report

    def _semantic_validation(
        self,
        primitives: AgentPackagePrimitives,
        report: ValidationReport,
    ) -> None:
        if not primitives.instructions.persona.strip():
            report.add(
                ValidationSeverity.FATAL,
                "instruction_persona_required",
                "instructions.yaml persona must not be blank.",
                file="instructions.yaml",
                path="persona",
            )
        if not primitives.instructions.goal.strip():
            report.add(
                ValidationSeverity.FATAL,
                "instruction_goal_required",
                "instructions.yaml goal must not be blank.",
                file="instructions.yaml",
                path="goal",
            )

    def _full_semantic_validation(
        self,
        package: object,
        report: ValidationReport,
    ) -> None:
        manifest = package.manifest
        primitives = package.primitives
        runtime = package.runtime
        tools = package.tools
        generated_tools = package.generated_tools

        if manifest.agent_name != primitives.instructions.metadata.name:
            report.add(
                ValidationSeverity.WARNING,
                "manifest_name_differs_from_instructions",
                "package.yaml agent_name differs from instructions metadata name.",
                file="package.yaml",
                path="agent_name",
            )

        metadata_paths: dict[str, tuple[str, str]] = {}
        for tool in generated_tools:
            metadata_paths[str(tool.implementation.path)] = (tool.tool_id, "wrapper")
            if tool.implementation.logic_path:
                metadata_paths[str(tool.implementation.logic_path)] = (tool.tool_id, "logic")
        for relative_path, (tool_id, artifact_type) in metadata_paths.items():
            if not (Path(report.root_path or ".") / relative_path).exists():
                report.add(
                    ValidationSeverity.FATAL,
                    "generated_tool_implementation_missing",
                    f"Generated tool {artifact_type} implementation is missing for {tool_id}.",
                    file=relative_path,
                )

        declared = set(tools.generated_tools)
        actual = {tool.tool_id for tool in generated_tools}
        missing_declared = actual.difference(declared)
        if missing_declared:
            report.add(
                ValidationSeverity.WARNING,
                "tools_yaml_missing_generated_tool_refs",
                "tools.yaml does not list all generated tool ids.",
                file="tools.yaml",
                path="generated_tools",
            )

        if not package.harness.scenarios:
            report.add(
                ValidationSeverity.FATAL,
                "harness_scenarios_required",
                "harness.yaml must contain at least one scenario.",
                file="harness.yaml",
                path="scenarios",
            )

        if package.readiness is not None and package.readiness.status == "mock_only_allowed":
            report.add(
                ValidationSeverity.WARNING,
                "package_mock_only",
                "readiness.yaml status is mock_only_allowed; external capabilities are simulated.",
                file="readiness.yaml",
                path="status",
            )
        elif package.readiness is not None and package.readiness.status != "ready":
            report.add(
                ValidationSeverity.FATAL,
                "package_not_ready",
                f"readiness.yaml status is {package.readiness.status}.",
                file="readiness.yaml",
                path="status",
            )

        if package.resource_contracts is not None:
            known_source_ids = {source.id for source in primitives.knowledge.sources}
            known_source_ids.update(source.id for source in package.context.sources)
            for resource in package.resource_contracts.resources:
                if resource.id not in known_source_ids:
                    report.add(
                        ValidationSeverity.WARNING,
                        "resource_contract_without_source",
                        "resource_contracts.yaml contains a resource not referenced by knowledge/context sources.",
                        file="resource_contracts.yaml",
                        path=f"resources.{resource.id}",
                    )
