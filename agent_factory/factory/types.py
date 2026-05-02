from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field

from agent_factory.core.types import JsonDumpMixin
from agent_factory.specs import AgentPackagePrimitives, ValidationReport


class FactoryError(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class FactoryCreateOptions(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    repair_attempts: int = 1


class FactoryPrimitiveDraft(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    requirement: str
    primitives: AgentPackagePrimitives | None = None
    validation_report: ValidationReport | None = None
    raw_model_data: dict[str, Any] | list[Any] | None = None
    repair_attempts: int = 0
    output_path: Path | None = None
    error: FactoryError | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.primitives is not None
