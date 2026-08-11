from __future__ import annotations

import json
from typing import Any, Callable, Mapping

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel

from agent_factory.tooling.execution_context import current_tool_call
from agent_factory.tooling.approval_policy import ToolApprovalPolicyConfig
from agent_factory.tooling.gateway import (
    ToolApprovalHandler,
    ToolApprovalTrustResolver,
    ToolExecutionGateway,
)
from agent_factory.resource_system import RESOURCE_RESOLVER_KEY
from agent_factory.tooling.output_store import (
    TOOL_OUTPUT_STORE_RESOURCE,
    ToolOutputPolicy,
    ToolOutputStore,
)
from agent_factory.tooling.schema_compiler import compile_json_schema
from agent_factory.tooling.spec import ToolSpec


class ToolCompileError(ValueError):
    pass


class ToolCompiler:
    def __init__(
        self,
        *,
        resources: Mapping[str, Any] | None = None,
        approval_handler: ToolApprovalHandler | None = None,
        approval_policy: ToolApprovalPolicyConfig,
        max_revisions: int,
        output_policy: ToolOutputPolicy,
        compression_model_resolver: Callable[[], Any] | None = None,
        approval_trust_store: ToolApprovalTrustResolver | None = None,
    ) -> None:
        if max_revisions < 1:
            raise ValueError("max_revisions must be positive")
        self.resources = resources or {}
        self.approval_handler = approval_handler
        self.approval_policy = approval_policy
        self.max_revisions = max_revisions
        self.output_store = _output_store_from_resources(self.resources)
        self.output_policy = output_policy
        self.compression_model_resolver = compression_model_resolver
        self.approval_trust_store = approval_trust_store

    def compile_resolved(
        self,
        spec: ToolSpec,
        *,
        entrypoint: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
        hard_risk_evaluator: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
    ) -> BaseTool:
        """Compile an already materialized entrypoint without consulting a registry or filesystem."""
        if not callable(entrypoint):
            raise ToolCompileError(f"cannot compile tool {spec.id}: resolved entrypoint is not callable")
        try:
            input_schema = compile_json_schema(schema=spec.input_schema, model_name=f"{spec.id}_args")
            output_schema = compile_json_schema(schema=spec.output_schema, model_name=f"{spec.id}_output")
        except Exception as exc:
            raise ToolCompileError(f"cannot compile tool {spec.id}: {exc}") from exc
        gateway = ToolExecutionGateway(
            spec=spec,
            input_schema=input_schema,
            output_schema=output_schema,
            entrypoint=entrypoint,
            global_resources=self.resources,
            resource_resolver=self.resources.get(RESOURCE_RESOLVER_KEY),
            hard_risk_evaluator=hard_risk_evaluator,
            llm_risk_prompt=None,
            approval_handler=self.approval_handler,
            approval_policy=self.approval_policy,
            max_revisions=self.max_revisions,
            output_store=self.output_store,
            output_policy=self.output_policy,
            approval_trust_store=self.approval_trust_store,
            compression_model_resolver=self.compression_model_resolver,
        )

        def invoke_tool(**kwargs: Any) -> dict[str, Any]:
            current = current_tool_call()
            arguments = _strip_unset_none_values(
                _normalize_tool_arguments(dict(kwargs)),
                schema=spec.input_schema,
            )
            return gateway.execute(
                arguments,
                tool_call_id=current.tool_call_id if current is not None and current.tool_id == spec.id else None,
            )

        return StructuredTool.from_function(
            func=invoke_tool,
            name=spec.id,
            description=spec.description,
            args_schema=input_schema.schema,
            infer_schema=False,
            metadata={
                "agent_factory": {
                    "tool_id": spec.id,
                    "concurrent": spec.concurrent,
                    "max_parallel_calls": spec.max_parallel_calls,
                    "risk_level": spec.risk_level,
                    "approval_request": gateway.approval_request,
                    "trust_tool": (
                        self.approval_trust_store.trust_tool
                        if self.approval_trust_store is not None
                        else None
                    ),
                    "loop_policy": spec.loop_policy.model_dump(mode="json", exclude_none=True),
                    "sensitive_argument_paths": list(spec.sensitive_argument_paths),
                    "base_description": spec.description,
                    "description_context": spec.description_context.model_dump(mode="json"),
                }
            },
            handle_validation_error=lambda error: json.dumps(
                {
                    "type": "tool_observation",
                    "status": "invalid_arguments",
                    "tool_id": spec.id,
                    "message": "Tool arguments failed transport validation.",
                    "retryable": True,
                    "errors": [str(error)],
                },
                ensure_ascii=False,
            ),
        )

def _normalize_tool_arguments(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _normalize_tool_arguments(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {key: _normalize_tool_arguments(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_tool_arguments(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_tool_arguments(item) for item in value]
    return value


def _strip_unset_none_values(value: Any, *, schema: dict[str, Any]) -> Any:
    if not isinstance(value, dict) or not isinstance(schema, dict):
        return value
    if _schema_type(schema) != "object":
        return value
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        return value
    required = set(schema.get("required") or [])
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        field_schema = properties.get(key)
        if not isinstance(field_schema, dict):
            cleaned[key] = item
            continue
        if item is None and key not in required and not _schema_accepts_null(field_schema):
            continue
        cleaned[key] = _strip_nested_none_values(item, schema=field_schema)
    return cleaned


def _strip_nested_none_values(value: Any, *, schema: dict[str, Any]) -> Any:
    schema_type = _schema_type(schema)
    if schema_type == "object" and isinstance(value, dict):
        return _strip_unset_none_values(value, schema=schema)
    if schema_type == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        if not isinstance(item_schema, dict):
            return value
        return [_strip_nested_none_values(item, schema=item_schema) for item in value]
    return value


def _schema_type(schema: dict[str, Any]) -> Any:
    return schema.get("type", "object")


def _schema_accepts_null(schema: dict[str, Any]) -> bool:
    schema_type = schema.get("type")
    if schema_type == "null":
        return True
    if isinstance(schema_type, list) and "null" in schema_type:
        return True
    for keyword in ("anyOf", "oneOf"):
        options = schema.get(keyword)
        if isinstance(options, list) and any(
            isinstance(option, dict) and _schema_accepts_null(option) for option in options
        ):
            return True
    return False


def _output_store_from_resources(resources: Mapping[str, Any]) -> ToolOutputStore | None:
    value = resources.get(TOOL_OUTPUT_STORE_RESOURCE)
    return value if isinstance(value, ToolOutputStore) else None
