from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

JsonSchema = dict[str, Any]


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ValidationSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    FATAL = "fatal"


class Metadata(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    name: str
    version: str = "0.1.0"
    description: str | None = None
    owner: str | None = None


class BaseSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    schema_version: str
    kind: str
    metadata: Metadata


class ValidationIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: ValidationSeverity
    code: str
    message: str
    file: str | None = None
    path: str | None = None


class ValidationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_path: Path | None = None
    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(
            issue.severity in {ValidationSeverity.ERROR, ValidationSeverity.FATAL}
            for issue in self.issues
        )

    def add(
        self,
        severity: ValidationSeverity,
        code: str,
        message: str,
        *,
        file: str | None = None,
        path: str | None = None,
    ) -> None:
        self.issues.append(
            ValidationIssue(
                severity=severity,
                code=code,
                message=message,
                file=file,
                path=path,
            )
        )

