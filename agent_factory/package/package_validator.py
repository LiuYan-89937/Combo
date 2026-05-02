from __future__ import annotations

from pathlib import Path

from agent_factory.package.package_loader import (
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

