from __future__ import annotations

import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Callable

from pydantic import ConfigDict, Field, ValidationError
from ruamel.yaml import YAML

from agent_factory.core.types import JsonDumpMixin
from agent_factory.factory_context import FactoryContextEnvelope, apply_context_envelope
from agent_factory.factory.tool_generation import (
    GeneratedToolCodeDraft,
    ToolContract,
    ToolContractBatch,
    build_tool_contracts_request,
    build_tool_repair_request,
    build_tool_generation_request,
    derive_tool_contract,
    fallback_tool_code,
    validate_tool_logic_source,
    validate_tool_source,
)
from agent_factory.model import LLMRequest, LLMResponse, LLMStreamEvent, ModelService
from agent_factory.specs import AgentPackagePrimitives, ResourceContractsSpec, ToolImplementationPlan


class PackageArtifactReport(JsonDumpMixin):
    model_config = ConfigDict(extra="forbid")

    artifact_paths: list[Path] = Field(default_factory=list)
    tool_count: int = 0
    tool_test_count: int = 0
    mcp_binding_count: int = 0
    harness_scenario_count: int = 0
    issues: list[str] = Field(default_factory=list)


class PackageArtifactGenerator:
    """Generate draft implementation artifacts for a primitives package."""

    def __init__(self, *, model_service: ModelService | None = None) -> None:
        self.model_service = model_service
        self._yaml = YAML()
        self._yaml.default_flow_style = False

    def generate_tool_scripts(
        self,
        package_path: Path,
        primitives: AgentPackagePrimitives,
        *,
        requirement: str | None = None,
        requirement_analysis: dict[str, Any] | None = None,
        resource_contracts: ResourceContractsSpec | None = None,
        context_envelope: FactoryContextEnvelope | None = None,
        on_stream_event: Callable[[LLMStreamEvent], None] | None = None,
        on_tool_progress: Callable[[dict[str, Any]], None] | None = None,
    ) -> PackageArtifactReport:
        report = PackageArtifactReport()
        draft_dir = package_path / "generated" / "draft_tools"
        draft_dir.mkdir(parents=True, exist_ok=True)

        tool_drafts = _tool_drafts(primitives)
        total_tools = len(tool_drafts)
        contracts = self._generate_tool_contracts(
            primitives,
            tool_drafts,
            requirement=requirement,
            requirement_analysis=requirement_analysis,
            resource_contracts=resource_contracts,
            context_envelope=context_envelope,
            on_stream_event=on_stream_event,
        )
        _emit_contract_progress(on_tool_progress, contracts, total=total_tools)
        worker_count = self._tool_generation_worker_count(total_tools)
        indexed_drafts = list(enumerate(tool_drafts, start=1))
        if worker_count <= 1:
            generated = [
                (
                    index,
                    draft,
                    self._generate_one_tool_code(
                        primitives,
                        draft,
                        contracts.get(str(draft["tool_id"])),
                        requirement=requirement,
                        requirement_analysis=requirement_analysis,
                        resource_contracts=resource_contracts,
                        context_envelope=context_envelope,
                        on_stream_event=on_stream_event,
                        on_tool_progress=on_tool_progress,
                        total_tools=total_tools,
                        index=index,
                    ),
                )
                for index, draft in indexed_drafts
            ]
        else:
            generated = []
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                future_map = {}
                for index, draft in indexed_drafts:
                    _emit_tool_progress(
                        on_tool_progress,
                        draft,
                        index=index,
                        total=total_tools,
                        phase="model_generation_started",
                    )
                    future = executor.submit(
                        self._generate_tool_code,
                        primitives,
                        draft,
                        contract=contracts.get(str(draft["tool_id"])),
                        requirement=requirement,
                        requirement_analysis=requirement_analysis,
                        resource_contracts=resource_contracts,
                        context_envelope=context_envelope,
                        on_stream_event=None,
                    )
                    future_map[future] = (index, draft)
                for future in as_completed(future_map):
                    index, draft = future_map[future]
                    code_draft = future.result()
                    _emit_tool_progress(
                        on_tool_progress,
                        draft,
                        index=index,
                        total=total_tools,
                        phase=code_draft.generation_status,
                        fallback_used=code_draft.fallback_used,
                        error_count=len(code_draft.generation_errors),
                    )
                    generated.append((index, draft, code_draft))
            generated.sort(key=lambda item: item[0])

        for index, draft, code_draft in generated:
            stem = _safe_file_stem(draft["tool_id"])
            script_path = draft_dir / f"{stem}.py"
            metadata_path = draft_dir / f"{stem}.tool.yaml"
            if code_draft.logic_source:
                logic_path = draft_dir / f"{stem}_logic.py"
                logic_path.write_text(code_draft.logic_source, encoding="utf-8")
                code_draft.logic_path = str(logic_path.relative_to(logic_path.parents[2]))
                report.artifact_paths.append(logic_path)
            script_path.write_text(code_draft.python_source, encoding="utf-8")
            self._dump_yaml(metadata_path, _tool_metadata(primitives, draft, script_path, code_draft))
            codegen_path = draft_dir / f"{stem}.codegen.json"
            codegen_path.write_text(code_draft.model_dump_json(indent=2), encoding="utf-8")
            _emit_tool_progress(
                on_tool_progress,
                draft,
                index=index,
                total=total_tools,
                phase="written",
                fallback_used=code_draft.fallback_used,
                error_count=len(code_draft.generation_errors),
                artifact_path=str(script_path),
            )
            report.artifact_paths.extend([script_path, metadata_path, codegen_path])
            if code_draft.generation_status == "generation_failed":
                report.issues.append(
                    _tool_generation_issue(draft["tool_id"], code_draft.generation_errors)
                )

        report.tool_count = len(tool_drafts)
        return report

    def generate_tool_tests(
        self,
        package_path: Path,
        primitives: AgentPackagePrimitives,
    ) -> PackageArtifactReport:
        return self._write_tool_tests(package_path, primitives)

    def repair_generated_tool_tests(
        self,
        package_path: Path,
        primitives: AgentPackagePrimitives,
        *,
        failed_report: Any | None = None,
    ) -> PackageArtifactReport:
        report = self._write_tool_tests(package_path, primitives)
        marker_path = _reports_dir(package_path) / "tool_test_repair.json"
        marker_path.write_text(
            json.dumps(
                {
                    "status": "repaired",
                    "strategy": "rewrite_relaxed_contract_tests",
                    "previous_issues": [
                        issue.model_dump(mode="json")
                        for issue in getattr(failed_report, "issues", [])
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        report.artifact_paths.append(marker_path)
        return report

    def _write_tool_tests(
        self,
        package_path: Path,
        primitives: AgentPackagePrimitives,
    ) -> PackageArtifactReport:
        report = PackageArtifactReport()
        test_dir = package_path / "generated" / "tool_tests"
        test_dir.mkdir(parents=True, exist_ok=True)

        tool_drafts = _tool_drafts(primitives)
        if not tool_drafts:
            readme_path = test_dir / "README.md"
            readme_path.write_text(
                "No generated tool tests are required because toolsets.yaml exposes no tools.\n",
                encoding="utf-8",
            )
            report.artifact_paths.append(readme_path)
            return report

        for draft in tool_drafts:
            stem = _safe_file_stem(draft["tool_id"])
            test_path = test_dir / f"test_{stem}.py"
            code_draft = _load_codegen(draft_dir=package_path / "generated" / "draft_tools", stem=stem)
            test_path.write_text(_tool_test_source(draft, code_draft), encoding="utf-8")
            report.artifact_paths.append(test_path)

        report.tool_test_count = len(tool_drafts)
        return report

    def generate_mcp_bindings(
        self,
        package_path: Path,
        primitives: AgentPackagePrimitives,
    ) -> PackageArtifactReport:
        report = PackageArtifactReport()
        mcp_sources = [source for source in primitives.knowledge.sources if source.type == "mcp"]
        bindings = []
        servers = []
        version = primitives.instructions.metadata.version

        for source in mcp_sources:
            server_id = _safe_identifier(source.id)
            binding_id = f"{server_id}_default"
            servers.append(
                {
                    "id": server_id,
                    "source_ref": source.ref,
                    "transport": "stdio",
                    "enabled": False,
                    "health_check": {"enabled": True},
                }
            )
            bindings.append(
                {
                    "id": binding_id,
                    "source_id": source.id,
                    "capability_ref": f"mcp.{server_id}.default@{version}",
                    "risk_level": "medium",
                    "visible_to_model": source.visible_to_model,
                    "proposal_only": True,
                    "input_mapping": {"strategy": "pass_through"},
                    "output_mapping": {"strategy": "sanitized_json"},
                }
            )

        path = package_path / "mcp.yaml"
        self._dump_yaml(
            path,
            {
                "schema_version": "0.1",
                "kind": "MCPBindingSpec",
                "metadata": _metadata_dict(primitives, suffix="mcp"),
                "servers": servers,
                "bindings": bindings,
            },
        )
        report.artifact_paths.append(path)
        report.mcp_binding_count = len(bindings)
        return report

    def generate_harness_scenarios(
        self,
        package_path: Path,
        primitives: AgentPackagePrimitives,
    ) -> PackageArtifactReport:
        report = PackageArtifactReport()
        tool_ids = [draft["tool_id"] for draft in _tool_drafts(primitives)]
        mcp_sources = [source for source in primitives.knowledge.sources if source.type == "mcp"]
        scenarios = [_basic_harness_scenario(primitives), _memory_harness_scenario()]

        for draft in _tool_drafts(primitives):
            scenarios.append(_tool_harness_scenario(draft))

        path = package_path / "harness.yaml"
        self._dump_yaml(
            path,
            {
                "schema_version": "0.1",
                "kind": "HarnessSpec",
                "metadata": _metadata_dict(primitives, suffix="harness"),
                "observation": {
                    "trace": True,
                    "runtime_path": True,
                    "route_decisions": True,
                    "context_bundle": True,
                    "tool_calls": True,
                    "mcp_calls": True,
                    "memory_ops": True,
                    "final_response": True,
                },
                "fixtures": {
                    "tools": {
                        tool_id: {
                            "mode": "mock",
                            "output": {
                                "status": "mocked",
                                "tool_id": tool_id,
                                "requires_approval": True,
                            },
                        }
                        for tool_id in tool_ids
                    },
                    "mcp": {
                        _safe_identifier(source.id): {
                            "mode": "mock",
                            "output": {"documents": []},
                        }
                        for source in mcp_sources
                    },
                    "context": {},
                    "memory": {},
                },
                "scenarios": scenarios,
            },
        )
        report.artifact_paths.append(path)
        report.harness_scenario_count = len(scenarios)
        return report

    def generate_package_specs(
        self,
        package_path: Path,
        primitives: AgentPackagePrimitives,
        *,
        resource_contracts: ResourceContractsSpec | None = None,
    ) -> PackageArtifactReport:
        report = PackageArtifactReport()
        metadata = primitives.instructions.metadata
        agent_id = _safe_identifier(metadata.name)
        tool_ids = [draft["tool_id"] for draft in _tool_drafts(primitives)]
        files = {
            "package.yaml": {
                "schema_version": "0.1",
                "kind": "PackageManifest",
                "metadata": _metadata_dict(primitives, suffix="package"),
                "agent_id": agent_id,
                "agent_name": metadata.name,
                "version": metadata.version,
                "status": "draft",
                "description": metadata.description,
                "entrypoint": "agent_factory.agent.worker",
                "package_format": "agentpackage.v1",
                "tags": ["factory-generated", "mvp"],
            },
            "runtime.yaml": {
                "schema_version": "0.1",
                "kind": "RuntimeSpec",
                "metadata": _metadata_dict(primitives, suffix="runtime"),
                "runtime_type": "langgraph_native",
                "compile_mode": "task_graph",
                "checkpointer": {"type": "filesystem"},
                "interrupt": {"mode": "langgraph_native"},
                "task_graph_file": "task_graph.yaml",
                "max_turns": primitives.conversation.history_window,
                "timeout_seconds": 60,
            },
            "task_graph.yaml": {
                "schema_version": "0.1",
                "kind": "TaskGraphSpec",
                "metadata": _metadata_dict(primitives, suffix="task-graph"),
                "graph_type": "langgraph_state_graph",
                "state_schema": "agent_runtime_state.v1",
                "nodes": {
                    "understand": {"type": "model", "purpose": "understand_task"},
                    "route": {
                        "type": "router",
                        "routes": [
                            {"when": "needs_capability", "to": "execute_capability"},
                            {"when": "needs_user_input", "to": "ask_user"},
                            {"when": "ready", "to": "compose_final"},
                        ],
                    },
                    "execute_capability": {"type": "capability", "capability_ref": "auto"},
                    "ask_user": {"type": "interrupt", "interrupt_type": "user_input_required"},
                    "compose_final": {"type": "model", "purpose": "final_answer"},
                },
                "edges": [
                    {"from": "START", "to": "understand"},
                    {"from": "understand", "to": "route"},
                    {"from": "execute_capability", "to": "route"},
                    {"from": "ask_user", "to": "route"},
                    {"from": "compose_final", "to": "END"},
                ],
            },
            "tools.yaml": {
                "schema_version": "0.1",
                "kind": "ToolsSpec",
                "metadata": _metadata_dict(primitives, suffix="tools"),
                "generated_tools": tool_ids,
                "builtin_capabilities": _builtin_capabilities(resource_contracts),
                "default_policy": "proposal_only",
                "allow_draft_execution": False,
                "require_approval_for_generated_code": True,
            },
            "context.yaml": {
                "schema_version": "0.1",
                "kind": "ContextSpec",
                "metadata": _metadata_dict(primitives, suffix="context"),
                "sources": _context_sources(primitives),
                "max_visible_items": 8,
                "redact_fields": [
                    "api_key",
                    "secret",
                    "authorization",
                    "auth_header",
                    "tool_auth_token",
                ],
            },
            "memory.yaml": {
                "schema_version": "0.1",
                "kind": "MemorySpec",
                "metadata": _metadata_dict(primitives, suffix="memory"),
                "backend": "filesystem",
                "session_memory_file": "memory/session_memory.jsonl",
                "summary_memory_file": "memory/summary_memory.jsonl",
                "enabled": True,
                "namespace_template": f"agent:{agent_id}:session:{{session_id}}",
                "redact_before_storage": True,
            },
        }
        for filename, data in files.items():
            path = package_path / filename
            self._dump_yaml(path, data)
            report.artifact_paths.append(path)
        return report

    def _dump_yaml(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            self._yaml.dump(data, file)

    def _generate_tool_contracts(
        self,
        primitives: AgentPackagePrimitives,
        tool_drafts: list[dict[str, Any]],
        *,
        requirement: str | None,
        requirement_analysis: dict[str, Any] | None,
        resource_contracts: ResourceContractsSpec | None,
        context_envelope: FactoryContextEnvelope | None,
        on_stream_event: Callable[[LLMStreamEvent], None] | None,
    ) -> dict[str, ToolContract]:
        derived = {
            str(draft["tool_id"]): derive_tool_contract(
                primitives,
                draft,
                requirement=requirement,
                requirement_analysis=requirement_analysis,
                resource_contracts=resource_contracts,
            )
            for draft in tool_drafts
        }
        if (
            self.model_service is None
            or not tool_drafts
            or _provider_name(self.model_service) == "fake"
        ):
            return derived
        try:
            request = apply_context_envelope(
                build_tool_contracts_request(
                    primitives,
                    tool_drafts,
                    requirement=requirement,
                    requirement_analysis=requirement_analysis,
                    resource_contracts=resource_contracts,
                ),
                context_envelope,
            )
            method = (
                self.model_service.stream_structured
                if on_stream_event
                else self.model_service.generate_structured
            )
            result = asyncio.run(
                method(
                    request,
                    schema=ToolContractBatch.model_json_schema(),
                    schema_name="ToolContractBatch",
                    **({"on_event": on_stream_event} if on_stream_event else {}),
                )
            )
            if result.error:
                return derived
            data = result.data
            if isinstance(data, list):
                data = {"tools": data}
            batch = ToolContractBatch.model_validate(data)
            for contract in batch.tools:
                if contract.tool_id in derived:
                    derived[contract.tool_id] = contract
        except Exception:
            return derived
        return derived

    def _generate_one_tool_code(
        self,
        primitives: AgentPackagePrimitives,
        draft: dict[str, Any],
        contract: ToolContract | None,
        *,
        requirement: str | None,
        requirement_analysis: dict[str, Any] | None,
        resource_contracts: ResourceContractsSpec | None,
        context_envelope: FactoryContextEnvelope | None,
        on_stream_event: Callable[[LLMStreamEvent], None] | None,
        on_tool_progress: Callable[[dict[str, Any]], None] | None,
        total_tools: int,
        index: int,
    ) -> GeneratedToolCodeDraft:
        _emit_tool_progress(
            on_tool_progress,
            draft,
            index=index,
            total=total_tools,
            phase="model_generation_started",
        )
        code_draft = self._generate_tool_code(
            primitives,
            draft,
            contract=contract,
            requirement=requirement,
            requirement_analysis=requirement_analysis,
            resource_contracts=resource_contracts,
            context_envelope=context_envelope,
            on_stream_event=on_stream_event,
        )
        _emit_tool_progress(
            on_tool_progress,
            draft,
            index=index,
            total=total_tools,
            phase=code_draft.generation_status,
            fallback_used=code_draft.fallback_used,
            error_count=len(code_draft.generation_errors),
        )
        return code_draft

    def _tool_generation_worker_count(self, total_tools: int) -> int:
        if total_tools <= 1 or self.model_service is None:
            return 1
        if _provider_name(self.model_service) == "fake":
            return 1
        return min(4, total_tools)

    def _generate_tool_code(
        self,
        primitives: AgentPackagePrimitives,
        draft: dict[str, Any],
        *,
        contract: ToolContract | None = None,
        requirement: str | None = None,
        requirement_analysis: dict[str, Any] | None = None,
        resource_contracts: ResourceContractsSpec | None = None,
        context_envelope: FactoryContextEnvelope | None = None,
        on_stream_event: Callable[[LLMStreamEvent], None] | None = None,
    ) -> GeneratedToolCodeDraft:
        if self.model_service is not None:
            generation_errors: list[str] = []
            previous_data: Any = None
            try:
                request = apply_context_envelope(
                    build_tool_generation_request(
                        primitives,
                        draft,
                        contract=contract,
                        requirement=requirement,
                        requirement_analysis=requirement_analysis,
                        resource_contracts=resource_contracts,
                    ),
                    context_envelope,
                )
                result = asyncio.run(
                    _generate_tool_text(
                        self.model_service,
                        request,
                        on_stream_event=on_stream_event,
                    )
                )
                previous_data = result.content
                if result.error:
                    generation_errors.append(
                        f"model_generation_error:{result.error.type}:{result.error.message}"
                    )
                else:
                    code, errors = _coerce_tool_code(
                        result.content,
                        draft,
                        primitives=primitives,
                        requirement=requirement,
                        contract=contract,
                        resource_contracts=resource_contracts,
                        generation_status="model_generated",
                        repair_attempts=0,
                        prior_errors=[],
                    )
                    if code is not None:
                        return code
                    generation_errors.extend(errors)
            except Exception as error:
                generation_errors.append(f"model_generation_exception:{type(error).__name__}:{error}")

            try:
                repair_request = apply_context_envelope(
                    build_tool_repair_request(
                        primitives,
                        draft,
                        contract=contract,
                        previous_data=previous_data,
                        validation_errors=generation_errors,
                        requirement=requirement,
                        requirement_analysis=requirement_analysis,
                        resource_contracts=resource_contracts,
                    ),
                    context_envelope,
                )
                repair_result = asyncio.run(
                    _generate_tool_text(
                        self.model_service,
                        repair_request,
                        on_stream_event=on_stream_event,
                    )
                )
                if repair_result.error:
                    generation_errors.append(
                        f"tool_repair_error:{repair_result.error.type}:{repair_result.error.message}"
                    )
                else:
                    code, errors = _coerce_tool_code(
                        repair_result.content,
                        draft,
                        primitives=primitives,
                        requirement=requirement,
                        contract=contract,
                        resource_contracts=resource_contracts,
                        generation_status="model_repaired",
                        repair_attempts=1,
                        prior_errors=generation_errors,
                    )
                    if code is not None:
                        return code
                    generation_errors.extend(f"repair:{error}" for error in errors)
            except Exception as error:
                generation_errors.append(f"tool_repair_exception:{type(error).__name__}:{error}")
        else:
            generation_errors = ["model_service_missing:tool code generation skipped"]
        return fallback_tool_code(
            draft,
            primitives=primitives,
            requirement=requirement,
            generation_errors=generation_errors,
            repair_attempts=1 if self.model_service is not None else 0,
        )


def merge_artifact_reports(*reports: PackageArtifactReport) -> PackageArtifactReport:
    merged = PackageArtifactReport()
    for report in reports:
        merged.artifact_paths.extend(report.artifact_paths)
        merged.tool_count += report.tool_count
        merged.tool_test_count += report.tool_test_count
        merged.mcp_binding_count += report.mcp_binding_count
        merged.harness_scenario_count += report.harness_scenario_count
        merged.issues.extend(report.issues)
    return merged


def _provider_name(model_service: ModelService) -> str:
    config = getattr(getattr(model_service, "router", None), "config", None)
    return str(getattr(config, "provider", "unknown"))


async def _generate_tool_text(
    model_service: ModelService,
    request: LLMRequest,
    *,
    on_stream_event: Callable[[LLMStreamEvent], None] | None,
) -> LLMResponse:
    if on_stream_event is None:
        return await model_service.generate(request)
    chunks: list[str] = []
    response = LLMResponse(provider="unknown")
    async for event in model_service.stream(request):
        on_stream_event(event)
        if event.type == "delta" and event.delta and event.metadata.get("delta_kind") != "reasoning":
            chunks.append(event.delta)
        elif event.type == "completed" and event.response:
            response = event.response
        elif event.type == "error" and event.error:
            return LLMResponse(provider=response.provider, error=event.error)
    content = "".join(chunks)
    if response.provider == "unknown":
        return LLMResponse(content=content, provider="unknown")
    return response.model_copy(update={"content": content or response.content})


def _emit_contract_progress(
    callback: Callable[[dict[str, Any]], None] | None,
    contracts: dict[str, ToolContract],
    *,
    total: int,
) -> None:
    if callback is None:
        return
    callback(
        {
            "tool_phase": "contracts_generated",
            "tool_total": total,
            "contract_count": len(contracts),
            "flow_summary": f"Generated {len(contracts)}/{total} code-free tool contracts.",
        }
    )


def _emit_tool_progress(
    callback: Callable[[dict[str, Any]], None] | None,
    draft: dict[str, Any],
    *,
    index: int,
    total: int,
    phase: str,
    fallback_used: bool | None = None,
    error_count: int | None = None,
    artifact_path: str | None = None,
) -> None:
    if callback is None:
        return
    tool_id = str(draft["tool_id"])
    summary = f"Tool {index}/{total}: {tool_id} - {_human_tool_phase(phase)}."
    if fallback_used:
        summary += " Fallback implementation was used."
    if error_count:
        summary += f" issues={error_count}."
    callback(
        {
            "tool_id": tool_id,
            "tool_index": index,
            "tool_total": total,
            "tool_phase": phase,
            "fallback_used": fallback_used,
            "error_count": error_count,
            "artifact_path": artifact_path,
            "flow_summary": summary,
        }
    )


def _human_tool_phase(phase: str) -> str:
    return {
        "model_generation_started": "calling model for code",
        "model_generated": "model code accepted",
        "model_repaired": "model code repaired",
        "generation_failed": "model code unavailable",
        "written": "files written",
    }.get(phase, phase.replace("_", " "))


def _tool_drafts(primitives: AgentPackagePrimitives) -> list[dict[str, Any]]:
    drafts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for toolset in primitives.toolsets.toolsets:
        for exposure, tool_ids in (
            ("exposed", toolset.exposed_tools),
            ("hidden", toolset.hidden_tools),
        ):
            for tool_id in tool_ids:
                if tool_id in seen:
                    continue
                seen.add(tool_id)
                risk_level = "medium"
                drafts.append(
                    {
                        "tool_id": tool_id,
                        "toolset_id": toolset.id,
                        "description": toolset.description,
                        "exposure": exposure,
                        "proposal_only": toolset.proposal_only,
                        "selection_strategy": toolset.selection_strategy,
                        "risk_level": risk_level,
                        "approval_required": True,
                    }
                )
    return drafts


def _tool_test_source(draft: dict[str, Any], code_draft: GeneratedToolCodeDraft) -> str:
    stem = _safe_file_stem(draft["tool_id"])
    class_name = "".join(part.capitalize() for part in stem.split("_")) or "GeneratedTool"
    test_cases = _merge_tool_test_cases(
        code_draft.test_cases,
        [],
    )
    rendered_cases = [
        {
            "name": case.name,
            "input_data": case.input_data,
            "expected_contains": case.expected_contains,
        }
        for case in test_cases
    ]
    return f'''from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest


MODULE_PATH = Path(__file__).resolve().parents[1] / "draft_tools" / "{stem}.py"
TEST_CASES = {rendered_cases!r}


def load_tool_module():
    module_dir = str(MODULE_PATH.parent)
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    spec = importlib.util.spec_from_file_location("generated_tool_{stem}", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_tool_test_context() -> dict:
    raw = os.environ.get("AGENTFACTORY_TOOL_TEST_CONTEXT_JSON") or "{{}}"
    data = json.loads(raw)
    return data if isinstance(data, dict) else {{}}


class {class_name}DraftTests(unittest.TestCase):
    def test_run_returns_executable_local_contract(self) -> None:
        module = load_tool_module()
        context = load_tool_test_context()
        cases = TEST_CASES or [{{"name": "default_contract", "input_data": {{}}}}]
        for case in cases:
            with self.subTest(case=case["name"]):
                result = module.run(case["input_data"], context)
                self.assert_executable_result(result)

    def assert_executable_result(self, result: object) -> None:
        self.assertIsInstance(result, dict)
        self.assertTrue(result, "tool result must not be empty")
        status = str(result.get("status", "")).lower()
        self.assertNotIn(status, {{"not_implemented", "error", "generation_failed"}})
        serialized = json.dumps(result, ensure_ascii=False, sort_keys=True).lower()
        if status == "needs_configuration":
            self.assertTrue(
                any(
                    marker in serialized
                    for marker in [
                        "external_config",
                        "configuration",
                        "missing",
                        "配置",
                        "缺少",
                    ]
                ),
                "needs_configuration results must explain missing configuration or point to external_config.yaml",
            )
        forbidden_markers = [
            "not_implemented",
        ]
        for marker in forbidden_markers:
            self.assertNotIn(marker, serialized)

    def test_schema_contracts_are_objects(self) -> None:
        module = load_tool_module()

        self.assertEqual(module.input_schema()["type"], "object")
        self.assertEqual(module.output_schema()["type"], "object")


if __name__ == "__main__":
    unittest.main()
'''


def _tool_metadata(
    primitives: AgentPackagePrimitives,
    draft: dict[str, Any],
    script_path: Path,
    code_draft: GeneratedToolCodeDraft,
) -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "kind": "GeneratedToolDraft",
        "metadata": _metadata_dict(primitives, suffix=_safe_file_stem(draft["tool_id"])),
        "tool_id": draft["tool_id"],
        "toolset_id": draft["toolset_id"],
        "source": "factory_generated",
        "status": "draft",
        "risk_level": draft["risk_level"],
        "exposure": draft["exposure"],
        "proposal_only": draft["proposal_only"],
        "selection_strategy": draft["selection_strategy"],
        "implementation": {
            "language": "python",
            "entrypoint": "run",
            "path": str(script_path.relative_to(script_path.parents[2])),
            **({"logic_path": code_draft.logic_path} if code_draft.logic_path else {}),
        },
        "input_schema": code_draft.input_schema,
        "output_schema": code_draft.output_schema,
        "approval": {
            "required": draft["approval_required"],
            "reason": "Factory-generated tool code must be reviewed before registration.",
        },
        **(
            {"implementation_plan": code_draft.implementation_plan.model_dump(mode="json")}
            if code_draft.implementation_plan
            else {}
        ),
        "generation": {
            "status": code_draft.generation_status,
            "fallback_used": code_draft.fallback_used,
            "repair_attempts": code_draft.repair_attempts,
            "errors": code_draft.generation_errors,
        },
    }


def _load_codegen(draft_dir: Path, stem: str) -> GeneratedToolCodeDraft:
    path = draft_dir / f"{stem}.codegen.json"
    if not path.exists():
        return fallback_tool_code({"tool_id": stem, "risk_level": "medium", "approval_required": True})
    data = json.loads(path.read_text(encoding="utf-8"))
    return GeneratedToolCodeDraft.model_validate(data)


def _reports_dir(package_path: Path) -> Path:
    path = package_path / "generated" / "reports"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _coerce_tool_code(
    data: Any,
    draft: dict[str, Any],
    *,
    primitives: AgentPackagePrimitives,
    requirement: str | None,
    contract: ToolContract | None,
    resource_contracts: ResourceContractsSpec | None,
    generation_status: str,
    repair_attempts: int,
    prior_errors: list[str],
) -> tuple[GeneratedToolCodeDraft | None, list[str]]:
    errors: list[str] = []
    if isinstance(data, str):
        legacy_data = _json_object_from_text(data)
        if legacy_data is not None:
            data = legacy_data
        else:
            logic_source = _extract_python_source(data)
            if not logic_source.strip():
                return None, ["logic_source_empty"]
            logic_errors = validate_tool_logic_source(logic_source)
            if logic_errors:
                return None, logic_errors
            code = _code_draft_from_logic(
                logic_source,
                draft,
                contract=contract,
                resource_contracts=resource_contracts,
                generation_status=generation_status,
                repair_attempts=repair_attempts,
                prior_errors=prior_errors,
            )
            return code, []
    if not isinstance(data, dict):
        return None, [f"structured_output_not_object:{type(data).__name__}"]
    try:
        code = GeneratedToolCodeDraft.model_validate(data)
    except ValidationError as error:
        return None, [f"schema_validation_error:{_compact_error(str(error))}"]
    if code.tool_id != draft["tool_id"]:
        errors.append(f"tool_id_mismatch:expected={draft['tool_id']}:actual={code.tool_id}")
    source_issues = validate_tool_source(code.python_source)
    errors.extend(source_issues)
    if errors:
        return None, errors
    code.generation_status = generation_status  # type: ignore[assignment]
    code.fallback_used = False
    code.repair_attempts = repair_attempts
    code.generation_errors = list(prior_errors)
    code.test_cases = _merge_tool_test_cases(code.test_cases, [])
    return code, []


def _code_draft_from_logic(
    logic_source: str,
    draft: dict[str, Any],
    *,
    contract: ToolContract | None,
    resource_contracts: ResourceContractsSpec | None,
    generation_status: str,
    repair_attempts: int,
    prior_errors: list[str],
) -> GeneratedToolCodeDraft:
    tool_id = str(draft.get("tool_id") or "generated_tool")
    stem = _safe_file_stem(tool_id)
    input_schema = contract.input_schema if contract is not None else {"type": "object"}
    output_schema = contract.output_schema if contract is not None else {"type": "object"}
    implementation_plan = _implementation_plan_from_contract(
        tool_id,
        contract=contract,
        resource_contracts=resource_contracts,
    )
    return GeneratedToolCodeDraft(
        tool_id=tool_id,
        python_source=_tool_wrapper_source(
            tool_id,
            logic_module=f"{stem}_logic",
            input_schema=input_schema,
            output_schema=output_schema,
        ),
        logic_source=logic_source,
        logic_path=f"generated/draft_tools/{stem}_logic.py",
        input_schema=input_schema,
        output_schema=output_schema,
        test_cases=contract.test_requirements if contract is not None else [],
        implementation_plan=implementation_plan,
        risk_notes=["model-generated logic artifact"],
        generation_status=generation_status,
        fallback_used=False,
        repair_attempts=repair_attempts,
        generation_errors=list(prior_errors),
    )


def _implementation_plan_from_contract(
    tool_id: str,
    *,
    contract: ToolContract | None,
    resource_contracts: ResourceContractsSpec | None,
) -> ToolImplementationPlan:
    resource_refs = list(contract.resource_refs) if contract is not None else []
    condition_refs: list[str] = []
    probe_evidence: dict[str, object] = {}
    web_research_refs: list[str] = []
    test_fixture_refs: list[str] = []
    if resource_contracts is not None:
        resources_by_id = {resource.id: resource for resource in resource_contracts.resources}
        resource_refs = [resource_id for resource_id in resource_refs if resource_id in resources_by_id]
        for resource_id in resource_refs:
            details = resources_by_id[resource_id].details
            condition = details.get("condition") if isinstance(details, dict) else None
            if isinstance(condition, dict):
                condition_id = str(condition.get("condition_id") or "")
                if condition_id and condition_id not in condition_refs:
                    condition_refs.append(condition_id)
                if condition.get("type") == "web_research":
                    web_research_refs.append(condition_id)
                if condition.get("type") == "mock_fixture":
                    test_fixture_refs.append(condition_id)
            probe_target = details.get("probe_target") if isinstance(details, dict) else None
            if isinstance(probe_target, dict):
                probe_evidence[resource_id] = probe_target
    return ToolImplementationPlan(
        tool_id=tool_id,
        resource_refs=resource_refs,
        preconditions=[
            "resource_contract_available" if resource_refs else "no_external_resource_required",
            "sandbox_context_available",
        ],
        condition_refs=condition_refs,
        probe_evidence=probe_evidence,
        web_research_refs=web_research_refs,
        test_fixture_refs=test_fixture_refs,
        allowed_operations=[
            "use_explicit_runtime_resources",
            "return_structured_dict_result",
            "use_parameterized_sql_for_sqlite" if resource_refs else "local_deterministic_logic",
        ],
        forbidden_operations=(
            list(contract.forbidden_behaviors)
            if contract is not None
            else [
                "do_not_read_env_or_secrets",
                "do_not_execute_shell",
                "do_not_access_network",
            ]
        ),
        failure_cases=[
            "missing_required_input",
            "resource_unavailable" if resource_refs else "invalid_input",
            "operation_rejected_by_policy",
        ],
        sandbox_context_required=bool(resource_refs),
    )


def _builtin_capabilities(resource_contracts: ResourceContractsSpec | None) -> list[dict[str, object]]:
    # MVP rule: Factory extracts user-provided external documentation during
    # production, but generated agents do not inherit open web/search tools.
    return []


def _tool_wrapper_source(
    tool_id: str,
    *,
    logic_module: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
) -> str:
    return f'''"""Factory-generated tool wrapper.

This wrapper is deterministic Factory code. The model-generated business logic
lives in {logic_module}.py and must define execute(input_data, resources).
"""

from __future__ import annotations

from typing import Any

from {logic_module} import execute


TOOL_ID = {tool_id!r}
INPUT_SCHEMA = {input_schema!r}
OUTPUT_SCHEMA = {output_schema!r}


def input_schema() -> dict[str, Any]:
    return INPUT_SCHEMA


def output_schema() -> dict[str, Any]:
    return OUTPUT_SCHEMA


def run(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(input_data, dict):
        raise TypeError("input_data must be a dict")
    resources = _resources_for_logic(context or {{}})
    try:
        result = execute(input_data, resources)
    except Exception as error:
        return {{
            "status": "failed",
            "tool_id": TOOL_ID,
            "error": str(error),
        }}
    if not isinstance(result, dict):
        return {{
            "status": "failed",
            "tool_id": TOOL_ID,
            "error": "logic result must be a dict",
        }}
    result.setdefault("status", "completed")
    result.setdefault("tool_id", TOOL_ID)
    return result


def _resources_for_logic(context: dict[str, Any]) -> dict[str, Any]:
    return {{
        "resources": context.get("resources", {{}}),
        "sqlite_databases": context.get("sqlite_databases", {{}}),
        "filesystem_root": context.get("filesystem_root"),
        "runtime": context.get("runtime", {{}}),
        "external_config": _external_config_for_logic(context.get("external_config", {{}})),
        "external_http_client": context.get("external_http_client"),
    }}


def _external_config_for_logic(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {{}}
    values = raw.get("values") if isinstance(raw.get("values"), dict) else {{}}
    resolved = raw.get("resolved_values") if isinstance(raw.get("resolved_values"), dict) else {{}}
    merged: dict[str, Any] = {{}}
    merged.update(values)
    merged.update(resolved)
    for key in (
        "path",
        "exists",
        "status",
        "required_keys",
        "secret_keys",
        "source_urls",
        "missing_required_keys",
    ):
        if key in raw:
            merged[key] = raw[key]
    merged["values"] = values
    merged["resolved_values"] = resolved
    merged["data"] = raw.get("data", {{}})
    return merged
'''


def _json_object_from_text(value: str) -> dict[str, Any] | None:
    text = value.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_python_source(value: str) -> str:
    fenced = re.search(r"```(?:python|py)?\s*(.*?)```", value, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return value.strip()


def _tool_generation_issue(tool_id: str, errors: list[str]) -> str:
    detail = "; ".join(errors[:5]) if errors else "no detailed error was captured"
    return (
        f"{tool_id}: model tool generation failed. "
        f"The package is not production-ready. Details: {detail}"
    )


def _compact_error(value: str, *, limit: int = 500) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 3] + "..."


def _merge_tool_test_cases(
    base_cases: list[Any],
    required_cases: list[Any],
) -> list[Any]:
    merged: list[Any] = list(base_cases)
    seen = {
        (
            getattr(case, "name", None),
            json.dumps(getattr(case, "expected_contains", {}), sort_keys=True, ensure_ascii=False),
        )
        for case in merged
    }
    for case in required_cases:
        key = (
            getattr(case, "name", None),
            json.dumps(getattr(case, "expected_contains", {}), sort_keys=True, ensure_ascii=False),
        )
        if key not in seen:
            merged.append(case)
            seen.add(key)
    return merged


def _basic_harness_scenario(primitives: AgentPackagePrimitives) -> dict[str, Any]:
    return {
        "id": "basic_response_001",
        "name": "Basic in-scope response",
        "turns": [{"user": "请根据你的职责提供帮助"}],
        "expected": {
            "intent": "in_scope",
            "must_confirm": False,
            "forbidden_direct_execution": True,
            "response_constraints": {
                "must_not_include": ["已直接执行", "已自动执行高风险操作"],
            },
        },
        "observe": {
            "trace": True,
            "runtime_path": True,
            "context_bundle": True,
            "tool_calls": True,
            "route_decisions": True,
        },
    }


def _memory_harness_scenario() -> dict[str, Any]:
    return {
        "id": "memory_recall_001",
        "name": "Conversation history recall",
        "turns": [
            {"user": "请记住我的代号是 AF-TEST-USER"},
            {"user": "我的代号是什么？"},
        ],
        "expected": {
            "intent": "in_scope",
            "memory_read_allowed": True,
            "must_confirm": False,
            "forbidden_direct_execution": True,
            "response_constraints": {
                "must_include": ["AF-TEST-USER"],
            },
        },
        "observe": {
            "trace": True,
            "runtime_path": True,
            "context_bundle": True,
            "memory_ops": True,
            "final_response": True,
        },
    }


def _tool_harness_scenario(draft: dict[str, Any]) -> dict[str, Any]:
    tool_id = draft["tool_id"]
    scenario_id = f"{_safe_file_stem(tool_id)}_proposal_001"
    return {
        "id": scenario_id,
        "name": f"Tool proposal boundary for {tool_id}",
        "turns": [{"user": f"请处理和 {tool_id} 相关的请求"}],
        "expected": {
            "selected_tool": tool_id,
            "forbidden_tools": [],
            "must_confirm": draft["approval_required"],
            "forbidden_direct_execution": draft["approval_required"],
            "response_constraints": {
                "must_include": [],
            },
        },
        "observe": {
            "trace": True,
            "tool_calls": True,
            "interrupts": True,
            "route_decisions": True,
        },
    }


def _metadata_dict(primitives: AgentPackagePrimitives, *, suffix: str) -> dict[str, Any]:
    metadata = primitives.instructions.metadata
    return {
        "name": f"{metadata.name}-{suffix}",
        "version": metadata.version,
        "description": metadata.description,
        "owner": metadata.owner,
    }


def _context_sources(primitives: AgentPackagePrimitives) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = [
        {
            "id": "agent_instructions",
            "type": "static",
            "content": f"{primitives.instructions.persona}\n{primitives.instructions.goal}",
            "visible_to_model": True,
            "visible_to_tools": False,
            "hidden_from_model": [],
        }
    ]
    for source in primitives.knowledge.sources:
        sources.append(
            {
                "id": source.id,
                "type": _context_source_type(source.type, source.ref),
                "content": None,
                "ref": source.ref,
                "visible_to_model": source.visible_to_model,
                "visible_to_tools": source.visible_to_tools,
                "hidden_from_model": [
                    "api_key",
                    "authorization",
                    "tool_auth_token",
                ],
            }
        )
    return sources


def _context_source_type(source_type: str, ref: str | None) -> str:
    if source_type == "mcp":
        return "mcp"
    if source_type == "directory":
        return "directory"
    if ref and ref.lower().endswith((".sqlite", ".sqlite3", ".db")):
        return "sqlite"
    if source_type in {"file", "url", "vector_store"}:
        return source_type
    return "static"


def _safe_file_stem(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    return normalized or "generated_tool"


def _safe_identifier(value: str) -> str:
    normalized = _safe_file_stem(value)
    if normalized[0].isdigit():
        return f"id_{normalized}"
    return normalized
