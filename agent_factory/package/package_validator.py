from __future__ import annotations

from pathlib import Path

from agent_factory.package.package_loader import (
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

    def validate_full_package(self, root_path: str | Path) -> ValidationReport:
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

        if runtime.runtime_type == "workflow" and not runtime.workflow_steps:
            report.add(
                ValidationSeverity.FATAL,
                "runtime_workflow_steps_required",
                "runtime.yaml workflow runtime must declare at least one enabled step.",
                file="runtime.yaml",
                path="workflow_steps",
            )

        metadata_paths = {
            str(tool.implementation.path): tool.tool_id for tool in generated_tools
        }
        for relative_path, tool_id in metadata_paths.items():
            if not (Path(report.root_path or ".") / relative_path).exists():
                report.add(
                    ValidationSeverity.FATAL,
                    "generated_tool_implementation_missing",
                    f"Generated tool implementation is missing for {tool_id}.",
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
