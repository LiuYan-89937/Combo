from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from agent_factory.dynamic_runtime.capability_definitions import (
    ToolDefinition,
    ToolImplementation,
    ToolLoopPolicy,
    ToolRuntimePolicy,
)
from agent_factory.runtime_protocol import CapabilityContent, CapabilityDraft
from agent_factory.tooling.builtins.browser.specs import get_browser_tool_specs
from agent_factory.tooling.builtins.capability.specs import get_capability_tool_specs
from agent_factory.tooling.builtins.delegation.specs import get_delegation_tool_specs
from agent_factory.tooling.builtins.filesystem.specs import get_filesystem_tool_specs
from agent_factory.tooling.builtins.knowledge.specs import get_knowledge_tool_specs
from agent_factory.tooling.builtins.memory.specs import get_memory_tool_specs
from agent_factory.tooling.builtins.process.specs import get_process_tool_specs
from agent_factory.tooling.builtins.scheduler.specs import get_scheduler_tool_specs
from agent_factory.tooling.builtins.skillhub.specs import get_skillhub_tool_specs
from agent_factory.tooling.builtins.tool_output.specs import get_tool_output_tool_specs
from agent_factory.tooling.output_store import TOOL_OUTPUT_STORE_RESOURCE
from agent_factory.tooling.spec import ToolSpec


@dataclass(frozen=True, slots=True)
class BuiltinToolSourceConfig:
    build_revision: str
    publisher_principal_id: str
    source_prefix: str
    overrides_path: Path

    def __post_init__(self) -> None:
        if not self.build_revision.strip():
            raise ValueError("builtin tool source requires a build revision")
        if not self.publisher_principal_id.strip():
            raise ValueError("builtin tool source requires a publisher principal")
        if not self.source_prefix.strip():
            raise ValueError("builtin tool source requires a source prefix")
        object.__setattr__(self, "overrides_path", Path(self.overrides_path).expanduser().resolve())


class BuiltinToolCapabilitySource:
    """Build-bound source artifacts; runtime resolution never consults this catalog."""

    def __init__(self, config: BuiltinToolSourceConfig) -> None:
        self._config = config

    def drafts(self) -> tuple[CapabilityDraft, ...]:
        specs = (
            *get_filesystem_tool_specs(),
            *get_process_tool_specs(),
            *get_tool_output_tool_specs(),
            *get_capability_tool_specs(),
            *get_delegation_tool_specs(),
            *get_memory_tool_specs(),
            *get_knowledge_tool_specs(),
            *get_scheduler_tool_specs(),
            *get_skillhub_tool_specs(),
            *get_browser_tool_specs(),
        )
        aliases = tuple(spec.id for spec in specs)
        if len(aliases) != len(set(aliases)):
            raise ValueError("builtin tool source contains duplicate model aliases")
        overrides = self._overrides()
        unknown = set(overrides).difference(aliases)
        if unknown:
            raise ValueError(f"builtin tool overrides reference unknown tools: {sorted(unknown)}")
        return tuple(self._draft(spec, overrides.get(spec.id, {})) for spec in specs)

    def _draft(self, spec: ToolSpec, override: dict[str, object]) -> CapabilityDraft:
        config = self._config
        runtime_resources = self._runtime_resources(spec)
        policy_override = override.get("runtime_policy") or {}
        if not isinstance(policy_override, dict):
            raise ValueError(f"builtin tool runtime policy override must be an object: {spec.id}")
        base_policy = ToolRuntimePolicy(
            risk_level=spec.risk_level,
            allow_parallel_calls=spec.concurrent,
            max_parallel_calls=spec.max_parallel_calls,
            serialization_key=None if spec.concurrent else spec.id,
            output_projection=spec.output_projection,
            output_max_model_chars=spec.output_compression.max_model_chars or 50_000,
            retain_raw_output=True,
        )
        policy = ToolRuntimePolicy.model_validate({
            **base_policy.model_dump(mode="json"),
            **policy_override,
        })
        description = str(override.get("description") or spec.description).strip()
        display_name = str(override.get("display_name") or spec.id).strip()
        definition = ToolDefinition(
            model_alias=spec.id,
            model_description=description,
            schema_error_guidance=spec.schema_error_guidance,
            input_schema=spec.input_schema,
            output_schema=spec.output_schema,
            implementation=ToolImplementation(
                kind="python_module",
                entrypoint=spec.entrypoint,
                hard_risk_evaluator_entrypoint=spec.risk_evaluator.hard,
            ),
            runtime_policy=policy,
            loop_policy=ToolLoopPolicy.model_validate(spec.loop_policy.model_dump(mode="json")),
            runtime_resources=runtime_resources,
            effects=tuple(spec.effects),
            read_only=spec.read_only,
            system_available=spec.system_available,
            sensitive_argument_paths=tuple(spec.sensitive_argument_paths),
        )
        return CapabilityDraft(
            capability_id=f"tool://builtin/{spec.id}",
            kind="tool",
            draft_revision=1,
            namespace=f"builtin.{spec.id}",
            resolved_version=config.build_revision,
            source_uri=f"{config.source_prefix}{config.build_revision}/{spec.id}",
            trust_level="builtin",
            content=CapabilityContent(
                display_name=display_name,
                description=description,
                keywords=tuple(dict.fromkeys((spec.id, *spec.effects))),
                definition_schema="tool_definition.v2",
                definition=definition.model_dump(mode="json"),
            ),
            updated_by_principal_id=config.publisher_principal_id,
        )

    def _overrides(self) -> dict[str, dict[str, object]]:
        path = self._config.overrides_path
        if not path.exists():
            return {}
        document = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict) or document.get("version") != "builtin_tool_overrides.v1":
            raise ValueError("builtin tool overrides must use builtin_tool_overrides.v1")
        overrides = document.get("tools")
        if not isinstance(overrides, dict) or any(not isinstance(value, dict) for value in overrides.values()):
            raise ValueError("builtin tool overrides tools must be an object")
        return {str(key): dict(value) for key, value in overrides.items()}

    @staticmethod
    def _runtime_resources(spec: ToolSpec) -> tuple[str, ...]:
        names: list[str] = []
        for local_name, resource_name in spec.resources.items():
            if resource_name == TOOL_OUTPUT_STORE_RESOURCE:
                continue
            if local_name != resource_name:
                raise ValueError(
                    f"builtin runtime resource aliases must be identical: {spec.id}:{local_name}"
                )
            if resource_name not in names:
                names.append(resource_name)
        return tuple(names)
