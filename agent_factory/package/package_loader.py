from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError
from ruamel.yaml import YAML

from agent_factory.specs import (
    AgentPackagePrimitives,
    ConversationSpec,
    ContextSpec,
    FullAgentPackage,
    GeneratedToolDraftSpec,
    GuardrailSpec,
    HarnessPackageSpec,
    HandoffSpec,
    InstructionSpec,
    KnowledgeSpec,
    MCPBindingSpec,
    MemorySpec,
    EnvironmentProbeReport,
    ObservabilitySpec,
    OutputSpec,
    PackageManifest,
    ReadinessReport,
    ResourceContractsSpec,
    RuntimeSpec,
    RunContextSpec,
    TaskGraphSpec,
    ToolsSpec,
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


REQUIRED_FULL_PACKAGE_FILES: dict[str, type[BaseModel]] = {
    "package.yaml": PackageManifest,
    "runtime.yaml": RuntimeSpec,
    "task_graph.yaml": TaskGraphSpec,
    "tools.yaml": ToolsSpec,
    "mcp.yaml": MCPBindingSpec,
    "context.yaml": ContextSpec,
    "memory.yaml": MemorySpec,
    "harness.yaml": HarnessPackageSpec,
}


OPTIONAL_CONDITION_FILES: dict[str, type[BaseModel]] = {
    "environment.yaml": EnvironmentProbeReport,
    "resource_contracts.yaml": ResourceContractsSpec,
    "readiness.yaml": ReadinessReport,
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

    def load_manifest(self, root_path: str | Path) -> PackageManifest:
        return self._load_model(Path(root_path), "package.yaml", PackageManifest)

    def load_full_package(self, root_path: str | Path) -> FullAgentPackage:
        root = Path(root_path)
        issues: list[ValidationIssue] = []
        try:
            primitives = self.load_primitives(root)
        except PackageLoadError as error:
            issues.extend(error.issues)
            primitives = None

        loaded: dict[str, BaseModel] = {}
        for filename, spec_type in REQUIRED_FULL_PACKAGE_FILES.items():
            path = root / filename
            if not path.exists():
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.FATAL,
                        code="missing_required_file",
                        message=f"Missing required AgentPackage file: {filename}",
                        file=filename,
                    )
                )
                continue
            try:
                loaded[self._full_field_name(filename)] = spec_type.model_validate(
                    self._load_yaml(path)
                )
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

        for filename, spec_type in OPTIONAL_CONDITION_FILES.items():
            path = root / filename
            if not path.exists():
                continue
            try:
                loaded[self._condition_field_name(filename)] = spec_type.model_validate(
                    self._load_yaml(path)
                )
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

        generated_tools = self._load_generated_tool_specs(root, issues)
        if issues:
            raise PackageLoadError(issues)
        assert primitives is not None
        return FullAgentPackage.model_validate(
            {
                "primitives": primitives,
                "generated_tools": generated_tools,
                **loaded,
            }
        )

    def _load_model(
        self,
        root: Path,
        filename: str,
        spec_type: type[BaseModel],
    ) -> BaseModel:
        path = root / filename
        if not path.exists():
            raise PackageLoadError(
                [
                    ValidationIssue(
                        severity=ValidationSeverity.FATAL,
                        code="missing_required_file",
                        message=f"Missing required AgentPackage file: {filename}",
                        file=filename,
                    )
                ]
            )
        try:
            return spec_type.model_validate(self._load_yaml(path))
        except ValidationError as error:
            raise PackageLoadError(self._validation_issues(filename, error)) from error

    def _load_generated_tool_specs(
        self,
        root: Path,
        issues: list[ValidationIssue],
    ) -> list[GeneratedToolDraftSpec]:
        specs: list[GeneratedToolDraftSpec] = []
        for path in sorted((root / "generated" / "draft_tools").glob("*.tool.yaml")):
            relative = str(path.relative_to(root))
            try:
                specs.append(GeneratedToolDraftSpec.model_validate(self._load_yaml(path)))
            except ValidationError as error:
                issues.extend(self._validation_issues(relative, error))
            except Exception as error:
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.FATAL,
                        code="yaml_parse_error",
                        message=str(error),
                        file=relative,
                    )
                )
        return specs

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

    @staticmethod
    def _full_field_name(filename: str) -> str:
        return {
            "package.yaml": "manifest",
            "runtime.yaml": "runtime",
            "task_graph.yaml": "task_graph",
            "tools.yaml": "tools",
            "mcp.yaml": "mcp",
            "context.yaml": "context",
            "memory.yaml": "memory",
            "harness.yaml": "harness",
        }[filename]

    @staticmethod
    def _condition_field_name(filename: str) -> str:
        return {
            "environment.yaml": "environment",
            "resource_contracts.yaml": "resource_contracts",
            "readiness.yaml": "readiness",
        }[filename]
