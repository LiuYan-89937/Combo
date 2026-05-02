from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML

from agent_factory.specs import (
    AgentPackagePrimitives,
    ConversationSpec,
    GuardrailSpec,
    HandoffSpec,
    InstructionSpec,
    KnowledgeSpec,
    ObservabilitySpec,
    OutputSpec,
    RunContextSpec,
    ToolsetSpec,
    ValidationIssue,
    ValidationSeverity,
)


class PackageLoadError(Exception):
    def __init__(self, issues: list[ValidationIssue]):
        super().__init__("AgentPackage could not be loaded")
        self.issues = issues


REQUIRED_PRIMITIVE_FILES: dict[str, type[BaseModel]] = {
    "instructions.yaml": InstructionSpec,
    "output.yaml": OutputSpec,
    "conversation.yaml": ConversationSpec,
    "run_context.yaml": RunContextSpec,
    "toolsets.yaml": ToolsetSpec,
    "knowledge.yaml": KnowledgeSpec,
    "guardrails.yaml": GuardrailSpec,
    "handoffs.yaml": HandoffSpec,
    "observability.yaml": ObservabilitySpec,
}


class PackageLoader:
    def __init__(self) -> None:
        self._yaml = YAML(typ="safe")

    def load_primitives(self, root_path: str | Path) -> AgentPackagePrimitives:
        root = Path(root_path)
        loaded: dict[str, BaseModel] = {}
        issues: list[ValidationIssue] = []

        for filename, spec_type in REQUIRED_PRIMITIVE_FILES.items():
            path = root / filename
            if not path.exists():
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.FATAL,
                        code="missing_required_file",
                        message=f"Missing required AgentPackage primitive file: {filename}",
                        file=filename,
                    )
                )
                continue

            try:
                data = self._load_yaml(path)
                loaded[self._field_name(filename)] = spec_type.model_validate(data)
            except ValidationError as error:
                issues.extend(self._validation_issues(filename, error))
            except Exception as error:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.FATAL,
                        code="yaml_parse_error",
                        message=str(error),
                        file=filename,
                    )
                )

        if issues:
            raise PackageLoadError(issues)

        return AgentPackagePrimitives.model_validate(loaded)

    def _load_yaml(self, path: Path) -> dict[str, Any]:
        data = self._yaml.load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("YAML root must be a mapping")
        return data

    def _validation_issues(self, filename: str, error: ValidationError) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        for item in error.errors():
            location = ".".join(str(part) for part in item.get("loc", ()))
            issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.FATAL,
                    code="schema_validation_error",
                    message=str(item.get("msg", "schema validation failed")),
                    file=filename,
                    path=location or None,
                )
            )
        return issues

    @staticmethod
    def _field_name(filename: str) -> str:
        return {
            "instructions.yaml": "instructions",
            "output.yaml": "output",
            "conversation.yaml": "conversation",
            "run_context.yaml": "run_context",
            "toolsets.yaml": "toolsets",
            "knowledge.yaml": "knowledge",
            "guardrails.yaml": "guardrails",
            "handoffs.yaml": "handoffs",
            "observability.yaml": "observability",
        }[filename]

