from __future__ import annotations

from dataclasses import dataclass

from agent_factory.assembly.schema import AgentAssemblySpec
from agent_factory.assembly.validator import AgentAssemblyValidator
from agent_factory.runtime_kernel.bindings import RuntimeServices
from agent_factory.runtime_kernel.errors import RuntimeKernelError
from agent_factory.runtime_kernel.kernel import CompiledKernelApp, RuntimeKernelFacade
from agent_factory.runtime_kernel.patterns.schema import GraphPatternSpec
from agent_factory.runtime_render import RenderManifest, validate_render_manifest


@dataclass(slots=True)
class CompiledAgentAssembly:
    spec: AgentAssemblySpec
    pattern_spec: GraphPatternSpec
    compiled_app: CompiledKernelApp

    @property
    def runtime_config(self) -> dict:
        return {
            "user_config": dict(self.spec.runtime.user_config),
            "agent_config": dict(self.spec.runtime.agent_config),
            "session_config": dict(self.spec.runtime.session_config),
        }


class AgentAssemblyCompiler:
    def __init__(self, *, facade: RuntimeKernelFacade | None = None) -> None:
        self.facade = facade or RuntimeKernelFacade()
        self.validator = AgentAssemblyValidator(pattern_registry=self.facade.instance.pattern_registry)

    def compile(
        self,
        spec: AgentAssemblySpec,
        *,
        services: RuntimeServices | None = None,
    ) -> CompiledAgentAssembly:
        self.validator.validate(spec)
        assembled_pattern = self._assemble_pattern(spec)
        render_manifest = self._render_manifest_for_spec(spec, assembled_pattern)
        self.facade.instance.pattern_registry.register(assembled_pattern)
        compiled_app = self.facade.compile(
            pattern_id=assembled_pattern.pattern_id,
            bindings=spec.bindings,
            services=services,
            render_manifest=render_manifest,
        )
        return CompiledAgentAssembly(
            spec=spec,
            pattern_spec=assembled_pattern,
            compiled_app=compiled_app,
        )

    def run(
        self,
        compiled: CompiledAgentAssembly,
        *,
        user_input: str,
        services: RuntimeServices | None = None,
    ):
        if services is not None and services is not compiled.compiled_app.services:
            compiled = self.compile(compiled.spec, services=services)
        return self.facade.run(
            compiled.compiled_app,
            user_input=user_input,
            **compiled.runtime_config,
        )

    def _assemble_pattern(self, spec: AgentAssemblySpec) -> GraphPatternSpec:
        base_pattern = self.facade.instance.pattern_registry.get(spec.runtime.pattern_id)
        assembled = base_pattern.model_copy(deep=True)
        assembled.pattern_id = spec.runtime.compiled_pattern_id or f"{spec.agent.id}__{base_pattern.pattern_id}"
        assembled.name = f"{spec.agent.id} assembly"
        node_map = {node.id: node for node in assembled.nodes}
        for override in spec.graph_overrides.node_wrappers:
            node = node_map[override.node_id]
            if override.replace_existing:
                node.wrappers = list(override.wrappers)
            else:
                node.wrappers = [*node.wrappers, *override.wrappers]
        return assembled

    def _render_manifest_for_spec(self, spec: AgentAssemblySpec, pattern: GraphPatternSpec) -> RenderManifest:
        raw_manifest = spec.metadata.get("render_manifest")
        if not raw_manifest:
            raise RuntimeKernelError("AgentAssemblySpec.metadata.render_manifest is required for generated agent compilation.")
        manifest = RenderManifest.model_validate(raw_manifest)
        return validate_render_manifest(manifest, {node.id for node in pattern.nodes})
