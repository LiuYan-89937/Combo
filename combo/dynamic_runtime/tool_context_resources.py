from __future__ import annotations

import json
from typing import Any, Mapping

from jsonschema import Draft202012Validator
from pydantic import JsonValue

from combo.resource_system import ResourceDescriptor, ResourceIdentity, ResourceStore


class ToolContextResources:
    """Validate and store ToolPackage context values for a published revision."""

    def __init__(self, store: ResourceStore) -> None:
        self._store = store

    @staticmethod
    def parse_value(name: str, value: object, value_type: str) -> JsonValue:
        raw = str(value or "")
        if not raw.strip():
            raise ValueError(f"Context value must not be empty: {name}")
        try:
            if value_type == "string":
                converted: JsonValue = raw
            elif value_type == "integer":
                converted = int(raw.strip())
            elif value_type == "number":
                converted = float(raw.strip())
            elif value_type == "boolean":
                normalized = raw.strip().lower()
                if normalized not in {"true", "false"}:
                    raise ValueError("expected true or false")
                converted = normalized == "true"
            elif value_type in {"object", "array"}:
                converted = json.loads(raw)
            else:
                raise ValueError(f"unsupported type: {value_type}")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid Context value for {name}: {exc}") from exc
        errors = list(Draft202012Validator({"type": value_type}).iter_errors(converted))
        if errors:
            raise ValueError(f"invalid Context value for {name}: {errors[0].message}")
        return converted

    def parse_payload(self, payload: Mapping[str, Any]) -> dict[str, JsonValue]:
        values: dict[str, JsonValue] = {}
        for item in payload.get("context_parameters", []):
            name = str(item["name"])
            raw = str(item.get("value") or "")
            if raw.strip():
                values[name] = self.parse_value(name, raw, str(item["type"]))
        return values

    def require_storage(self, values: Mapping[str, JsonValue]) -> None:
        if values and not self._store.key_available:
            raise ValueError("Context encryption is unavailable")

    @staticmethod
    def validate_values(
        values: Mapping[str, JsonValue],
        context_schema: Mapping[str, Any],
    ) -> None:
        properties = context_schema.get("properties", {})
        if not isinstance(properties, dict):
            raise ValueError("ToolPackage context_schema.properties must be an object")
        for name, value in values.items():
            schema = properties.get(name)
            if not isinstance(schema, dict):
                raise ValueError(f"Context field is not declared: {name}")
            errors = list(Draft202012Validator(schema).iter_errors(value))
            if errors:
                raise ValueError(f"invalid Context value for {name}: {errors[0].message}")

    @staticmethod
    def descriptor(
        *,
        capability_id: str,
        revision: int,
        name: str,
        schema: object,
    ) -> ResourceDescriptor:
        value_type = str(schema.get("type", "string")) if isinstance(schema, dict) else "string"
        return ResourceDescriptor(
            identity=ResourceIdentity(
                owner_kind="tool",
                owner_id=capability_id,
                owner_revision=revision,
                resource_id=name,
                resource_revision=1,
            ),
            purpose="tool_context",
            required=False,
            value_schema={"type": value_type},
        )

    def configured(self, descriptors: Mapping[str, ResourceDescriptor]) -> dict[str, bool]:
        statuses = self._store.status(list(descriptors.values()))
        return {
            name: bool(status.get("configured"))
            for (name, _), status in zip(descriptors.items(), statuses, strict=True)
        }

    def read(
        self,
        *,
        capability_id: str,
        revision: int,
        context_schema: Mapping[str, Any],
    ) -> dict[str, JsonValue]:
        properties = context_schema.get("properties")
        if not isinstance(properties, dict):
            return {}
        descriptors = {
            str(name): self.descriptor(
                capability_id=capability_id,
                revision=revision,
                name=str(name),
                schema=schema,
            )
            for name, schema in properties.items()
        }
        configured = self.configured(descriptors)
        return {
            name: self._store.resolve(descriptor)
            for name, descriptor in descriptors.items()
            if configured[name]
        }

    def stage_publication(
        self,
        *,
        operation_id: str,
        values: Mapping[str, JsonValue],
        context_schema: Mapping[str, Any],
    ) -> None:
        self.validate_values(values, context_schema)
        self.require_storage(values)
        self._store.prepare_publication(operation_id, values)

    def commit_publication(
        self,
        *,
        operation_id: str,
        capability_id: str,
        revision: int,
        context_schema: Mapping[str, Any],
        previous_revision: int | None = None,
        previous_context_schema: Mapping[str, Any] | None = None,
    ) -> None:
        properties = context_schema.get("properties", {})
        if not isinstance(properties, dict):
            raise ValueError("ToolPackage context_schema.properties must be an object")
        descriptors = {
            str(name): self.descriptor(
                capability_id=capability_id,
                revision=revision,
                name=str(name),
                schema=schema,
            )
            for name, schema in properties.items()
        }
        deletes = []
        if previous_revision is not None and previous_context_schema is not None:
            previous_properties = previous_context_schema.get("properties")
            if isinstance(previous_properties, dict):
                deletes = [
                    self.descriptor(
                        capability_id=capability_id,
                        revision=previous_revision,
                        name=str(name),
                        schema=schema,
                    ).identity
                    for name, schema in previous_properties.items()
                ]
        self._store.commit_publication(
            operation_id,
            descriptors=descriptors,
            deletes=deletes,
        )

    def publication_state(self, operation_id: str) -> str | None:
        return self._store.publication_state(operation_id)

    def discard_publication(self, operation_id: str) -> None:
        self._store.discard_publication(operation_id)

    def release_publication(self, operation_id: str) -> None:
        self._store.release_publication(operation_id)
