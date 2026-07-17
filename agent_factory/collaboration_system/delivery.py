from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DeliveryArtifactExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    kind: Literal["markdown", "json", "text", "binary"] | None = None
    description: str

    @field_validator("path", mode="before")
    @classmethod
    def _normalize_path(cls, value: Any) -> str:
        return _safe_relative_output_path(str(value or "").strip())

    @field_validator("description", mode="before")
    @classmethod
    def _normalize_description(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("delivery artifact description must not be empty")
        return text


class CollaborationDeliveryStandard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: str | None = None
    output_path: str | None = None
    output_paths: list[str] = Field(default_factory=list)
    artifacts: list[DeliveryArtifactExpectation] = Field(default_factory=list)
    acceptance_criteria: list[str]

    @field_validator("format", "output_path", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @field_validator("output_paths", "acceptance_criteria", mode="before")
    @classmethod
    def _normalize_text_list(cls, value: Any) -> list[str]:
        return _normalize_text_list(value)

    @model_validator(mode="after")
    def _validate_contract(self) -> "CollaborationDeliveryStandard":
        paths = [self.output_path, *self.output_paths, *(artifact.path for artifact in self.artifacts)]
        normalized: list[str] = []
        for value in paths:
            if not value:
                continue
            path = _safe_relative_output_path(value)
            if path not in normalized:
                normalized.append(path)
        if not normalized:
            raise ValueError("delivery_standard requires output_path, output_paths, or artifacts")
        if not self.acceptance_criteria:
            raise ValueError("delivery_standard requires semantic acceptance_criteria")
        artifact_paths: set[str] = set()
        for artifact in self.artifacts:
            if artifact.path in artifact_paths:
                raise ValueError(f"duplicate delivery artifact path: {artifact.path}")
            artifact_paths.add(artifact.path)
        self.output_path = normalized[0]
        self.output_paths = normalized[1:]
        return self

    @property
    def expected_output_paths(self) -> tuple[str, ...]:
        return tuple(path for path in [self.output_path, *self.output_paths] if path)


class WorkerDeliveryValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    expected_output_paths: list[str]
    delivered_output_paths: list[str]
    missing_output_paths: list[str]
    unchanged_output_paths: list[str]
    empty_output_paths: list[str]
    errors: list[str]


def normalize_delivery_standard(value: Any) -> dict[str, Any]:
    standard = CollaborationDeliveryStandard.model_validate(value)
    return standard.model_dump(mode="json", exclude_none=True)


def validate_worker_delivery(
    value: Any,
    *,
    visible_result: str,
    worker_workdir: Path,
    before_snapshot: dict[str, tuple[int, int]],
) -> WorkerDeliveryValidation:
    del visible_result
    standard = CollaborationDeliveryStandard.model_validate(value)
    missing: list[str] = []
    unchanged: list[str] = []
    empty: list[str] = []
    delivered: list[str] = []
    for relative in standard.expected_output_paths:
        path = worker_workdir / PurePosixPath(relative)
        if not path.is_file():
            missing.append(relative)
            continue
        stat = path.stat()
        current = (stat.st_size, stat.st_mtime_ns)
        if before_snapshot.get(relative) == current:
            unchanged.append(relative)
            continue
        if stat.st_size <= 0:
            empty.append(relative)
            continue
        delivered.append(relative)
    errors: list[str] = []
    if missing:
        errors.append("missing required output files: " + ", ".join(missing))
    if unchanged:
        errors.append("required output files were not produced by this run: " + ", ".join(unchanged))
    if empty:
        errors.append("required output files are empty: " + ", ".join(empty))
    return WorkerDeliveryValidation(
        passed=not errors,
        expected_output_paths=list(standard.expected_output_paths),
        delivered_output_paths=delivered,
        missing_output_paths=missing,
        unchanged_output_paths=unchanged,
        empty_output_paths=empty,
        errors=errors,
    )


def _safe_relative_output_path(value: str) -> str:
    path = PurePosixPath(str(value).replace("\\", "/"))
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"delivery output path must be a safe relative path: {value}")
    if path.parts[0] == "share_files":
        raise ValueError("delivery output path must not be under share_files/")
    return path.as_posix()


def _normalize_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError("value must be an array of non-empty strings")
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result
