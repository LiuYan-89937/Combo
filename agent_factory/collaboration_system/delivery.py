from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DeliveryFieldRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    path: str | None = None
    selector: Literal["document", "markdown_section", "json_pointer"] = "markdown_section"
    selector_value: str | None = None
    value_type: Literal["text", "number", "list", "table", "object"] = "text"
    minimum_chars: int = Field(default=1, ge=1)
    minimum_items: int = Field(default=1, ge=1)
    contains_all: list[str] = Field(default_factory=list)
    contains_any: list[str] = Field(default_factory=list)

    @field_validator("name", mode="before")
    @classmethod
    def _normalize_name(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("field requirement name must not be empty")
        return text

    @field_validator("path", "selector_value", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @field_validator("contains_all", "contains_any", mode="before")
    @classmethod
    def _normalize_match_terms(cls, value: Any) -> list[str]:
        return _normalize_text_list(value)

    @model_validator(mode="after")
    def _validate_selector(self) -> "DeliveryFieldRequirement":
        if self.path:
            self.path = _safe_relative_output_path(self.path)
        if self.selector == "markdown_section" and not self.selector_value:
            self.selector_value = self.name
        if self.selector == "json_pointer":
            if not self.selector_value or not self.selector_value.startswith("/"):
                raise ValueError("json_pointer selector requires selector_value beginning with '/'")
        if self.selector == "document" and self.selector_value:
            raise ValueError("document selector does not accept selector_value")
        return self


class CollaborationDeliveryStandard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: str | None = None
    output_path: str | None = None
    output_paths: list[str] = Field(default_factory=list)
    required_fields: list[DeliveryFieldRequirement] = Field(default_factory=list)
    require_visible_result: bool = True
    minimum_visible_chars: int = Field(default=1, ge=1)

    @field_validator("format", "output_path", mode="before")
    @classmethod
    def _normalize_optional_text(cls, value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @field_validator("output_paths", mode="before")
    @classmethod
    def _normalize_text_list(cls, value: Any) -> list[str]:
        return _normalize_text_list(value)

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
        expected_paths = set(normalized)
        names: set[str] = set()
        for requirement in self.required_fields:
            if requirement.name in names:
                raise ValueError(f"duplicate required field name: {requirement.name}")
            names.add(requirement.name)
            if requirement.path is None:
                if len(normalized) != 1:
                    raise ValueError(
                        f"required field '{requirement.name}' must declare path when multiple outputs are expected"
                    )
                requirement.path = normalized[0]
            if requirement.path not in expected_paths:
                raise ValueError(
                    f"required field '{requirement.name}' references undeclared output path: {requirement.path}"
                )
        return self

    @property
    def expected_output_paths(self) -> tuple[str, ...]:
        return tuple(path for path in [self.output_path, *self.output_paths] if path)


class WorkerDeliveryFieldValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    path: str
    selector: str
    value_type: str
    passed: bool
    observed_chars: int
    observed_items: int
    errors: list[str]


class WorkerDeliveryValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    passed: bool
    expected_output_paths: list[str]
    delivered_output_paths: list[str]
    missing_output_paths: list[str]
    unchanged_output_paths: list[str]
    visible_result_chars: int
    field_validations: list[WorkerDeliveryFieldValidation]
    invalid_required_fields: list[str]
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
    field_validations = _validate_required_fields(
        standard=standard,
        worker_workdir=worker_workdir,
    )
    invalid_required_fields = [item.name for item in field_validations if not item.passed]
    if invalid_required_fields:
        errors.append("required output fields failed validation: " + ", ".join(invalid_required_fields))
    return WorkerDeliveryValidation(
        passed=not errors,
        expected_output_paths=list(standard.expected_output_paths),
        delivered_output_paths=delivered,
        missing_output_paths=missing,
        unchanged_output_paths=unchanged,
        visible_result_chars=len(content),
        field_validations=field_validations,
        invalid_required_fields=invalid_required_fields,
        errors=errors,
    )


def _validate_required_fields(
    *,
    standard: CollaborationDeliveryStandard,
    worker_workdir: Path,
) -> list[WorkerDeliveryFieldValidation]:
    document_cache: dict[str, str | Exception] = {}
    results: list[WorkerDeliveryFieldValidation] = []
    for requirement in standard.required_fields:
        relative = str(requirement.path or "")
        document = document_cache.get(relative)
        if document is None:
            path = worker_workdir / PurePosixPath(relative)
            try:
                document = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                document = exc
            document_cache[relative] = document
        results.append(_validate_required_field(requirement, relative=relative, document=document))
    return results


def _validate_required_field(
    requirement: DeliveryFieldRequirement,
    *,
    relative: str,
    document: str | Exception,
) -> WorkerDeliveryFieldValidation:
    errors: list[str] = []
    if isinstance(document, Exception):
        errors.append(f"unable to read UTF-8 text output: {type(document).__name__}")
        return _field_validation_result(requirement, relative, errors=errors)
    try:
        value, selected_text = _select_field_value(requirement, document)
    except (ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
        return _field_validation_result(requirement, relative, errors=errors)

    observed_chars = len(selected_text.strip())
    observed_items = _observed_item_count(requirement.value_type, value, selected_text)
    if requirement.value_type == "text" and observed_chars < requirement.minimum_chars:
        errors.append(
            f"selected text has {observed_chars} characters; minimum is {requirement.minimum_chars}"
        )
    if requirement.value_type != "text" and observed_items < requirement.minimum_items:
        errors.append(
            f"selected {requirement.value_type} has {observed_items} items; minimum is {requirement.minimum_items}"
        )
    normalized_text = selected_text.casefold()
    missing_terms = [term for term in requirement.contains_all if term.casefold() not in normalized_text]
    if missing_terms:
        errors.append("selected content is missing required terms: " + ", ".join(missing_terms))
    if requirement.contains_any and not any(term.casefold() in normalized_text for term in requirement.contains_any):
        errors.append("selected content contains none of the accepted terms: " + ", ".join(requirement.contains_any))
    return _field_validation_result(
        requirement,
        relative,
        observed_chars=observed_chars,
        observed_items=observed_items,
        errors=errors,
    )


def _select_field_value(requirement: DeliveryFieldRequirement, document: str) -> tuple[Any, str]:
    if requirement.selector == "document":
        return document, document
    if requirement.selector == "markdown_section":
        section = _markdown_section(document, str(requirement.selector_value or ""))
        if section is None:
            raise ValueError(f"markdown section not found: {requirement.selector_value}")
        return section, section
    value = _json_pointer_value(json.loads(document), str(requirement.selector_value or ""))
    if value is None:
        raise ValueError(f"json pointer resolves to null: {requirement.selector_value}")
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value, text


def _markdown_section(document: str, heading: str) -> str | None:
    target = _normalize_heading(heading)
    matches = list(re.finditer(r"(?m)^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", document))
    for index, match in enumerate(matches):
        current = _normalize_heading(match.group(2))
        if target not in current:
            continue
        level = len(match.group(1))
        end = len(document)
        for following in matches[index + 1 :]:
            if len(following.group(1)) <= level:
                end = following.start()
                break
        return document[match.end() : end].strip()
    return None


def _json_pointer_value(document: Any, pointer: str) -> Any:
    current = document
    for raw_part in pointer.split("/")[1:]:
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list):
            try:
                current = current[int(part)]
                continue
            except (ValueError, IndexError):
                pass
        raise ValueError(f"json pointer not found: {pointer}")
    return current


def _observed_item_count(value_type: str, value: Any, text: str) -> int:
    if value_type == "number":
        return len(re.findall(r"(?<![\w.])[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?![\w.])", text))
    if value_type == "list":
        if isinstance(value, list):
            return len(value)
        return len(re.findall(r"(?m)^[ \t]*(?:[-*+] |\d+[.)][ \t]+)", text))
    if value_type == "table":
        rows = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
        return len([line for line in rows if not re.fullmatch(r"\|?[ :|-]+\|?", line)]) - (1 if rows else 0)
    if value_type == "object":
        return len(value) if isinstance(value, dict) else 0
    return 1 if text.strip() else 0


def _field_validation_result(
    requirement: DeliveryFieldRequirement,
    relative: str,
    *,
    observed_chars: int = 0,
    observed_items: int = 0,
    errors: list[str],
) -> WorkerDeliveryFieldValidation:
    return WorkerDeliveryFieldValidation(
        name=requirement.name,
        path=relative,
        selector=requirement.selector,
        value_type=requirement.value_type,
        passed=not errors,
        observed_chars=observed_chars,
        observed_items=max(observed_items, 0),
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


def _normalize_heading(value: str) -> str:
    return "".join(str(value).casefold().split())
