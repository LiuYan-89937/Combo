from __future__ import annotations

from dataclasses import dataclass
import importlib
import re
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, create_model
from jsonschema.exceptions import best_match


class ToolSchemaError(ValueError):
    pass


@dataclass(slots=True)
class CompiledJsonSchema:
    schema: dict[str, Any]
    pydantic_model: type[BaseModel]
    validator: Any

    def errors_for(self, value: Any) -> list[str]:
        errors = sorted(self.validator.iter_errors(value), key=lambda item: tuple(str(part) for part in item.absolute_path))
        return list(dict.fromkeys(
            _format_error(detail)
            for error in errors
            for detail in _relevant_errors(error)
        ))

    def validate(self, value: Any) -> None:
        errors = self.errors_for(value)
        if errors:
            raise ToolSchemaError("; ".join(errors))


def compile_json_schema(*, schema: dict[str, Any], model_name: str) -> CompiledJsonSchema:
    normalized = _normalize_schema(schema)
    validator_cls = _draft_validator()
    try:
        validator_cls.check_schema(normalized)
    except Exception as exc:  # jsonschema raises several schema-specific exception types.
        raise ToolSchemaError(f"invalid JSON schema: {exc}") from exc
    return CompiledJsonSchema(
        schema=normalized,
        pydantic_model=_pydantic_model_from_schema(normalized, model_name),
        validator=validator_cls(normalized),
    )


def _draft_validator():
    try:
        return importlib.import_module("jsonschema").Draft202012Validator
    except ModuleNotFoundError as exc:
        raise ToolSchemaError("jsonschema dependency is required for tool schema validation") from exc


def _normalize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    if not schema:
        return {"type": "object", "properties": {}, "additionalProperties": False}
    if not isinstance(schema, dict):
        raise ToolSchemaError("schema must be a JSON object")
    normalized = dict(schema)
    normalized.setdefault("type", "object")
    if normalized.get("type") == "object":
        normalized.setdefault("properties", {})
    return normalized


def _pydantic_model_from_schema(schema: dict[str, Any], model_name: str) -> type[BaseModel]:
    if schema.get("type") != "object":
        raise ToolSchemaError("top-level tool schema must be a JSON object")
    fields: dict[str, Any] = {}
    required = set(schema.get("required") or [])
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        raise ToolSchemaError("object schema properties must be a JSON object")
    for field_name, field_schema in properties.items():
        if isinstance(field_schema, bool):
            annotation = Any
            default = ... if field_name in required else None
            fields[field_name] = (annotation, Field(default))
            continue
        if not isinstance(field_schema, dict):
            raise ToolSchemaError(f"field schema must be an object or boolean: {field_name}")
        annotation = _annotation_for_schema(field_schema, f"{model_name}_{field_name}")
        default = ... if field_name in required else field_schema.get("default", None)
        description = field_schema.get("description")
        fields[field_name] = (annotation, Field(default, description=description))
    extra = "forbid" if schema.get("additionalProperties") is False else "allow"
    return create_model(
        model_name,
        __config__=ConfigDict(extra=extra),
        **fields,
    )


def _annotation_for_schema(schema: dict[str, Any], model_name: str) -> Any:
    if "const" in schema:
        return Literal.__getitem__((schema["const"],))
    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and enum_values:
        return Literal.__getitem__(tuple(enum_values))
    if "anyOf" in schema or "oneOf" in schema:
        options = schema.get("anyOf") or schema.get("oneOf") or []
        annotations = [
            _annotation_for_schema(option, f"{model_name}_{index}")
            for index, option in enumerate(options)
            if isinstance(option, dict) and option.get("type") != "null"
        ]
        if not annotations:
            return Any
        if len(annotations) == 1:
            return annotations[0]
        return Union.__getitem__(tuple(annotations))
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        non_null = [item for item in schema_type if item != "null"]
        if len(non_null) == 1:
            return _annotation_for_schema({**schema, "type": non_null[0]}, model_name)
        return Any
    if schema_type == "string":
        return str
    if schema_type == "integer":
        return int
    if schema_type == "number":
        return float
    if schema_type == "boolean":
        return bool
    if schema_type == "array":
        item_schema = schema.get("items")
        item_annotation = _annotation_for_schema(item_schema, f"{model_name}_item") if isinstance(item_schema, dict) else Any
        return list[item_annotation]
    if schema_type == "object":
        properties = schema.get("properties")
        if isinstance(properties, dict) and properties:
            return _pydantic_model_from_schema(schema, model_name)
        return dict[str, Any]
    return Any


def _relevant_errors(error: Any) -> list[Any]:
    """Report the selected union variant, rather than an unrelated near match."""
    if error.context:
        if error.validator in {"oneOf", "anyOf"} and isinstance(error.instance, dict):
            selected: list[int] = []
            for index, branch in enumerate(error.validator_value):
                if not isinstance(branch, dict):
                    continue
                guards = [
                    (name, {key: constraint[key] for key in ("const", "enum") if key in constraint})
                    for name, constraint in branch.get("properties", {}).items()
                    if name in error.instance and isinstance(constraint, dict)
                    and ("const" in constraint or "enum" in constraint)
                ]
                if guards and all(
                    _draft_validator()(constraint).is_valid(error.instance[name])
                    for name, constraint in guards
                ):
                    selected.append(index)
            if len(selected) == 1:
                children = [
                    child for child in error.context
                    if child.schema_path and child.schema_path[0] == selected[0]
                ]
                if children:
                    return [detail for child in children for detail in _relevant_errors(child)]
        return _relevant_errors(best_match(error.context))
    return [error]


def _format_error(error: Any) -> str:
    path = [str(part) for part in error.absolute_path]
    if error.validator == "required" and isinstance(error.instance, dict):
        missing = [str(name) for name in error.validator_value if name not in error.instance]
        if len(missing) == 1:
            return f"{_location([*path, missing[0]])}: required property is missing"
    if error.validator == "additionalProperties" and isinstance(error.instance, dict):
        schema = error.schema if isinstance(error.schema, dict) else {}
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        patterns = schema.get("patternProperties") or {}
        unexpected = sorted(
            str(name) for name in set(error.instance) - set(properties)
            if not any(re.search(pattern, str(name)) for pattern in patterns)
        )
        if unexpected:
            return "; ".join(
                f"{_location([*path, name])}: property is not allowed"
                for name in unexpected
            )
    location = _location(path)
    validator = str(error.validator or "schema")
    constraint = error.validator_value
    messages = {
        "type": f"expected type {constraint}",
        "enum": f"must be one of {constraint}",
        "const": f"must equal {constraint!r}",
        "pattern": f"must match pattern {constraint!r}",
        "minimum": f"must be at least {constraint}",
        "maximum": f"must be at most {constraint}",
        "exclusiveMinimum": f"must be greater than {constraint}",
        "exclusiveMaximum": f"must be less than {constraint}",
        "minLength": f"must contain at least {constraint} characters",
        "maxLength": f"must contain at most {constraint} characters",
        "minItems": f"must contain at least {constraint} items",
        "maxItems": f"must contain at most {constraint} items",
        "additionalProperties": "contains properties that are not allowed",
    }
    return f"{location}: {messages.get(validator, f'failed schema constraint {validator!r}')}"


def validation_failure_message(subject: str, errors: list[str]) -> str:
    normalized_subject = str(subject or "value").strip()
    details = "; ".join(str(error).strip() for error in errors if str(error).strip())
    prefix = f"Tool {normalized_subject} failed schema validation"
    return f"{prefix}: {details}." if details else f"{prefix}."


def pydantic_validation_errors(error: Any) -> list[str]:
    try:
        items = error.errors(include_url=False, include_context=False, include_input=False)
    except (AttributeError, TypeError):
        return [f"<root>: {type(error).__name__}"]
    formatted: list[str] = []
    for item in items:
        location = _location([str(part) for part in item.get("loc") or ()])
        message = str(item.get("msg") or item.get("type") or "validation failed").strip()
        formatted.append(f"{location}: {message}")
    return formatted


def _location(path: list[str]) -> str:
    return ".".join(path) if path else "<root>"
