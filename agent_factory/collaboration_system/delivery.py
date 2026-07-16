from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CollaborationDeliveryStandard(BaseModel):
    model_config = ConfigDict(extra="allow")

    format: str | None = None
    output_path: str | None = None
    output_paths: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    require_visible_result: bool = True
    minimum_visible_chars: int = Field(default=1, ge=1)

    @field_validator("format", "output_path", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @field_validator("output_paths", "required_fields", mode="before")
    @classmethod
    def _normalize_text_list(cls, value: Any) -> list[str]:
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

    @model_validator(mode="after")
    def _validate_output_paths(self) -> "CollaborationDeliveryStandard":
        paths = [self.output_path, *self.output_paths]
        normalized: list[str] = []
        for value in paths:
            if not value:
                continue
            path = _safe_relative_output_path(value)
            if path not in normalized:
                normalized.append(path)
        if not normalized:
            raise ValueError("delivery_standard requires output_path or output_paths")
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
    visible_result_chars: int
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
    standard = CollaborationDeliveryStandard.model_validate(value)
    content = str(visible_result or "").strip()
    missing: list[str] = []
    unchanged: list[str] = []
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
        delivered.append(relative)
    errors: list[str] = []
    if standard.require_visible_result and len(content) < standard.minimum_visible_chars:
        errors.append(
            f"visible result has {len(content)} characters; minimum is {standard.minimum_visible_chars}"
        )
    if missing:
        errors.append("missing required output files: " + ", ".join(missing))
    if unchanged:
        errors.append("required output files were not produced by this run: " + ", ".join(unchanged))
    return WorkerDeliveryValidation(
        passed=not errors,
        expected_output_paths=list(standard.expected_output_paths),
        delivered_output_paths=delivered,
        missing_output_paths=missing,
        unchanged_output_paths=unchanged,
        visible_result_chars=len(content),
        errors=errors,
    )


def _safe_relative_output_path(value: str) -> str:
    path = PurePosixPath(str(value).replace("\\", "/"))
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"delivery output path must be a safe relative path: {value}")
    if path.parts[0] == "share_files":
        raise ValueError("delivery output path must not be under share_files/")
    return path.as_posix()
