from __future__ import annotations

from pathlib import Path

from pydantic import ConfigDict

from agent_factory.core.types import JsonDumpMixin
from agent_factory.package import PackageValidator
from agent_factory.specs import ValidationReport


class ValidateAgentRequest(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    path: Path
    strict: bool = False


class ValidateAgentResult(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    report: ValidationReport

    @property
    def ok(self) -> bool:
        return self.report.ok


class ValidateAgentService:
    def __init__(self, validator: PackageValidator | None = None) -> None:
        self.validator = validator or PackageValidator()

    def validate_agent(self, request: ValidateAgentRequest) -> ValidateAgentResult:
        report = self.validator.validate_primitives(request.path)
        return ValidateAgentResult(report=report)
