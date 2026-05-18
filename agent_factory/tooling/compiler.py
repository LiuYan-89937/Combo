from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel

from agent_factory.tooling.entrypoint import ToolEntrypointLoader
from agent_factory.tooling.entrypoints import EntrypointAdapterRegistry, MCPToolClient
from agent_factory.tooling.gateway import (
    ToolApprovalHandler,
    ToolExecutionGateway,
    default_tool_max_revisions,
)
from agent_factory.tooling.risk import ToolRiskEvaluator
from agent_factory.tooling.schema_compiler import compile_json_schema
from agent_factory.tooling.spec import ToolSpec


class ToolCompileError(ValueError):
    pass


class ToolCompiler:
    def __init__(
        self,
        *,
        package_root: str | Path | None = None,
        resources: Mapping[str, Any] | None = None,
        approval_handler: ToolApprovalHandler | None = None,
        max_revisions: int | None = None,
        entrypoint_loader: ToolEntrypointLoader | None = None,
        allowed_python_roots: list[str | Path] | None = None,
        adapter_registry: EntrypointAdapterRegistry | None = None,
        mcp_clients: Mapping[str, MCPToolClient] | None = None,
    ) -> None:
        self.package_root = Path(package_root).resolve() if package_root else None
        self.loader = entrypoint_loader or ToolEntrypointLoader(
            package_root=package_root,
            allowed_python_roots=allowed_python_roots,
            adapter_registry=adapter_registry,
            mcp_clients=mcp_clients,
        )
        self.resources = resources or {}
        self.approval_handler = approval_handler
        self.max_revisions = max_revisions or default_tool_max_revisions()

    def compile(self, spec: ToolSpec) -> BaseTool:
        try:
            input_schema = compile_json_schema(schema=spec.input_schema, model_name=f"{spec.id}_args")
            output_schema = compile_json_schema(schema=spec.output_schema, model_name=f"{spec.id}_output")
            entrypoint = self.loader.load(spec.entrypoint)
            hard_risk_evaluator = self._load_hard_risk_evaluator(spec)
            llm_risk_prompt = self._load_llm_risk_prompt(spec)
        except Exception as exc:
            raise ToolCompileError(f"cannot compile tool {spec.id}: {exc}") from exc
        gateway = ToolExecutionGateway(
            spec=spec,
            input_schema=input_schema,
            output_schema=output_schema,
            entrypoint=entrypoint,
            global_resources=self.resources,
            hard_risk_evaluator=hard_risk_evaluator,
            llm_risk_prompt=llm_risk_prompt,
            approval_handler=self.approval_handler,
            max_revisions=self.max_revisions,
        )

        def invoke_tool(**kwargs: Any) -> dict[str, Any]:
            return gateway.execute(_normalize_tool_arguments(dict(kwargs)))

        return StructuredTool.from_function(
            func=invoke_tool,
            name=spec.id,
            description=spec.description,
            args_schema=input_schema.pydantic_model,
            infer_schema=False,
            handle_validation_error=lambda error: json.dumps(
                {
                    "type": "tool_observation",
                    "status": "invalid_arguments",
                    "tool_id": spec.id,
                    "message": "Tool arguments failed Pydantic validation.",
                    "retryable": True,
                    "errors": [str(error)],
                },
                ensure_ascii=False,
            ),
        )

    def compile_many(self, specs: Iterable[ToolSpec]) -> list[BaseTool]:
        return [self.compile(spec) for spec in specs]

    def _load_hard_risk_evaluator(self, spec: ToolSpec) -> ToolRiskEvaluator | None:
        if not spec.risk_evaluator.hard:
            return None
        evaluator = self.loader.load(spec.risk_evaluator.hard)
        return evaluator

    def _load_llm_risk_prompt(self, spec: ToolSpec) -> str | None:
        value = spec.risk_evaluator.llm
        if not value:
            return None
        if self.package_root is None:
            return value
        candidate = (self.package_root / value).resolve()
        try:
            candidate.relative_to(self.package_root)
        except ValueError as exc:
            raise ToolCompileError(f"llm risk prompt escapes package root: {value}") from exc
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
        if value.endswith(".md"):
            raise ToolCompileError(f"llm risk prompt file does not exist: {value}")
        return value


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
