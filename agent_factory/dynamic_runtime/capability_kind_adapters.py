from __future__ import annotations

from collections.abc import Iterable
from typing import ClassVar, Generic, TypeVar

from jsonschema import Draft7Validator, Draft201909Validator, Draft202012Validator
from jsonschema.exceptions import SchemaError
from pydantic import BaseModel, ValidationError

from agent_factory.dynamic_runtime.capability_adapters import (
    CapabilityAdapterValidation,
    CapabilityRuntimeProjection,
    CapabilityValidationDiagnostic,
)
from agent_factory.dynamic_runtime.capability_definitions import (
    DependencyDefinition,
    MCPServerDefinition,
    MCPSchemaEvidence,
    MCPToolDefinition,
    SkillDefinition,
    ToolDefinition,
)
from agent_factory.runtime_protocol import CapabilityDraft, CapabilityKind, CapabilityRevision


DefinitionT = TypeVar("DefinitionT", bound=BaseModel)


class TypedCapabilityAdapter(Generic[DefinitionT]):
    kind: ClassVar[CapabilityKind]
    adapter_id: ClassVar[str]
    adapter_revision: ClassVar[str] = "1"
    definition_schema: ClassVar[str]
    definition_model: ClassVar[type[BaseModel]]

    def validate(self, draft: CapabilityDraft) -> CapabilityAdapterValidation:
        diagnostics: list[CapabilityValidationDiagnostic] = []
        if draft.content.definition_schema != self.definition_schema:
            diagnostics.append(
                _diagnostic(
                    code="definition_schema_mismatch",
                    message=(
                        f"{self.kind} capability requires definition schema "
                        f"{self.definition_schema}, got {draft.content.definition_schema}"
                    ),
                    path=("content", "definition_schema"),
                )
            )
        else:
            try:
                definition = self.definition_model.model_validate(draft.content.definition)
            except ValidationError as exc:
                diagnostics.extend(_pydantic_diagnostics(exc))
            else:
                diagnostics.extend(self._validate_definition(draft, definition))
        return CapabilityAdapterValidation(
            capability_id=draft.capability_id,
            kind=draft.kind,
            draft_revision=draft.draft_revision,
            content_digest=draft.content_digest,
            diagnostics=tuple(diagnostics),
        )

    def project(self, revision: CapabilityRevision) -> CapabilityRuntimeProjection:
        if revision.content.definition_schema != self.definition_schema:
            raise ValueError(
                f"published {self.kind} revision uses unsupported definition schema: "
                f"{revision.content.definition_schema}"
            )
        definition = self.definition_model.model_validate(revision.content.definition)
        return self._project_definition(revision, definition)

    def _validate_definition(
        self,
        draft: CapabilityDraft,
        definition: BaseModel,
    ) -> tuple[CapabilityValidationDiagnostic, ...]:
        return ()

    def _project_definition(
        self,
        revision: CapabilityRevision,
        definition: BaseModel,
    ) -> CapabilityRuntimeProjection:
        return CapabilityRuntimeProjection(
            capability_id=revision.capability_id,
            kind=revision.kind,
            revision=revision.revision,
            content_digest=revision.content_digest,
            dependencies=revision.content.dependencies,
            resources=revision.content.resources,
            runtime_definition_schema=self.definition_schema,
            runtime_definition=definition.model_dump(mode="json"),
        )


class SkillCapabilityAdapter(TypedCapabilityAdapter[SkillDefinition]):
    kind = "skill"
    adapter_id = "dynamic_runtime.skill"
    definition_schema = "skill_definition.v1"
    definition_model = SkillDefinition

    def _project_definition(
        self,
        revision: CapabilityRevision,
        definition: BaseModel,
    ) -> CapabilityRuntimeProjection:
        skill = _require_definition(definition, SkillDefinition)
        return _projection(
            revision,
            schema=self.definition_schema,
            definition=skill,
            prompt_fragments=(skill.instructions,),
        )


class ToolCapabilityAdapter(TypedCapabilityAdapter[ToolDefinition]):
    kind = "tool"
    adapter_id = "dynamic_runtime.tool"
    definition_schema = "tool_definition.v1"
    definition_model = ToolDefinition

    def _validate_definition(
        self,
        draft: CapabilityDraft,
        definition: BaseModel,
    ) -> tuple[CapabilityValidationDiagnostic, ...]:
        tool = _require_definition(definition, ToolDefinition)
        diagnostics = [
            *_schema_diagnostics(tool.input_schema, path=("content", "definition", "input_schema")),
            *_schema_diagnostics(tool.output_schema, path=("content", "definition", "output_schema")),
        ]
        diagnostics.extend(
            _resource_binding_diagnostics(
                bindings=(
                    (item.resource_id, item.resource_revision, item.purpose)
                    for item in tool.resource_bindings
                ),
                draft=draft,
                path=("content", "definition", "resource_bindings"),
            )
        )
        return tuple(diagnostics)

    def _project_definition(
        self,
        revision: CapabilityRevision,
        definition: BaseModel,
    ) -> CapabilityRuntimeProjection:
        tool = _require_definition(definition, ToolDefinition)
        return _projection(
            revision,
            schema=self.definition_schema,
            definition=tool,
            model_tool_ids=(tool.model_alias,),
        )


class MCPServerCapabilityAdapter(TypedCapabilityAdapter[MCPServerDefinition]):
    kind = "mcp_server"
    adapter_id = "dynamic_runtime.mcp_server"
    definition_schema = "mcp_server_definition.v1"
    definition_model = MCPServerDefinition

    def _validate_definition(
        self,
        draft: CapabilityDraft,
        definition: BaseModel,
    ) -> tuple[CapabilityValidationDiagnostic, ...]:
        server = _require_definition(definition, MCPServerDefinition)
        return tuple(
            _resource_binding_diagnostics(
                bindings=(
                    (item.resource_id, item.resource_revision, item.purpose)
                    for item in server.resource_bindings
                ),
                draft=draft,
                path=("content", "definition", "resource_bindings"),
            )
        )


class MCPToolCapabilityAdapter(TypedCapabilityAdapter[MCPToolDefinition]):
    kind = "mcp_tool"
    adapter_id = "dynamic_runtime.mcp_tool"
    definition_schema = "mcp_tool_definition.v1"
    definition_model = MCPToolDefinition

    def _validate_definition(
        self,
        draft: CapabilityDraft,
        definition: BaseModel,
    ) -> tuple[CapabilityValidationDiagnostic, ...]:
        tool = _require_definition(definition, MCPToolDefinition)
        diagnostics: list[CapabilityValidationDiagnostic] = []
        server_dependencies = [
            item
            for item in draft.content.dependencies
            if item.kind == "mcp_server" and item.capability_id == tool.server_capability_id and item.required
        ]
        if len(server_dependencies) != 1:
            diagnostics.append(
                _diagnostic(
                    code="mcp_server_dependency_missing",
                    message="MCP tool requires exactly one required dependency on its server capability",
                    path=("content", "dependencies"),
                )
            )
        diagnostics.extend(
            _mcp_schema_evidence_diagnostics(
                tool.input_schema,
                path=("content", "definition", "input_schema"),
            )
        )
        diagnostics.extend(
            _mcp_schema_evidence_diagnostics(
                tool.output_schema,
                path=("content", "definition", "output_schema"),
            )
        )
        return tuple(diagnostics)

    def _project_definition(
        self,
        revision: CapabilityRevision,
        definition: BaseModel,
    ) -> CapabilityRuntimeProjection:
        tool = _require_definition(definition, MCPToolDefinition)
        return _projection(
            revision,
            schema=self.definition_schema,
            definition=tool,
            model_tool_ids=(tool.model_alias,),
        )


class DependencyCapabilityAdapter(TypedCapabilityAdapter[DependencyDefinition]):
    kind = "dependency"
    adapter_id = "dynamic_runtime.dependency"
    definition_schema = "dependency_definition.v1"
    definition_model = DependencyDefinition

    def _validate_definition(
        self,
        draft: CapabilityDraft,
        definition: BaseModel,
    ) -> tuple[CapabilityValidationDiagnostic, ...]:
        dependency = _require_definition(definition, DependencyDefinition)
        cycle = _dependency_cycle(dependency)
        if cycle is None:
            return ()
        return (
            _diagnostic(
                code="dependency_graph_cycle",
                message="resolved dependency graph contains a cycle",
                path=("content", "definition", "artifacts"),
                details={"cycle": " -> ".join(cycle)},
            ),
        )


def default_capability_adapters() -> tuple[TypedCapabilityAdapter[BaseModel], ...]:
    return (
        SkillCapabilityAdapter(),
        ToolCapabilityAdapter(),
        MCPServerCapabilityAdapter(),
        MCPToolCapabilityAdapter(),
        DependencyCapabilityAdapter(),
    )


def _projection(
    revision: CapabilityRevision,
    *,
    schema: str,
    definition: BaseModel,
    prompt_fragments: tuple[str, ...] = (),
    model_tool_ids: tuple[str, ...] = (),
) -> CapabilityRuntimeProjection:
    return CapabilityRuntimeProjection(
        capability_id=revision.capability_id,
        kind=revision.kind,
        revision=revision.revision,
        content_digest=revision.content_digest,
        model_prompt_fragments=prompt_fragments,
        model_tool_ids=model_tool_ids,
        dependencies=revision.content.dependencies,
        resources=revision.content.resources,
        runtime_definition_schema=schema,
        runtime_definition=definition.model_dump(mode="json"),
    )


def _pydantic_diagnostics(exc: ValidationError) -> tuple[CapabilityValidationDiagnostic, ...]:
    return tuple(
        _diagnostic(
            code="definition_validation_error",
            message=str(error.get("msg") or "invalid capability definition"),
            path=("content", "definition", *(str(item) for item in error.get("loc", ()))),
            details={"error_type": str(error.get("type") or "value_error")},
        )
        for error in exc.errors(include_url=False, include_context=False, include_input=False)
    )


def _schema_diagnostics(
    schema: dict[str, object],
    *,
    path: tuple[str, ...],
) -> tuple[CapabilityValidationDiagnostic, ...]:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        return (
            _diagnostic(
                code="invalid_json_schema",
                message=exc.message,
                path=(*path, *(str(item) for item in exc.absolute_schema_path)),
            ),
        )
    return ()


def _mcp_schema_evidence_diagnostics(
    evidence: MCPSchemaEvidence,
    *,
    path: tuple[str, ...],
) -> tuple[CapabilityValidationDiagnostic, ...]:
    diagnostics: list[CapabilityValidationDiagnostic] = []
    validator = {
        "draft_2020_12": Draft202012Validator,
        "draft_2019_09": Draft201909Validator,
        "draft_07": Draft7Validator,
        "mcp_unspecified": None,
    }[evidence.dialect]
    if validator is not None:
        try:
            validator.check_schema(evidence.source_schema)
        except SchemaError as exc:
            diagnostics.append(
                _diagnostic(
                    code="invalid_mcp_source_schema",
                    message=exc.message,
                    path=(*path, "source_schema", *(str(item) for item in exc.absolute_schema_path)),
                )
            )
    diagnostics.extend(_schema_diagnostics(evidence.canonical_schema, path=(*path, "canonical_schema")))
    for index, projection in enumerate(evidence.provider_projections):
        diagnostics.extend(
            _schema_diagnostics(
                projection.projected_schema,
                path=(*path, "provider_projections", str(index), "projected_schema"),
            )
        )
    return tuple(diagnostics)


def _resource_binding_diagnostics(
    *,
    bindings: Iterable[tuple[str, int, str]],
    draft: CapabilityDraft,
    path: tuple[str, ...],
) -> tuple[CapabilityValidationDiagnostic, ...]:
    declared = {
        (item.resource_id, item.revision, item.purpose)
        for item in draft.content.resources
    }
    diagnostics: list[CapabilityValidationDiagnostic] = []
    for index, binding in enumerate(bindings):
        if binding not in declared:
            diagnostics.append(
                _diagnostic(
                    code="resource_binding_not_declared",
                    message="runtime resource binding must reference an exact CapabilityContent resource revision",
                    path=(*path, str(index)),
                    details={
                        "resource_id": binding[0],
                        "resource_revision": binding[1],
                        "purpose": binding[2],
                    },
                )
            )
    return tuple(diagnostics)


def _dependency_cycle(definition: DependencyDefinition) -> tuple[str, ...] | None:
    graph = {item.artifact_id: item.dependencies for item in definition.artifacts}
    visiting: list[str] = []
    active: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> tuple[str, ...] | None:
        if node in active:
            start = visiting.index(node)
            return tuple([*visiting[start:], node])
        if node in visited:
            return None
        active.add(node)
        visiting.append(node)
        for dependency in graph[node]:
            cycle = visit(dependency)
            if cycle is not None:
                return cycle
        visiting.pop()
        active.remove(node)
        visited.add(node)
        return None

    for artifact_id in sorted(graph):
        cycle = visit(artifact_id)
        if cycle is not None:
            return cycle
    return None


def _diagnostic(
    *,
    code: str,
    message: str,
    path: tuple[str, ...],
    details: dict[str, object] | None = None,
) -> CapabilityValidationDiagnostic:
    normalized_details = {
        str(key): value if isinstance(value, (str, int, float, bool)) or value is None else str(value)
        for key, value in (details or {}).items()
    }
    return CapabilityValidationDiagnostic(
        code=code,
        severity="error",
        message=message,
        path=path,
        details=normalized_details,
    )


def _require_definition(value: BaseModel, expected: type[DefinitionT]) -> DefinitionT:
    if not isinstance(value, expected):
        raise TypeError(f"expected {expected.__name__}, got {type(value).__name__}")
    return value
