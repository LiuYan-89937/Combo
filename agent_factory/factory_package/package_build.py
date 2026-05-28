from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
import json
import py_compile
import re
import shutil
from pathlib import Path
from tempfile import mkdtemp
from typing import Any

from jsonschema import Draft202012Validator

from agent_factory.assembly.schema import AgentAssemblySpec
from agent_factory.factory_package.schemas import (
    CapabilityContractOutput,
    PackageBuildMaterializedFile,
    PackageBuildModelPlan,
    PackageBuildPlan,
    PackageBuildReport,
    PackageBuildStaticCheck,
    PackageToolBuildPlan,
    ProductBriefOutput,
    RuntimeDesignOutput,
    SchedulerPreparationOutput,
)
from agent_factory.runtime_contracts.builtins import default_runtime_contract_registry
from agent_factory.runtime_contracts.loader import AgentPackageLoader
from agent_factory.runtime_contracts.schema import AgentPackageManifest, REQUIRED_AGENT_PACKAGE_CONTRACTS
from agent_factory.runtime_kernel.bindings import BindingSet, NodeBinding
from agent_factory.runtime_kernel.bindings.schema import (
    ModelOperationBindingPayload,
    ModelOperationWriteTarget,
    NodeBindingTarget,
    PromptBindingPayload,
    ToolAccessBindingPayload,
)
from agent_factory.runtime_kernel.node_providers.package import PackageNodeManifest
from agent_factory.runtime_kernel.patterns.registry import PatternRegistry
from agent_factory.runtime_kernel.patterns.schema import GraphPatternSpec
from agent_factory.runtime_render import RenderManifest, NodeRenderSpec, default_node_render_spec, validate_render_manifest
from agent_factory.tooling.spec import ToolRiskEvaluatorConfig, ToolSpec


PACKAGE_OUTPUT_ROOT = Path(".agentfactory/packages")
PACKAGE_BUILD_PLAN_PATH = "reports/package_build_plan.json"
PACKAGE_BUILD_REPORT_PATH = "reports/package_build_report.json"
_SAFE_ID_PATTERN = re.compile(r"[^a-z0-9_-]+")
_PROMPT_VARIABLES_ALLOWED_BY_PACKAGE_BUILD = {
    "messages",
    "runtime_context",
    "context",
    "model_context",
    "package_state",
    "resources",
    "current_user_input",
}


class PackageBuildError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PackageBuildResult:
    plan: PackageBuildPlan
    report: PackageBuildReport


def default_package_build_plan(
    *,
    factory_run_id: str,
    product_brief: ProductBriefOutput,
    runtime_design: RuntimeDesignOutput,
    capability_contract: CapabilityContractOutput,
    approved_package_tools: list[PackageToolBuildPlan] | None = None,
) -> PackageBuildPlan:
    agent_id = _safe_id(product_brief.working_title or product_brief.agent_goal or "generated_agent")
    if factory_run_id:
        agent_id = f"{agent_id}_{factory_run_id[:8]}"
    package_id = factory_run_id or agent_id
    prompt_templates = [
        {
            "prompt_id": f"prompt.{node.node_id}.default",
            "node_id": node.node_id,
            "template": _default_prompt_template(product_brief, runtime_design),
            "variables": ["messages", "runtime_context"],
        }
        for node in runtime_design.nodes
        if node.impl in {"cognitive.answer", "cognitive.structured"}
    ]
    if not prompt_templates:
        prompt_templates = [
            {
                "prompt_id": f"prompt.{node.node_id}.default",
                "node_id": node.node_id,
                "template": _default_prompt_template(product_brief, runtime_design),
                "variables": ["messages", "runtime_context"],
            }
            for node in _pattern_nodes_for_bindings(runtime_design)
            if node.impl in {"cognitive.answer", "cognitive.structured"}
        ]
    return PackageBuildPlan.model_validate(
        {
            "version": "package_build_plan.v0",
            "package_id": _safe_id(package_id),
            "agent_id": agent_id,
            "agent_name": product_brief.working_title or agent_id.replace("_", " ").title(),
            "agent_description": product_brief.agent_goal or product_brief.business_plan_text or runtime_design.graph_intent,
            "prompt_templates": prompt_templates,
            "structured_outputs": [],
            "package_nodes": [],
            "package_tools": [item.model_dump(mode="json") for item in approved_package_tools or []],
            "build_summary_text": "Package Build plan initialized from validated Product Brief, Runtime Design, and Capability Contract.",
            "warnings": list(capability_contract.deferred_decisions),
        }
    )


def merge_package_build_plan(
    *,
    base: PackageBuildPlan,
    model_plan: PackageBuildModelPlan | PackageBuildPlan | None,
    approved_package_tools: list[PackageToolBuildPlan] | None = None,
) -> PackageBuildPlan:
    if model_plan is None:
        return base
    base_prompts = {item.node_id: item for item in base.prompt_templates}
    if isinstance(model_plan, PackageBuildModelPlan):
        merged_plan = model_plan.to_package_build_plan(package_tools=approved_package_tools or base.package_tools)
    else:
        merged_plan = model_plan.model_copy(update={"package_tools": approved_package_tools or base.package_tools}, deep=True)
    merged_prompts = list(merged_plan.prompt_templates)
    for node_id, prompt in base_prompts.items():
        if node_id not in {item.node_id for item in merged_prompts}:
            merged_prompts.append(prompt)
    return merged_plan.model_copy(
        update={
            "package_id": base.package_id,
            "agent_id": base.agent_id,
            "agent_name": merged_plan.agent_name or base.agent_name,
            "agent_description": merged_plan.agent_description or base.agent_description,
            "prompt_templates": merged_prompts,
            "package_tools": approved_package_tools or base.package_tools,
        },
        deep=True,
    )


def build_agent_package(
    *,
    plan: PackageBuildPlan,
    product_brief: ProductBriefOutput,
    runtime_design: RuntimeDesignOutput,
    capability_contract: CapabilityContractOutput,
    scheduler_preparation: SchedulerPreparationOutput | None = None,
    output_root: Path = PACKAGE_OUTPUT_ROOT,
) -> PackageBuildResult:
    errors = _validate_plan_alignment(
        plan=plan,
        runtime_design=runtime_design,
        capability_contract=capability_contract,
    )
    package_root = (Path.cwd() / output_root / plan.package_id).resolve()
    if errors:
        return PackageBuildResult(
            plan=plan,
            report=PackageBuildReport(
                status="invalid",
                package_root=str(package_root),
                errors=errors,
                warnings=list(plan.warnings),
                scheduler_seed_count=len(scheduler_preparation.approved_seeds) if scheduler_preparation is not None else 0,
            ),
        )
    package_root.parent.mkdir(parents=True, exist_ok=True)
    temp_root = Path(mkdtemp(prefix=f".{plan.package_id}.", dir=str(package_root.parent))).resolve()
    materialized: list[PackageBuildMaterializedFile] = []
    static_checks: list[PackageBuildStaticCheck] = []
    try:
        _materialize_to_temp_root(
            temp_root=temp_root,
            materialized=materialized,
            plan=plan,
            product_brief=product_brief,
            runtime_design=runtime_design,
            capability_contract=capability_contract,
            scheduler_preparation=scheduler_preparation,
        )
        static_checks.extend(_validate_temp_package(temp_root))
        failed = [item for item in static_checks if item.status == "failed"]
        scheduler_seed_count = len(scheduler_preparation.approved_seeds) if scheduler_preparation is not None else 0
        report = PackageBuildReport(
            status="invalid" if failed else "valid",
            package_root=str(package_root),
            manifest_path=str(package_root / "agent_package.json"),
            materialized_files=materialized,
            static_checks=static_checks,
            errors=[item.message for item in failed if item.message],
            warnings=list(plan.warnings),
            scheduler_seed_count=scheduler_seed_count,
        )
        _write_json_file(
            temp_root=temp_root,
            relative_path=PACKAGE_BUILD_REPORT_PATH,
            payload=report.model_dump(mode="json"),
            generation_mode="system_generated",
            source="package_build_report",
            materialized=materialized,
        )
        if report.status != "valid":
            shutil.rmtree(temp_root, ignore_errors=True)
            return PackageBuildResult(plan=plan, report=report)
        _commit_temp_package(temp_root=temp_root, package_root=package_root, output_root=output_root)
        committed_report = report.model_copy(
            update={
                "package_root": str(package_root),
                "manifest_path": str(package_root / "agent_package.json"),
                "materialized_files": [
                    item.model_copy(update={"path": item.path}, deep=True)
                    for item in materialized
                ],
            },
            deep=True,
        )
        return PackageBuildResult(plan=plan, report=committed_report)
    except Exception as exc:
        shutil.rmtree(temp_root, ignore_errors=True)
        return PackageBuildResult(
            plan=plan,
            report=PackageBuildReport(
                status="failed",
                package_root=str(package_root),
                errors=[f"{type(exc).__name__}: {exc}"],
                warnings=list(plan.warnings),
                materialized_files=materialized,
                static_checks=static_checks,
                scheduler_seed_count=len(scheduler_preparation.approved_seeds) if scheduler_preparation is not None else 0,
            ),
        )


def package_build_message(plan: PackageBuildPlan, report: PackageBuildReport) -> str:
    lines = [
        "Package Build 已完成。" if report.status == "valid" else "Package Build 未通过静态校验。",
        "",
        f"Agent：{plan.agent_name}",
        f"Package：{report.package_root}",
        f"状态：{report.status}",
    ]
    if report.materialized_files:
        lines.extend(["", f"已物化文件：{len(report.materialized_files)} 个"])
    if report.scheduler_seed_count:
        lines.append(f"已准备定时任务：{report.scheduler_seed_count} 个，将在 Agent 首次运行时自动启用。")
    if report.errors:
        lines.extend(["", "错误：", *[f"- {item}" for item in report.errors]])
    if report.warnings:
        lines.extend(["", "提示：", *[f"- {item}" for item in report.warnings]])
    if plan.build_summary_text:
        lines.extend(["", "构建说明：", plan.build_summary_text])
    return "\n".join(lines).strip()


def _materialize_to_temp_root(
    *,
    temp_root: Path,
    materialized: list[PackageBuildMaterializedFile],
    plan: PackageBuildPlan,
    product_brief: ProductBriefOutput,
    runtime_design: RuntimeDesignOutput,
    capability_contract: CapabilityContractOutput,
    scheduler_preparation: SchedulerPreparationOutput | None = None,
) -> None:
    pattern = _package_pattern(runtime_design)
    contracts = _merge_generated_dependencies(
        contracts=_contract_payloads(capability_contract),
        plan=plan,
    )
    contracts = _merge_resource_descriptors(
        contracts=contracts,
        capability_contract=capability_contract,
    )
    contracts = _merge_scheduler_seed_contract(
        contracts=contracts,
        scheduler_preparation=scheduler_preparation,
    )
    state_contract = contracts.get("state") or {}
    state_enabled = bool(state_contract.get("enabled", True))
    state_config = state_contract.get("config") if isinstance(state_contract.get("config"), dict) else {}
    state_namespace = str(state_config.get("namespace") or "package")
    assembly = _assembly_spec(
        plan=plan,
        runtime_design=runtime_design,
        product_brief=product_brief,
        pattern=pattern,
        bindings=_binding_set(
            plan=plan,
            runtime_design=runtime_design,
            state_namespace=state_namespace,
        ),
    )
    manifest = _agent_package_manifest(
        plan=plan,
        runtime_design=runtime_design,
        pattern=pattern,
        contracts=contracts,
    )
    render_manifest = _render_manifest(runtime_design=runtime_design, pattern=pattern)
    resources = {"version": "factory_resources.v0", "resources": _resource_values(capability_contract)}
    sandbox_contract = _sandbox_contract(capability_contract)
    _write_json_file(
        temp_root=temp_root,
        relative_path="agent_package.json",
        payload=manifest.model_dump(mode="json"),
        generation_mode="system_generated",
        source="agent_package_manifest",
        materialized=materialized,
    )
    _write_json_file(
        temp_root=temp_root,
        relative_path="assembly_spec.json",
        payload=assembly.model_dump(mode="json"),
        generation_mode="system_generated",
        source="assembly_spec",
        materialized=materialized,
    )
    _write_json_file(
        temp_root=temp_root,
        relative_path="render_manifest.json",
        payload=render_manifest.model_dump(mode="json"),
        generation_mode="system_generated",
        source="render_manifest",
        materialized=materialized,
    )
    _write_json_file(
        temp_root=temp_root,
        relative_path="resources.json",
        payload=resources,
        generation_mode="system_generated",
        source="resources",
        materialized=materialized,
    )
    _write_json_file(
        temp_root=temp_root,
        relative_path="sandbox_contract.json",
        payload=sandbox_contract,
        generation_mode="system_generated",
        source="sandbox_contract",
        materialized=materialized,
    )
    for key, payload in sorted(contracts.items()):
        _write_json_file(
            temp_root=temp_root,
            relative_path=f"contracts/{key}.json",
            payload=payload,
            generation_mode="system_generated",
            source=f"contract:{key}",
            materialized=materialized,
        )
    if state_enabled:
        _write_json_file(
            temp_root=temp_root,
            relative_path=str(state_config.get("schema_path") or f"state/{state_namespace}.schema.json"),
            payload=_state_schema(runtime_design, physical_namespace=state_namespace),
            generation_mode="system_generated",
            source="state_schema",
            materialized=materialized,
        )
        _write_json_file(
            temp_root=temp_root,
            relative_path=str(state_config.get("initial_state_path") or f"state/{state_namespace}.initial.json"),
            payload=_state_initial(runtime_design, physical_namespace=state_namespace),
            generation_mode="system_generated",
            source="state_initial",
            materialized=materialized,
        )
    _write_json_file(
        temp_root=temp_root,
        relative_path=PACKAGE_BUILD_PLAN_PATH,
        payload=plan.model_dump(mode="json"),
        generation_mode="system_generated",
        source="package_build_plan",
        materialized=materialized,
    )
    _write_json_file(
        temp_root=temp_root,
        relative_path="bindings/node_bindings.json",
        payload=assembly.bindings.model_dump(mode="json"),
        generation_mode="system_generated",
        source="bindings",
        materialized=materialized,
    )
    for prompt in plan.prompt_templates:
        _write_text_file(
            temp_root=temp_root,
            relative_path=f"prompts/{_safe_file_id(prompt.prompt_id)}.md",
            content=prompt.template,
            file_type="markdown",
            generation_mode="model_generated",
            source=f"prompt:{prompt.prompt_id}",
            materialized=materialized,
        )
    for node in plan.package_nodes:
        node_dir = f"nodes/{_safe_file_id(node.node_id)}"
        _write_json_file(
            temp_root=temp_root,
            relative_path=f"{node_dir}/manifest.json",
            payload=_package_node_manifest(node),
            generation_mode="model_generated",
            source=f"package_node:{node.impl_id}",
            materialized=materialized,
        )
        _write_text_file(
            temp_root=temp_root,
            relative_path=f"{node_dir}/node.py",
            content=node.code,
            file_type="python",
            generation_mode="model_generated",
            source=f"package_node:{node.impl_id}",
            materialized=materialized,
        )
    for tool in plan.package_tools:
        tool_dir = f"tools/{tool.tool_id}"
        _write_json_file(
            temp_root=temp_root,
            relative_path=f"{tool_dir}/manifest.json",
            payload=_tool_spec(tool).model_dump(mode="json"),
            generation_mode="model_generated",
            source=f"package_tool:{tool.tool_id}",
            materialized=materialized,
        )
        _write_text_file(
            temp_root=temp_root,
            relative_path=f"{tool_dir}/tool.py",
            content=tool.code,
            file_type="python",
            generation_mode="model_generated",
            source=f"package_tool:{tool.tool_id}",
            materialized=materialized,
        )

def _validate_temp_package(temp_root: Path) -> list[PackageBuildStaticCheck]:
    checks: list[PackageBuildStaticCheck] = []

    def record(name: str, fn) -> None:
        try:
            fn()
            checks.append(PackageBuildStaticCheck(name=name, status="passed"))
        except Exception as exc:
            checks.append(PackageBuildStaticCheck(name=name, status="failed", message=f"{type(exc).__name__}: {exc}"))

    loaded_package: Any = None

    def load_package() -> None:
        nonlocal loaded_package
        loaded_package = AgentPackageLoader().load_path(temp_root / "agent_package.json")

    record("agent_package_loader", load_package)

    def parse_contracts() -> None:
        package = loaded_package or AgentPackageLoader().load_path(temp_root / "agent_package.json")
        registry = default_runtime_contract_registry()
        for payload in package.contracts.values():
            registry.parse(payload)

    record("runtime_contract_registry", parse_contracts)

    def validate_render() -> None:
        package = loaded_package or AgentPackageLoader().load_path(temp_root / "agent_package.json")
        pattern = _compile_pattern_for_validation(package)
        validate_render_manifest(package.render_manifest, {node.id for node in pattern.nodes})

    record("render_manifest", validate_render)

    def validate_state() -> None:
        package = loaded_package or AgentPackageLoader().load_path(temp_root / "agent_package.json")
        state_contract = package.contracts.get("state") or {}
        if not bool(state_contract.get("enabled", True)):
            return
        config = state_contract.get("config") if isinstance(state_contract.get("config"), dict) else {}
        schema = _read_json_object(temp_root / str(config.get("schema_path") or "state/package.schema.json"))
        initial = _read_json_object(temp_root / str(config.get("initial_state_path") or "state/package.initial.json"))
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(initial)

    record("state_contract_files", validate_state)

    def validate_resources() -> None:
        package = loaded_package or AgentPackageLoader().load_path(temp_root / "agent_package.json")
        _validate_materialized_resource_files(package.resources, package.contracts.get("resources") or {})

    record("resource_contract_files", validate_resources)

    def validate_sandbox_semantics() -> None:
        package = loaded_package or AgentPackageLoader().load_path(temp_root / "agent_package.json")
        _validate_materialized_sandbox_dependency_boundary(
            package.sandbox_contract,
            package.contracts.get("dependencies") or {},
        )

    record("sandbox_dependency_boundary", validate_sandbox_semantics)

    def validate_python() -> None:
        for path in sorted([*temp_root.glob("nodes/*/*.py"), *temp_root.glob("tools/*/*.py")]):
            py_compile.compile(str(path), doraise=True)

    record("python_compile", validate_python)

    def validate_package_nodes() -> None:
        for manifest_path in sorted(temp_root.glob("nodes/*/manifest.json")):
            manifest = PackageNodeManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
            entrypoint_path = _package_node_entrypoint_path(
                node_dir=manifest_path.parent,
                entrypoint=manifest.entrypoint,
            )
            _validate_python_entrypoint_signature(
                path=entrypoint_path,
                function_name="run",
                parameter_names=("input", "context"),
            )

    record("package_node_provider", validate_package_nodes)

    def validate_package_tools() -> None:
        for manifest_path in sorted(temp_root.glob("tools/*/manifest.json")):
            payload = _read_json_object(manifest_path)
            spec = ToolSpec.model_validate(payload)
            entrypoint_path = _package_tool_entrypoint_path(
                package_root=temp_root,
                entrypoint=spec.entrypoint,
            )
            _validate_python_entrypoint_signature(
                path=entrypoint_path,
                function_name="run",
                parameter_names=("arguments", "resources"),
            )

    record("package_tool_provider", validate_package_tools)
    return checks


def _package_node_entrypoint_path(*, node_dir: Path, entrypoint: str) -> Path:
    relative_path, function_name = _split_package_python_entrypoint(entrypoint)
    if function_name != "run":
        raise ValueError("package node entrypoint function must be run")
    return _safe_existing_file(node_dir, relative_path)


def _package_tool_entrypoint_path(*, package_root: Path, entrypoint: str) -> Path:
    relative_path, function_name = _split_package_python_entrypoint(entrypoint)
    if function_name != "run":
        raise ValueError("package tool entrypoint function must be run")
    return _safe_existing_file(package_root, relative_path)


def _split_package_python_entrypoint(entrypoint: str) -> tuple[str, str]:
    raw = entrypoint.strip()
    if raw.startswith("python:"):
        raw = raw.removeprefix("python:")
    elif raw.startswith(("python-import:", "mcp:")):
        raise ValueError("generated package entrypoint must be a package-relative Python file")
    if ":" not in raw:
        raise ValueError("entrypoint must use path.py:run format")
    path_text, function_name = raw.rsplit(":", 1)
    path = Path(path_text)
    if path.is_absolute() or path.suffix != ".py" or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("generated package entrypoint path must be a safe relative Python file")
    return path_text, function_name


def _safe_existing_file(root: Path, relative_path: str) -> Path:
    path = _safe_target(root, relative_path)
    if not path.exists():
        raise FileNotFoundError(f"package entrypoint file does not exist: {relative_path}")
    if not path.is_file():
        raise ValueError(f"package entrypoint is not a file: {relative_path}")
    return path


def _validate_python_entrypoint_signature(
    *,
    path: Path,
    function_name: str,
    parameter_names: tuple[str, ...],
) -> None:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(
        (item for item in module.body if isinstance(item, ast.FunctionDef) and item.name == function_name),
        None,
    )
    if function is None:
        raise ValueError(f"entrypoint function is missing: {function_name}")
    arguments = function.args
    if arguments.posonlyargs or arguments.vararg or arguments.kwarg or arguments.kwonlyargs:
        raise ValueError(f"{function_name} must use the fixed positional signature {parameter_names}")
    actual_names = tuple(argument.arg for argument in arguments.args)
    if actual_names != parameter_names:
        raise ValueError(
            f"{function_name} must use the fixed signature "
            f"({', '.join(parameter_names)}); got ({', '.join(actual_names)})"
        )


def _compile_pattern_for_validation(package: Any) -> GraphPatternSpec:
    if package.assembly_spec.runtime.pattern_id in {pattern.pattern_id for pattern in package.patterns}:
        return next(pattern for pattern in package.patterns if pattern.pattern_id == package.assembly_spec.runtime.pattern_id)
    return _builtin_pattern_registry().get(package.assembly_spec.runtime.pattern_id)


def _commit_temp_package(*, temp_root: Path, package_root: Path, output_root: Path) -> None:
    expected_parent = (Path.cwd() / output_root).resolve()
    package_root.parent.mkdir(parents=True, exist_ok=True)
    try:
        package_root.relative_to(expected_parent)
    except ValueError as exc:
        raise PackageBuildError(f"package root escapes output root: {package_root}") from exc
    if package_root.exists():
        shutil.rmtree(package_root)
    temp_root.replace(package_root)


def _validate_plan_alignment(
    *,
    plan: PackageBuildPlan,
    runtime_design: RuntimeDesignOutput,
    capability_contract: CapabilityContractOutput,
) -> list[str]:
    errors: list[str] = []
    pattern = _package_pattern(runtime_design)
    pattern_nodes = {node.id: node for node in pattern.nodes}
    cognitive_node_ids = {
        node.id
        for node in pattern.nodes
        if node.impl in {"cognitive.answer", "cognitive.structured"}
    }
    structured_node_ids = {node.id for node in pattern.nodes if node.impl == "cognitive.structured"}
    errors.extend(_validate_resource_contract_semantics(capability_contract))
    errors.extend(_validate_state_resource_separation(runtime_design, capability_contract))
    errors.extend(_validate_sandbox_dependency_separation(plan, capability_contract))
    expected_nodes = {item.impl_id for item in capability_contract.package_nodes_to_generate}
    expected_nodes.update(item.impl_id for item in runtime_design.package_nodes_to_generate)
    actual_nodes = {item.impl_id for item in plan.package_nodes}
    missing_nodes = sorted(expected_nodes.difference(actual_nodes))
    if missing_nodes:
        errors.append("package build plan missing package node implementations: " + ", ".join(missing_nodes))
    for prompt in plan.prompt_templates:
        if prompt.node_id not in cognitive_node_ids:
            errors.append(f"prompt template references non-cognitive preset node: {prompt.node_id}")
        unknown_variables = sorted(
            set(prompt.variables).difference(_PROMPT_VARIABLES_ALLOWED_BY_PACKAGE_BUILD)
        )
        if unknown_variables:
            errors.append(
                f"prompt template {prompt.prompt_id} declares variables without a Kernel data source: "
                + ", ".join(unknown_variables)
            )
    resource_values = _resource_values(capability_contract)
    for tool in plan.package_tools:
        for local_name, selector in tool.resources.items():
            try:
                _resolve_resource_selector(resource_values, selector)
            except KeyError:
                errors.append(
                    f"package tool {tool.tool_id} resource mapping {local_name} references unknown resource selector: "
                    f"{selector}"
                )
    expected_structured_nodes = {item.produced_by_node for item in runtime_design.structured_outputs}
    actual_structured_nodes = {item.node_id for item in plan.structured_outputs}
    missing_structured = sorted(expected_structured_nodes.difference(actual_structured_nodes))
    if missing_structured:
        errors.append("package build plan missing structured output schemas: " + ", ".join(missing_structured))
    for item in plan.structured_outputs:
        if item.node_id not in structured_node_ids:
            errors.append(f"structured output references non-structured preset node: {item.node_id}")
    for item in plan.package_nodes:
        if item.impl_id not in {node.impl for node in pattern.nodes}:
            errors.append(f"package node implementation is not used by selected preset pattern: {item.impl_id}")
    for node in runtime_design.nodes:
        pattern_node = pattern_nodes.get(node.node_id)
        if pattern_node is None:
            errors.append(f"runtime design node is outside selected preset pattern: {node.node_id}")
            continue
        if node.impl != pattern_node.impl:
            errors.append(
                f"runtime design node {node.node_id} impl does not match selected preset pattern: "
                f"{node.impl} != {pattern_node.impl}"
            )
    state_namespace = _state_namespace_from_contract(capability_contract)
    for item in plan.structured_outputs:
        try:
            ModelOperationBindingPayload(
                operation="structured_json",
                model_role="main",
                output_schema=item.output_schema,
                write_target=_normalized_write_target(
                    raw=item.write_target,
                    state_namespace=state_namespace,
                    node_id=item.node_id,
                ),
                max_attempts=item.max_attempts,
                structured_method=item.structured_method,
                prompt_id=item.prompt_id,
            )
        except Exception as exc:
            errors.append(f"structured output binding is invalid for {item.node_id}: {exc}")
    return errors


def _agent_package_manifest(
    *,
    plan: PackageBuildPlan,
    runtime_design: RuntimeDesignOutput,
    pattern: GraphPatternSpec,
    contracts: dict[str, dict[str, Any]],
) -> AgentPackageManifest:
    contract_paths = {key: f"contracts/{key}.json" for key in sorted(contracts)}
    missing = sorted(REQUIRED_AGENT_PACKAGE_CONTRACTS.difference(contract_paths))
    if missing:
        raise PackageBuildError("cannot build package manifest without required contracts: " + ", ".join(missing))
    return AgentPackageManifest(
        factory_run_id=plan.package_id,
        agent={
            "id": plan.agent_id,
            "name": plan.agent_name,
            "description": plan.agent_description,
        },
        runtime={"system_package": False, "execution_backend": "docker"},
        assembly_spec_path="assembly_spec.json",
        render_manifest_path="render_manifest.json",
        resources_path="resources.json",
        sandbox_contract_path="sandbox_contract.json",
        contracts=contract_paths,
        bindings={"node_bindings": "bindings/node_bindings.json"},
        patterns=[],
        prompts=[f"prompts/{_safe_file_id(item.prompt_id)}.md" for item in plan.prompt_templates],
        tools=[f"tools/{item.tool_id}/manifest.json" for item in plan.package_tools],
    )


def _assembly_spec(
    *,
    plan: PackageBuildPlan,
    runtime_design: RuntimeDesignOutput,
    product_brief: ProductBriefOutput,
    pattern: GraphPatternSpec,
    bindings: BindingSet,
) -> AgentAssemblySpec:
    return AgentAssemblySpec.model_validate(
        {
            "schema_version": "0.1",
            "agent": {
                "id": plan.agent_id,
                "name": plan.agent_name,
                "description": plan.agent_description,
                "version": "0.1.0",
            },
            "runtime": {
                "pattern_id": runtime_design.selected_pattern_id,
                "compiled_pattern_id": None,
                "user_config": {},
                "agent_config": {
                    "agent_id": plan.agent_id,
                    "factory_generated": True,
                },
            },
            "graph_overrides": {"node_wrappers": []},
            "bindings": bindings.model_dump(mode="json"),
            "tools": [],
            "output": {
                "citations_required": False,
                "format": "markdown" if any("markdown" in item.lower() for item in product_brief.expected_outputs) else "text",
            },
            "harness": [],
            "metadata": {
                "provenance": {
                    "source": "factory_package_build",
                    "product_brief_version": product_brief.version,
                    "runtime_design_version": runtime_design.version,
                }
            },
        }
    )


def _binding_set(
    *,
    plan: PackageBuildPlan,
    runtime_design: RuntimeDesignOutput,
    state_namespace: str,
) -> BindingSet:
    prompts_by_node = {item.node_id: item for item in plan.prompt_templates}
    structured_by_node = {item.node_id: item for item in plan.structured_outputs}
    generated_tool_ids = [item.tool_id for item in plan.package_tools]
    bindings: list[NodeBinding] = []
    for node in _pattern_nodes_for_bindings(runtime_design):
        prompt = prompts_by_node.get(node.node_id)
        if prompt and node.impl.startswith("cognitive."):
            bindings.append(
                NodeBinding(
                    binding_id=f"{node.node_id}.prompt",
                    binding_type="prompt",
                    target=NodeBindingTarget(node_id=node.node_id, impl=node.impl),
                    payload=PromptBindingPayload(
                        prompt_id=prompt.prompt_id,
                        template=prompt.template,
                        variables=prompt.variables,
                    ),
                )
            )
        if node.impl == "cognitive.structured":
            structured = structured_by_node.get(node.node_id)
            if structured is not None:
                bindings.append(
                    NodeBinding(
                        binding_id=f"{node.node_id}.model_operation",
                        binding_type="model_operation",
                        target=NodeBindingTarget(node_id=node.node_id, impl=node.impl),
                        payload=ModelOperationBindingPayload(
                            operation="structured_json",
                            model_role="main",
                            output_schema=structured.output_schema,
                            write_target=_normalized_write_target(
                                raw=structured.write_target,
                                state_namespace=state_namespace,
                                node_id=node.node_id,
                            ),
                            max_attempts=structured.max_attempts,
                            structured_method=structured.structured_method,
                            prompt_id=structured.prompt_id,
                        ),
                    )
                )
        if _node_accepts_tool_access(node):
            allowed = _dedupe([*node.tool_access_required, *generated_tool_ids])
            if allowed:
                bindings.append(
                    NodeBinding(
                        binding_id=f"{node.node_id}.tool_access",
                        binding_type="tool_access",
                        target=NodeBindingTarget(node_id=node.node_id, impl=node.impl),
                        payload=ToolAccessBindingPayload(
                            allowed_tool_ids=allowed,
                            approval_policy="standard",
                        ),
                    )
                )
    return BindingSet(node_bindings=bindings)


def _pattern_nodes_for_bindings(runtime_design: RuntimeDesignOutput):
    design_by_id = {node.node_id: node for node in runtime_design.nodes}
    pattern = _builtin_pattern_registry().get(runtime_design.selected_pattern_id or "")
    nodes = []
    for node in pattern.nodes:
        if node.id in design_by_id:
            nodes.append(design_by_id[node.id])
            continue
        nodes.append(
            type("_NodePlan", (), {
                "node_id": node.id,
                "impl": node.impl,
                "requires_tools": node.impl in {"cognitive.answer", "operational.tool_call"},
                "tool_access_required": [],
            })()
        )
    return nodes


def _node_accepts_tool_access(node: Any) -> bool:
    return bool(getattr(node, "requires_tools", False)) or getattr(node, "impl", "") in {
        "cognitive.answer",
        "operational.tool_call",
    }


def _package_pattern(runtime_design: RuntimeDesignOutput) -> GraphPatternSpec:
    return _builtin_pattern_registry().get(runtime_design.selected_pattern_id or "")


def _render_manifest(*, runtime_design: RuntimeDesignOutput, pattern: GraphPatternSpec) -> RenderManifest:
    design_by_id = {node.node_id: node for node in runtime_design.nodes}
    nodes: dict[str, NodeRenderSpec] = {}
    for node in pattern.nodes:
        design_node = design_by_id.get(node.id)
        if design_node is None:
            nodes[node.id] = default_node_render_spec(node_id=node.id, node_type=node.type, impl=node.impl)
            continue
        nodes[node.id] = NodeRenderSpec(
            node_id=node.id,
            label=node.id.replace("_", " ").title(),
            kind=node.type,
            purpose=design_node.purpose,
            doing=f"运行 {node.impl}。",
            expected_output="生成符合 RuntimeKernel patch 规范的节点输出。",
            visible_to_user=design_node.visible_to_user,
        )
    return RenderManifest(graph_id=pattern.pattern_id, nodes=nodes)


def _contract_payloads(capability_contract: CapabilityContractOutput) -> dict[str, dict[str, Any]]:
    payloads = {key: value.model_dump(mode="json") for key, value in capability_contract.contract_drafts.items()}
    missing = sorted(REQUIRED_AGENT_PACKAGE_CONTRACTS.difference(payloads))
    if missing:
        raise PackageBuildError("capability contract missing required contract drafts: " + ", ".join(missing))
    return payloads


def _merge_scheduler_seed_contract(
    *,
    contracts: dict[str, dict[str, Any]],
    scheduler_preparation: SchedulerPreparationOutput | None,
) -> dict[str, dict[str, Any]]:
    merged = json.loads(json.dumps(contracts, ensure_ascii=False))
    seeds = list(scheduler_preparation.approved_seeds if scheduler_preparation is not None else [])
    if not seeds:
        return merged
    scheduler_contract = merged.get("scheduler")
    if not isinstance(scheduler_contract, dict):
        raise PackageBuildError("scheduler seed requires scheduler contract")
    scheduler_contract["enabled"] = True
    merged["scheduler_seed"] = {
        "type": "scheduler_seed",
        "version": "scheduler_seed_contract.v0",
        "enabled": True,
        "config": {
            "seeds": [seed.model_dump(mode="json") for seed in seeds],
        },
    }
    return merged


def _merge_generated_dependencies(
    *,
    contracts: dict[str, dict[str, Any]],
    plan: PackageBuildPlan,
) -> dict[str, dict[str, Any]]:
    merged = json.loads(json.dumps(contracts, ensure_ascii=False))
    dependencies = merged.get("dependencies")
    if not isinstance(dependencies, dict):
        raise PackageBuildError("dependencies contract is required before package materialization")
    config = dependencies.get("config")
    if not isinstance(config, dict):
        config = {}
        dependencies["config"] = config

    python_requirements = _dedupe(
        [
            *_contract_dependency_list(config, "python_requirements"),
            *[item for node in plan.package_nodes for item in node.python_requirements],
            *[item for tool in plan.package_tools for item in tool.python_requirements],
        ]
    )
    system_packages = _dedupe(
        [
            *_contract_dependency_list(config, "system_packages"),
            *[item for node in plan.package_nodes for item in node.system_packages],
            *[item for tool in plan.package_tools for item in tool.system_packages],
        ]
    )
    system_binaries = _dedupe(
        [
            *_contract_dependency_list(config, "system_binaries"),
            *[item for node in plan.package_nodes for item in node.system_binaries],
            *[item for tool in plan.package_tools for item in tool.system_binaries],
        ]
    )
    if (python_requirements or system_packages or system_binaries) and not bool(dependencies.get("enabled", True)):
        raise PackageBuildError("generated code declares dependencies but dependencies contract is disabled")
    config["python_requirements"] = python_requirements
    config["system_packages"] = system_packages
    config["system_binaries"] = system_binaries
    config.setdefault("install_mode", "sandbox_init")
    return merged


def _merge_resource_descriptors(
    *,
    contracts: dict[str, dict[str, Any]],
    capability_contract: CapabilityContractOutput,
) -> dict[str, dict[str, Any]]:
    merged = json.loads(json.dumps(contracts, ensure_ascii=False))
    resources_contract = merged.get("resources")
    if not isinstance(resources_contract, dict):
        raise PackageBuildError("resources contract is required before package materialization")
    config = resources_contract.get("config")
    if not isinstance(config, dict):
        config = {}
        resources_contract["config"] = config
    descriptors = [
        {
            "resource_id": item.resource_id,
            "description": item.description,
            "required": item.required,
            "value_schema": item.value_schema,
            "default_value": item.default_value,
            "secret_fields": item.secret_fields,
            "used_by": item.used_by,
            "sandbox_access_expectation": item.sandbox_access_expectation,
        }
        for item in capability_contract.resources_required
    ]
    config["resource_descriptors"] = descriptors
    config.setdefault("resources_path", "resources.json")
    return merged


def _contract_dependency_list(config: dict[str, Any], key: str) -> list[str]:
    raw = config.get(key, [])
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise PackageBuildError(f"dependencies contract config.{key} must be a list")
    return [str(item) for item in raw]


def _state_namespace_from_contract(capability_contract: CapabilityContractOutput) -> str:
    state_draft = capability_contract.contract_drafts.get("state")
    if state_draft is None:
        return "package"
    config = state_draft.config if isinstance(state_draft.config, dict) else {}
    namespace = str(config.get("namespace") or "").strip()
    return namespace or "package"


def _normalized_write_target(
    *,
    raw: dict[str, Any],
    state_namespace: str,
    node_id: str,
) -> ModelOperationWriteTarget:
    payload = dict(raw or {})
    section = str(payload.get("section") or "package_state").strip()
    if section == "context":
        return ModelOperationWriteTarget(section="context")
    if section != "package_state":
        raise ValueError(f"unsupported structured write target section: {section}")
    namespace = str(payload.get("namespace") or state_namespace).strip()
    path = payload.get("path")
    if path is None:
        normalized_path = [node_id]
    elif isinstance(path, list):
        normalized_path = [str(item).strip() for item in path if str(item).strip()]
    else:
        raise ValueError("structured write target path must be a list of field segments")
    return ModelOperationWriteTarget(
        section="package_state",
        namespace=namespace,
        path=normalized_path,
    )


def _resource_values(capability_contract: CapabilityContractOutput) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for item in capability_contract.resources_required:
        values[item.resource_id] = _resource_default_value(item)
    return values


def _resource_default_value(item) -> Any:
    if item.value_schema:
        value = _empty_value_from_json_schema(item.value_schema)
        if item.default_value:
            value = _deep_merge_json_values(value, item.default_value)
        return json.loads(json.dumps(value, ensure_ascii=False))
    if item.default_value:
        return json.loads(json.dumps(item.default_value, ensure_ascii=False))
    return {}


def _deep_merge_json_values(base: Any, override: Any) -> Any:
    if isinstance(base, dict) and isinstance(override, dict):
        merged = dict(base)
        for key, value in override.items():
            merged[str(key)] = _deep_merge_json_values(merged.get(str(key)), value)
        return merged
    return json.loads(json.dumps(override, ensure_ascii=False))


def _validate_resource_contract_semantics(capability_contract: CapabilityContractOutput) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for item in capability_contract.resources_required:
        if item.resource_id in seen:
            errors.append(f"resource requirement duplicated resource_id: {item.resource_id}")
            continue
        seen.add(item.resource_id)
        if item.value_schema:
            try:
                Draft202012Validator.check_schema(item.value_schema)
            except Exception as exc:
                errors.append(f"resource {item.resource_id} value_schema is not a valid JSON Schema: {exc}")
                continue
            value = _resource_default_value(item)
            try:
                Draft202012Validator(item.value_schema).validate(value)
            except Exception as exc:
                errors.append(
                    f"resource {item.resource_id} default/runtime value does not satisfy value_schema: {exc.message}"
                )
        for field in item.secret_fields:
            if not _resource_schema_contains_path(item.value_schema, field):
                errors.append(
                    f"resource {item.resource_id} secret field is not declared in value_schema: {field}"
                )
    return errors


def _validate_materialized_resource_files(resources_payload: dict[str, Any], resources_contract: dict[str, Any]) -> None:
    values = resources_payload.get("resources")
    if not isinstance(values, dict):
        raise ValueError("resources.json must contain object field resources")
    config = resources_contract.get("config") if isinstance(resources_contract.get("config"), dict) else {}
    descriptors = config.get("resource_descriptors") if isinstance(config, dict) else []
    if not isinstance(descriptors, list):
        raise ValueError("resources contract config.resource_descriptors must be a list")
    descriptor_ids: set[str] = set()
    for descriptor in descriptors:
        if not isinstance(descriptor, dict):
            raise ValueError("resources contract descriptors must be objects")
        resource_id = str(descriptor.get("resource_id") or "").strip()
        if not resource_id:
            raise ValueError("resources contract descriptor resource_id must not be empty")
        descriptor_ids.add(resource_id)
        if resource_id not in values:
            raise ValueError(f"resources.json missing value for descriptor: {resource_id}")
        value_schema = descriptor.get("value_schema")
        if isinstance(value_schema, dict) and value_schema:
            Draft202012Validator.check_schema(value_schema)
            Draft202012Validator(value_schema).validate(values[resource_id])
    extra_values = sorted(set(values).difference(descriptor_ids))
    if extra_values:
        raise ValueError("resources.json contains values without descriptors: " + ", ".join(extra_values))


def _resource_schema_contains_path(schema: dict[str, Any], selector: str) -> bool:
    if not selector:
        return False
    current: Any = schema
    for part in selector.split("."):
        if not isinstance(current, dict):
            return False
        properties = current.get("properties")
        if not isinstance(properties, dict) or part not in properties:
            return False
        current = properties[part]
    return True


def _validate_state_resource_separation(
    runtime_design: RuntimeDesignOutput,
    capability_contract: CapabilityContractOutput,
) -> list[str]:
    resource_fields = _resource_top_level_fields(capability_contract)
    if not resource_fields:
        return []
    errors: list[str] = []
    for namespace in runtime_design.state_namespaces:
        overlapping = sorted(set(namespace.initial_shape).intersection(resource_fields))
        if overlapping:
            errors.append(
                "package_state namespace "
                f"{namespace.namespace} duplicates runtime resource fields: {', '.join(overlapping)}. "
                "Runtime configuration must stay in resources.json/resources contract; package_state should store "
                "business state such as confirmations, progress, and derived results."
            )
    return errors


def _resource_top_level_fields(capability_contract: CapabilityContractOutput) -> set[str]:
    fields: set[str] = set()
    for item in capability_contract.resources_required:
        schema_properties = item.value_schema.get("properties") if isinstance(item.value_schema, dict) else None
        if isinstance(schema_properties, dict):
            fields.update(str(key) for key in schema_properties)
        if isinstance(item.default_value, dict):
            fields.update(str(key) for key in item.default_value)
    return fields


def _validate_sandbox_dependency_separation(
    plan: PackageBuildPlan,
    capability_contract: CapabilityContractOutput,
) -> list[str]:
    dependency_aliases = _declared_dependency_aliases(plan, capability_contract)
    if not dependency_aliases:
        return []
    errors: list[str] = []
    for item in capability_contract.sandbox_requirements:
        for service in item.services_required:
            normalized = _dependency_alias(service)
            if normalized in dependency_aliases:
                errors.append(
                    f"sandbox requirement {item.requirement_id} lists dependency-like service {service}; "
                    "Python packages, system packages, and binaries must be declared only in "
                    "contracts/dependencies.json, not sandbox services."
                )
    return errors


def _validate_materialized_sandbox_dependency_boundary(
    sandbox_contract: dict[str, Any],
    dependencies_contract: dict[str, Any],
) -> None:
    config = dependencies_contract.get("config") if isinstance(dependencies_contract.get("config"), dict) else {}
    dependency_aliases: set[str] = set()
    if isinstance(config, dict):
        for requirement in _contract_dependency_list(config, "python_requirements"):
            dependency_aliases.update(_python_requirement_aliases(requirement))
        for key in ("system_packages", "system_binaries"):
            for dependency in _contract_dependency_list(config, key):
                dependency_aliases.update(_dependency_aliases(dependency))
    if not dependency_aliases:
        return
    services = sandbox_contract.get("services", [])
    if not isinstance(services, list):
        raise ValueError("sandbox_contract.services must be a list")
    for service in services:
        if not isinstance(service, dict):
            raise ValueError("sandbox_contract.services items must be objects")
        service_id = str(service.get("service_id") or "").strip()
        endpoint = str(service.get("endpoint") or "").strip()
        for value in (service_id, endpoint):
            if _dependency_alias(value) in dependency_aliases:
                raise ValueError(
                    f"sandbox service {service_id or endpoint} duplicates a declared dependency; "
                    "dependencies belong in contracts/dependencies.json, while sandbox services are external endpoints"
                )


def _declared_dependency_aliases(
    plan: PackageBuildPlan,
    capability_contract: CapabilityContractOutput,
) -> set[str]:
    aliases: set[str] = set()
    dependencies = capability_contract.contract_drafts.get("dependencies")
    if dependencies is not None and isinstance(dependencies.config, dict):
        for requirement in _contract_dependency_list(dependencies.config, "python_requirements"):
            aliases.update(_python_requirement_aliases(requirement))
        for key in ("system_packages", "system_binaries"):
            for dependency in _contract_dependency_list(dependencies.config, key):
                aliases.update(_dependency_aliases(dependency))
    for requirement in [
        *[item for node in plan.package_nodes for item in node.python_requirements],
        *[item for tool in plan.package_tools for item in tool.python_requirements],
    ]:
        aliases.update(_python_requirement_aliases(requirement))
    for dependency in [
        *[item for node in plan.package_nodes for item in node.system_packages],
        *[item for node in plan.package_nodes for item in node.system_binaries],
        *[item for tool in plan.package_tools for item in tool.system_packages],
        *[item for tool in plan.package_tools for item in tool.system_binaries],
    ]:
        aliases.update(_dependency_aliases(dependency))
    return aliases


def _python_requirement_aliases(requirement: str) -> set[str]:
    try:
        from packaging.requirements import Requirement

        name = Requirement(requirement).name
    except Exception:
        name = requirement
    return _dependency_aliases(name)


def _dependency_aliases(value: str) -> set[str]:
    alias = _dependency_alias(value)
    aliases = {alias}
    for prefix in ("python", "py", "pip", "apt", "bin", "binary", "system"):
        aliases.add(f"{prefix}_{alias}")
    return aliases


def _dependency_alias(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")


def _empty_value_from_json_schema(schema: dict[str, Any]) -> Any:
    if not isinstance(schema, dict):
        return {}
    if "default" in schema:
        return json.loads(json.dumps(schema["default"], ensure_ascii=False))
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = next((item for item in schema_type if item != "null"), schema_type[0] if schema_type else None)
    if schema_type == "object":
        properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
        return {
            str(key): _empty_value_from_json_schema(value)
            for key, value in properties.items()
            if isinstance(value, dict)
        }
    if schema_type == "array":
        return []
    if schema_type == "string":
        return ""
    if schema_type in {"integer", "number"}:
        return 0
    if schema_type == "boolean":
        return False
    return {}


def _resolve_resource_selector(resources: dict[str, Any], selector: str) -> Any:
    current: Any = resources
    for part in selector.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(selector)
        current = current[part]
    return current


def _sandbox_contract(capability_contract: CapabilityContractOutput) -> dict[str, Any]:
    network_required = any(item.network_required for item in capability_contract.sandbox_requirements)
    secrets = [
        {"secret_id": secret, "source": "runtime_provided", "purpose": item.description}
        for item in capability_contract.sandbox_requirements
        for secret in item.secrets_required
    ]
    services = [
        {
            "service_id": service,
            "kind": "remote_service",
            "endpoint": service,
            "ports": [],
            "purpose": item.description,
        }
        for item in capability_contract.sandbox_requirements
        for service in item.services_required
    ]
    return {
        "version": "sandbox_contract.v0",
        "backend": "docker",
        "image": "agentfactory-runtime-python:3.12",
        "workdir": "/workdir",
        "network_policy": {
            "mode": "default_allow" if network_required else "default_allow",
            "allowed_hosts": [],
        },
        "mounts": [],
        "services": services,
        "secrets": secrets,
        "env": {},
        "volumes": [],
    }


def _state_schema(runtime_design: RuntimeDesignOutput, *, physical_namespace: str) -> dict[str, Any]:
    logical = runtime_design.state_namespaces
    if not logical:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
        }
    if len(logical) == 1 and logical[0].namespace == physical_namespace:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                key: _json_schema_for_value(value)
                for key, value in logical[0].initial_shape.items()
            },
            "additionalProperties": False,
            "description": logical[0].purpose,
        }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            item.namespace: {
                "type": "object",
                "properties": {
                    key: _json_schema_for_value(value)
                    for key, value in item.initial_shape.items()
                },
                "additionalProperties": False,
                "description": item.purpose,
            }
            for item in logical
        },
        "additionalProperties": False,
    }


def _state_initial(runtime_design: RuntimeDesignOutput, *, physical_namespace: str) -> dict[str, Any]:
    logical = runtime_design.state_namespaces
    if not logical:
        return {}
    if len(logical) == 1 and logical[0].namespace == physical_namespace:
        return dict(logical[0].initial_shape)
    return {item.namespace: dict(item.initial_shape) for item in logical}


def _json_schema_for_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "type": "object",
            "properties": {str(key): _json_schema_for_value(item) for key, item in value.items()},
            "additionalProperties": False,
        }
    if isinstance(value, list):
        item_schema = _json_schema_for_value(value[0]) if value else {}
        return {"type": "array", "items": item_schema}
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if value is None:
        return {"type": ["null", "string", "number", "boolean", "object", "array"]}
    return {"type": "string"}


def _package_node_manifest(node) -> dict[str, Any]:
    return {
        "version": "package_node.v0",
        "impl_id": node.impl_id,
        "node_type": "operational",
        "entrypoint": "node.py:run",
        "input_schema": node.input_schema,
        "output_schema": node.output_schema,
        "readable_sections": node.readable_sections,
        "writable_sections": node.writable_sections,
        "required_services": node.required_services,
        "tool_access": node.tool_access,
        "description": node.description,
    }


def _tool_spec(tool) -> ToolSpec:
    return ToolSpec(
        id=tool.tool_id,
        description=tool.description,
        entrypoint=f"tools/{tool.tool_id}/tool.py:run",
        input_schema=tool.input_schema,
        output_schema=tool.output_schema,
        resources=tool.resources,
        risk_level=tool.risk_level,
        risk_evaluator=ToolRiskEvaluatorConfig(),
        concurrent=tool.concurrent,
    )


def _write_json_file(
    *,
    temp_root: Path,
    relative_path: str,
    payload: dict[str, Any],
    generation_mode: str,
    source: str,
    materialized: list[PackageBuildMaterializedFile],
) -> None:
    content = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    _write_text_file(
        temp_root=temp_root,
        relative_path=relative_path,
        content=content,
        file_type="json",
        generation_mode=generation_mode,
        source=source,
        materialized=materialized,
    )


def _write_text_file(
    *,
    temp_root: Path,
    relative_path: str,
    content: str,
    file_type: str,
    generation_mode: str,
    source: str,
    materialized: list[PackageBuildMaterializedFile],
) -> None:
    target = _safe_target(temp_root, relative_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _record_file(
        temp_root=temp_root,
        target=target,
        file_type=file_type,
        generation_mode=generation_mode,
        source=source,
        materialized=materialized,
    )


def _record_file(
    *,
    temp_root: Path,
    target: Path,
    file_type: str,
    generation_mode: str,
    source: str,
    materialized: list[PackageBuildMaterializedFile],
) -> None:
    data = target.read_bytes()
    materialized.append(
        PackageBuildMaterializedFile(
            path=str(target.relative_to(temp_root)),
            file_type=file_type,  # type: ignore[arg-type]
            generation_mode=generation_mode,  # type: ignore[arg-type]
            source=source,
            bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )
    )


def _safe_target(root: Path, relative_path: str) -> Path:
    raw = str(relative_path).strip()
    if not raw:
        raise PackageBuildError("package file path must not be empty")
    path = Path(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PackageBuildError(f"unsafe package file path: {relative_path}")
    target = (root / path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise PackageBuildError(f"package file escapes package root: {relative_path}") from exc
    return target


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _default_prompt_template(product_brief: ProductBriefOutput, runtime_design: RuntimeDesignOutput) -> str:
    return "\n".join(
        [
            f"You are {product_brief.working_title or 'the generated Agent'}.",
            product_brief.agent_goal or runtime_design.graph_intent,
            "",
            f"Primary workflow: {product_brief.primary_workflow or runtime_design.graph_intent}",
            f"Autonomy boundary: {product_brief.autonomy_boundary or 'Use available tools only when useful.'}",
            f"Human review boundary: {product_brief.human_review_boundary or 'Ask for review when the action is risky or irreversible.'}",
            f"Resource boundary: {product_brief.resource_boundary or 'Use only configured runtime resources.'}",
            "Answer clearly and keep internal runtime details out of user-facing text.",
        ]
    ).strip()


def _safe_id(value: str) -> str:
    text = _SAFE_ID_PATTERN.sub("_", value.strip().lower()).strip("_-")
    if not text:
        text = "generated_agent"
    if text[0].isdigit():
        text = f"agent_{text}"
    return text[:64]


def _safe_file_id(value: str) -> str:
    return _safe_id(value.replace(".", "_"))


def _dedupe(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item).strip()
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _builtin_pattern_registry() -> PatternRegistry:
    builtins_dir = Path(__file__).resolve().parents[1] / "runtime_kernel" / "patterns" / "builtins"
    return PatternRegistry(builtins_dir=builtins_dir)
