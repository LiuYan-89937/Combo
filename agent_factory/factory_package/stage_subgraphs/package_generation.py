from __future__ import annotations

import ast
import json
import py_compile
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from pydantic import TypeAdapter

from agent_factory.assembly.schema import AgentAssemblySpec
from agent_factory.factory_package.model_call import (
    FactoryModelCallError,
    call_structured_model,
    model_error_patch,
    prompt_values,
)
from agent_factory.paths import factory_artifact_path
from agent_factory.factory_package.schemas import (
    PackageBuildDecision,
    PackageFileDraft,
    PackageMaterializedFile,
    PackageMaterializationFileSpec,
    PackageMaterializationPlan,
    PackageValidationReport,
)
from agent_factory.factory_package.state import FactoryPackageState
from agent_factory.models import get_main_model, get_main_model_settings
from agent_factory.prompts import PromptId, get_prompt, output_json_schema
from agent_factory.runtime_contracts.builtins import default_runtime_contract_registry
from agent_factory.runtime_contracts.schema import AgentPackageManifest
from agent_factory.runtime_render import RenderManifest, validate_render_manifest


STAGE_ID = "package_generation"
PACKAGE_ROOT = ".agentfactory/packages"
PACKAGE_REPORT_VERSION = "package_report.v0"
AGENT_PACKAGE_VERSION = "agent_package.v0"
PACKAGE_REACT_MODEL_NODE = "package_react_model"
PACKAGE_TOOLS_NODE = "package_tools"
MAX_PACKAGE_REVISION_ROUNDS = 3
PACKAGE_READ_TOOLS = []
REQUIRED_PACKAGE_FILES = {
    "agent_package.json",
    "assembly_spec.json",
    "resources.json",
    "sandbox_contract.json",
    "render_manifest.json",
    "package_report.json",
    "bindings/services.json",
    "bindings/node_bindings.json",
    "bindings/hooks.json",
    "contracts/artifact.json",
    "contracts/context.json",
    "contracts/dependencies.json",
    "contracts/knowledge.json",
    "contracts/model.json",
    "contracts/node_provider.json",
    "contracts/render.json",
    "contracts/resources.json",
    "contracts/sandbox.json",
    "contracts/scheduler.json",
    "contracts/session.json",
    "contracts/state.json",
    "contracts/tools.json",
    "contracts/trace.json",
}


def build_package_generation_subgraph():
    graph = StateGraph(FactoryPackageState)
    graph.add_node("initialize_package_context", _initialize_package_context)
    graph.add_node(PACKAGE_REACT_MODEL_NODE, _package_react_model)
    graph.add_node("emit_package_tool_events", _emit_package_tool_events)
    graph.add_node("finalize_package_build_decision", _finalize_package_build_decision)
    graph.add_node("validate_package_build_plan", _validate_package_build_plan)
    graph.add_node("materialize_package_files", _materialize_package_files)
    graph.add_node("validate_package_structure", _validate_package_structure)
    graph.add_node("publish_package_report", _publish_package_report)
    graph.add_edge(START, "initialize_package_context")
    graph.add_edge("initialize_package_context", PACKAGE_REACT_MODEL_NODE)
    graph.add_conditional_edges(
        PACKAGE_REACT_MODEL_NODE,
        _route_after_package_model,
        {"finalize_package_build_decision": "finalize_package_build_decision", END: END},
    )
    graph.add_conditional_edges(
        "finalize_package_build_decision",
        _route_after_package_decision,
        {
            "validate_package_build_plan": "validate_package_build_plan",
            END: END,
        },
    )
    graph.add_conditional_edges(
        "validate_package_build_plan",
        _route_after_build_plan_validation,
        {
            "materialize_package_files": "materialize_package_files",
            PACKAGE_REACT_MODEL_NODE: PACKAGE_REACT_MODEL_NODE,
            END: END,
        },
    )
    graph.add_edge("materialize_package_files", "validate_package_structure")
    graph.add_conditional_edges(
        "validate_package_structure",
        _route_after_package_validation,
        {
            "materialize_package_files": "materialize_package_files",
            "publish_package_report": "publish_package_report",
            END: END,
        },
    )
    graph.add_edge("publish_package_report", END)
    return graph.compile()


def run_package_generation_subgraph(state: FactoryPackageState) -> dict[str, Any]:
    original_stage_log_count = len(state.get("stage_log", []))
    working_state: FactoryPackageState = {**state, "messages": []}
    final_state = build_package_generation_subgraph().invoke(working_state)
    return _delta_patch(final_state, original_stage_log_count=original_stage_log_count)


def _initialize_package_context(state: FactoryPackageState) -> dict[str, Any]:
    factory_run_id = str(state.get("factory_run_id") or "default")
    materialization_plan = _materialization_plan(state, factory_run_id)
    package_root = Path(materialization_plan.package_root)
    return {
        "current_stage": STAGE_ID,
        "package_generation": {
            "status": "collecting",
            "package_root": str(package_root),
            "manifest_path": str(package_root / "agent_package.json"),
            "report_path": str(package_root / "package_report.json"),
            "materialized_files": [],
        },
    }


def _package_react_model(state: FactoryPackageState) -> dict[str, Any]:
    model = get_main_model()
    settings = get_main_model_settings()
    if model is None:
        return _fail("main model is not configured")
    plan = dict(state.get("package_generation") or {})
    revision_attempt = int(state.get("package_revision_attempt") or 0) + 1
    try:
        prompt_value = get_prompt(PromptId.PACKAGE_REACT).invoke(
            prompt_values(
                STAGE_ID,
                {
                    "assembly_spec": _json_text(state.get("assembly_spec") or {}),
                    "package_materialization_plan": _json_text(_materialization_plan(state).model_dump(mode="json")),
                    "resource_condition_plan": _json_text(state.get("resource_condition_plan") or {}),
                    "package_root": plan.get("package_root") or str(_package_root(str(state.get("factory_run_id") or "default"))),
                    "package_validation_observation": _json_text(state.get("package_validation_observation") or {}),
                    "messages": _complete_tool_blocks(state),
                },
            )
        )
        bound_model = model.bind_tools(PACKAGE_READ_TOOLS) if PACKAGE_READ_TOOLS else model
        if settings.max_tokens is not None:
            bound_model = bound_model.bind(max_tokens=settings.max_tokens)
        response = bound_model.invoke(prompt_value)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=str(getattr(response, "content", response)))
        return {"messages": [response], "package_revision_attempt": revision_attempt}
    except Exception as exc:
        return _fail(f"{type(exc).__name__}: {exc}")


def _finalize_package_build_decision(state: FactoryPackageState) -> dict[str, Any]:
    messages = state.get("messages") or []
    if not messages or not isinstance(messages[-1], AIMessage):
        return _fail("package react model did not produce an AI message")
    plan = dict(state.get("package_generation") or {})
    try:
        decision = call_structured_model(
            stage_id=STAGE_ID,
            prompt_id=PromptId.PACKAGE_BUILD_DECISION,
            output_model=PackageBuildDecision,
            values={
                "assembly_spec": _json_text(state.get("assembly_spec") or {}),
                "package_materialization_plan": _json_text(_materialization_plan(state).model_dump(mode="json")),
                "resource_condition_plan": _json_text(state.get("resource_condition_plan") or {}),
                "package_root": plan.get("package_root") or str(_package_root(str(state.get("factory_run_id") or "default"))),
                "package_validation_observation": _json_text(state.get("package_validation_observation") or {}),
                "tool_observations": _json_text(_tool_observations(messages)),
                "raw_model_output": str(messages[-1].content or ""),
                "output_json_schema": output_json_schema(PackageBuildDecision),
            },
        )
    except FactoryModelCallError as exc:
        return _fail(f"invalid package build decision: {exc}")
    if decision.action == "blocked":
        return _fail(decision.blocked_reason or "package build blocked")
    if decision.action == "failed":
        return _fail(decision.blocked_reason or "package build failed")
    return {
        "package_generation": {
            **plan,
            "status": "collecting",
            "build_decision": decision.model_dump(mode="json"),
        }
    }


def _validate_package_build_plan(state: FactoryPackageState) -> dict[str, Any]:
    plan = dict(state.get("package_generation") or {})
    decision = PackageBuildDecision.model_validate(plan.get("build_decision") or {})
    errors = _validate_decision(decision, state)
    report = PackageValidationReport(
        status="invalid" if errors else "valid",
        package_root=str(_package_root(str(state.get("factory_run_id") or "default"))),
        validation_errors=errors,
        static_checks=_static_checks_from_decision(decision, errors),
    )
    if errors:
        observation = {
            "attempt": int(state.get("package_revision_attempt") or 1),
            "status": "invalid",
            "errors": errors,
            "allowed_fix_scope": "Only modify generated_files declared as model_generated in package_materialization_plan.",
        }
        if int(state.get("package_revision_attempt") or 1) >= MAX_PACKAGE_REVISION_ROUNDS:
            return _package_failed(report, "package build plan validation failed")
        return {
            "package_generation": {
                **plan,
                "validation_report": report.model_dump(mode="json"),
            },
            "package_validation_observation": observation,
        }
    return {
        "package_generation": {
            **plan,
            "validation_report": report.model_dump(mode="json"),
        },
        "package_validation_observation": {},
    }


def _materialize_package_files(state: FactoryPackageState) -> dict[str, Any]:
    plan = dict(state.get("package_generation") or {})
    decision = PackageBuildDecision.model_validate(plan.get("build_decision") or {})
    materialization_plan = _materialization_plan(state)
    package_root = Path(materialization_plan.package_root)
    materialized: list[PackageMaterializedFile] = []
    package_root.mkdir(parents=True, exist_ok=True)
    try:
        files_to_write = _system_generated_files(state, materialization_plan) + list(decision.generated_files)
    except Exception as exc:
        report = PackageValidationReport(
            status="failed",
            package_root=str(package_root),
            validation_errors=[f"package system file generation failed: {type(exc).__name__}: {exc}"],
            static_checks=[{"check": "system_generated_files", "status": "failed"}],
        )
        return _package_failed(report, "package materialization failed")
    for draft in files_to_write:
        relative_path = _safe_relative_path(draft.path)
        target = package_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(draft.content, encoding="utf-8")
        materialized.append(
            PackageMaterializedFile(
                path=str(relative_path),
                file_type=draft.file_type,
                source_kind=draft.source_kind,
                source_id=draft.source_id,
                bytes=len(draft.content.encode("utf-8")),
            )
        )
    return {
        "package_generation": {
            **plan,
            "materialized_files": [item.model_dump(mode="json") for item in materialized],
        }
    }


def _validate_package_structure(state: FactoryPackageState) -> dict[str, Any]:
    plan = dict(state.get("package_generation") or {})
    package_root = _package_root(str(state.get("factory_run_id") or "default"))
    materialized = [
        PackageMaterializedFile.model_validate(item)
        for item in list(plan.get("materialized_files") or [])
    ]
    errors: list[str] = []
    static_checks: list[dict[str, object]] = []
    required_files = set(REQUIRED_PACKAGE_FILES)
    materialization_plan = _materialization_plan(state)
    if "memory" in materialization_plan.contracts:
        required_files.add("contracts/memory.json")
    for path in required_files:
        if not (package_root / path).is_file():
            errors.append(f"missing required package file: {path}")
    for item in materialized:
        target = package_root / item.path
        if item.file_type == "json":
            check = _validate_json_file(target)
        elif item.file_type == "python":
            check = _validate_python_file(target)
        else:
            check = {"path": item.path, "status": "ok", "check": f"{item.file_type}_exists"}
        static_checks.append(check)
        if check.get("status") != "ok":
            errors.append(str(check.get("message") or f"invalid file: {item.path}"))
    assembly_path = package_root / "assembly_spec.json"
    assembly_spec: AgentAssemblySpec | None = None
    if assembly_path.is_file():
        try:
            assembly_spec = AgentAssemblySpec.model_validate_json(assembly_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"assembly_spec.json invalid: {type(exc).__name__}: {exc}")
    render_manifest_path = package_root / "render_manifest.json"
    if render_manifest_path.is_file() and assembly_spec is not None:
        try:
            render_manifest = RenderManifest.model_validate_json(render_manifest_path.read_text(encoding="utf-8"))
            manifest_nodes = set(render_manifest.nodes)
            validate_render_manifest(render_manifest, manifest_nodes)
        except Exception as exc:
            errors.append(f"render_manifest.json invalid: {type(exc).__name__}: {exc}")
    manifest_path = package_root / "agent_package.json"
    if manifest_path.is_file():
        errors.extend(_validate_agent_package_manifest(package_root, manifest_path))
    report = PackageValidationReport(
        status="invalid" if errors else "valid",
        package_root=str(package_root),
        materialized_files=materialized,
        validation_errors=errors,
        static_checks=static_checks,
    )
    if errors:
        return _package_failed(report, "package structure validation failed")
    return {"package_generation": {**plan, "validation_report": report.model_dump(mode="json")}}


def _publish_package_report(state: FactoryPackageState) -> dict[str, Any]:
    plan = dict(state.get("package_generation") or {})
    report = PackageValidationReport.model_validate(plan.get("validation_report") or {})
    package_root = _package_root(str(state.get("factory_run_id") or "default"))
    report_path = package_root / "package_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "current_stage": STAGE_ID,
        "status": "running",
        "package_generation": {
            **plan,
            "status": "complete",
            "package_root": str(package_root),
            "manifest_path": str(package_root / "agent_package.json"),
            "report_path": str(report_path),
            "validation_report": report.model_dump(mode="json"),
        },
        "stage_log": [
            {
                "stage_id": STAGE_ID,
                "status": "complete",
                "message": "package_generation materialized validated AgentPackage draft.",
            }
        ],
    }


def _route_after_package_model(state: FactoryPackageState) -> str:
    if state.get("status") == "failed" or state.get("graph_control", {}).get("action") == "end":
        return END
    messages = state.get("messages") or []
    if PACKAGE_READ_TOOLS and messages and getattr(messages[-1], "tool_calls", None):
        return PACKAGE_TOOLS_NODE
    return "finalize_package_build_decision"


def _route_after_package_decision(state: FactoryPackageState) -> str:
    if state.get("status") == "failed" or state.get("graph_control", {}).get("action") == "end":
        return END
    return "validate_package_build_plan"


def _route_after_package_validation(state: FactoryPackageState) -> str:
    if state.get("status") == "failed" or state.get("graph_control", {}).get("action") == "end":
        return END
    report = dict(dict(state.get("package_generation") or {}).get("validation_report") or {})
    if report.get("status") == "valid":
        return "publish_package_report"
    return END


def _route_after_build_plan_validation(state: FactoryPackageState) -> str:
    if state.get("status") == "failed" or state.get("graph_control", {}).get("action") == "end":
        return END
    if state.get("package_validation_observation"):
        return PACKAGE_REACT_MODEL_NODE
    report = dict(dict(state.get("package_generation") or {}).get("validation_report") or {})
    if report.get("status") == "valid":
        return "materialize_package_files"
    return END


def _validate_decision(decision: PackageBuildDecision, state: FactoryPackageState) -> list[str]:
    errors: list[str] = []
    resource_keys = _resource_keys(state)
    materialization_plan = _materialization_plan(state)
    plan_files = {item.path: item for item in materialization_plan.files}
    model_generated_paths = {
        item.path for item in materialization_plan.files
        if item.generation_mode == "model_generated"
    }
    files_by_path: dict[str, PackageFileDraft] = {}
    for draft in decision.generated_files:
        try:
            relative_path = _safe_relative_path(draft.path)
        except ValueError as exc:
            errors.append(f"invalid package file path {draft.path!r}: {exc}")
            continue
        normalized = str(relative_path)
        if normalized in files_by_path:
            errors.append(f"duplicate package file path: {normalized}")
        files_by_path[normalized] = draft
        planned = plan_files.get(normalized)
        if planned is None:
            errors.append(f"generated file is not declared in package_materialization_plan: {normalized}")
            continue
        if planned.generation_mode != "model_generated":
            errors.append(f"generated file attempts to modify system-generated contract file: {normalized}")
        if draft.file_type != planned.file_type:
            errors.append(f"generated file type mismatch for {normalized}: expected {planned.file_type}")
        if draft.source_kind != planned.source_kind:
            errors.append(f"generated file source_kind mismatch for {normalized}: expected {planned.source_kind}")
        if draft.source_id != planned.source_id:
            errors.append(f"generated file source_id mismatch for {normalized}: expected {planned.source_id}")
        if draft.file_type == "json":
            errors.extend(_json_content_errors(normalized, draft.content))
        elif draft.file_type == "python":
            errors.extend(_python_content_errors(normalized, draft.content))
    missing = sorted(model_generated_paths - set(files_by_path))
    for path in missing:
        errors.append(f"missing required package file draft: {path}")
    for tool in materialization_plan.tools:
        for key in tool.manifest.resources.values():
            if key not in resource_keys:
                errors.append(f"tool manifest resource key not prepared by stage 6: {tool.tool_id}.{key}")
    forbidden_prefixes = (".agentfactory/resources/", ".agentfactory/assemblies/")
    for path in files_by_path:
        if path.startswith(forbidden_prefixes):
            errors.append(f"package generation cannot write outside package root: {path}")
    return errors


def _validate_agent_package_manifest(package_root: Path, manifest_path: Path) -> list[str]:
    errors: list[str] = []
    try:
        manifest = AgentPackageManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"agent_package.json invalid: {type(exc).__name__}: {exc}"]
    required_keys = [
        "assembly_spec_path",
        "resources_path",
        "render_manifest_path",
        "sandbox_contract_path",
    ]
    for key in required_keys:
        value = str(getattr(manifest, key) or "")
        if not value:
            errors.append(f"agent_package.json missing {key}")
            continue
        try:
            relative_path = _safe_relative_path(value)
        except ValueError as exc:
            errors.append(f"agent_package.json invalid {key}: {exc}")
            continue
        if not (package_root / relative_path).is_file():
            errors.append(f"agent_package.json references missing file: {value}")
    for key, value in manifest.contracts.items():
        try:
            relative_path = _safe_relative_path(str(value))
        except ValueError as exc:
            errors.append(f"agent_package.json invalid contracts.{key}: {exc}")
            continue
        target = package_root / relative_path
        if not target.is_file():
            errors.append(f"agent_package.json contracts.{key} references missing file")
            continue
        try:
            default_runtime_contract_registry().parse(TypeAdapter(dict[str, object]).validate_json(target.read_text(encoding="utf-8")))
        except Exception as exc:
            errors.append(f"agent_package.json contracts.{key} invalid: {type(exc).__name__}: {exc}")
    required_contracts = {
        "context",
        "dependencies",
        "knowledge",
        "model",
        "render",
        "resources",
        "sandbox",
        "scheduler",
        "session",
        "tools",
    }
    missing_contracts = sorted(required_contracts - set(manifest.contracts))
    for key in missing_contracts:
        errors.append(f"agent_package.json missing contracts.{key}")
    for key in ("services", "node_bindings", "hooks"):
        value = str(manifest.bindings.get(key) or "")
        if not value or not (package_root / _safe_relative_path(value)).is_file():
            errors.append(f"agent_package.json bindings.{key} references missing file")
    return errors


def _validate_json_file(target: Path) -> dict[str, object]:
    try:
        TypeAdapter(object).validate_json(target.read_text(encoding="utf-8"))
        return {"path": str(target), "status": "ok", "check": "json_parse"}
    except Exception as exc:
        return {"path": str(target), "status": "failed", "check": "json_parse", "message": f"{type(exc).__name__}: {exc}"}


def _validate_python_file(target: Path) -> dict[str, object]:
    try:
        py_compile.compile(str(target), doraise=True)
        return {"path": str(target), "status": "ok", "check": "python_compile"}
    except Exception as exc:
        return {"path": str(target), "status": "failed", "check": "python_compile", "message": f"{type(exc).__name__}: {exc}"}


def _json_content_errors(path: str, content: str) -> list[str]:
    try:
        TypeAdapter(object).validate_json(content)
    except Exception as exc:
        return [f"{path} JSON invalid: {type(exc).__name__}: {exc}"]
    return []


def _python_content_errors(path: str, content: str) -> list[str]:
    errors: list[str] = []
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        return [f"{path} Python syntax invalid: SyntaxError: {exc}"]
    if _is_tool_code_path(path):
        errors.extend(_tool_code_contract_errors(path, tree))
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8", delete=False) as handle:
            handle.write(content)
            temp_path = Path(handle.name)
        try:
            py_compile.compile(str(temp_path), doraise=True)
        finally:
            temp_path.unlink(missing_ok=True)
    except Exception as exc:
        errors.append(f"{path} Python syntax invalid: {type(exc).__name__}: {exc}")
    return errors


def _is_tool_code_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return len(parts) == 3 and parts[0] == "tools" and parts[2] == "tool.py"


def _tool_code_contract_errors(path: str, tree: ast.Module) -> list[str]:
    errors: list[str] = []
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for function_name in ("run", "evaluate_risk"):
        function = functions.get(function_name)
        if function is None:
            errors.append(f"{path} missing required function: {function_name}(arguments, resources/context)")
            continue
        positional = [arg.arg for arg in function.args.posonlyargs + function.args.args]
        expected_second = "context" if function_name == "evaluate_risk" else "resources"
        if positional[:2] != ["arguments", expected_second]:
            errors.append(f"{path} {function_name} first two parameters must be arguments, {expected_second}")
    return errors


def _static_checks_from_decision(decision: PackageBuildDecision, errors: list[str]) -> list[dict[str, object]]:
    return [
        {
            "check": "package_build_plan",
            "status": "failed" if errors else "ok",
            "generated_file_count": len(decision.generated_files),
        }
    ]


def _resource_keys(state: FactoryPackageState) -> set[str]:
    resource_plan = dict(state.get("resource_condition_plan") or {})
    resources = dict(resource_plan.get("resources") or {})
    return {str(key) for key in resources}


def _materialization_plan(state: FactoryPackageState, factory_run_id: str | None = None) -> PackageMaterializationPlan:
    raw = state.get("package_materialization_plan") or {}
    if raw:
        return PackageMaterializationPlan.model_validate(raw)
    run_id = factory_run_id or str(state.get("factory_run_id") or "default")
    return PackageMaterializationPlan(
        factory_run_id=run_id,
        package_root=str(_package_root(run_id)),
        files=[],
        tools=[],
        manifest_contract={},
    )


def _system_generated_files(
    state: FactoryPackageState,
    plan: PackageMaterializationPlan,
) -> list[PackageFileDraft]:
    assembly_spec = AgentAssemblySpec.model_validate(state.get("assembly_spec") or {})
    resource_plan = dict(state.get("resource_condition_plan") or {})
    resources_payload = {"version": "factory_resources.v0", "resources": dict(resource_plan.get("resources") or {})}
    sandbox_contract = dict(resource_plan.get("sandbox_contract") or {})
    by_path = {
        "agent_package.json": plan.manifest_contract,
        "assembly_spec.json": assembly_spec.model_dump(mode="json"),
        "resources.json": resources_payload,
        "sandbox_contract.json": {"version": "sandbox_contract.v0", **sandbox_contract},
        "render_manifest.json": state.get("render_manifest") or {},
        "package_report.json": {"version": "package_report.v0", "status": "valid"},
        "bindings/services.json": [item.model_dump(mode="json") for item in assembly_spec.bindings.services],
        "bindings/node_bindings.json": [item.model_dump(mode="json") for item in assembly_spec.bindings.node_bindings],
        "bindings/hooks.json": [item.model_dump(mode="json") for item in assembly_spec.bindings.hooks],
    }
    for contract_name, contract_payload in plan.contracts.items():
        by_path[f"contracts/{contract_name}.json"] = contract_payload
    for binding in assembly_spec.bindings.node_bindings:
        payload = binding.payload.model_dump(mode="json") if hasattr(binding.payload, "model_dump") else {}
        if binding.binding_type == "prompt":
            prompt_id = str(payload.get("prompt_id") or binding.binding_id)
            by_path[f"prompts/{prompt_id}.md"] = str(payload.get("template") or "")
        elif binding.binding_type == "policy_profile":
            profile_id = str(payload.get("profile_id") or binding.binding_id)
            by_path[f"policies/{profile_id}.json"] = payload
        elif binding.binding_type == "strategy_profile":
            by_path[f"strategies/{binding.target.node_id}.json"] = payload
        elif binding.binding_type == "output_formatter":
            formatter_id = str(payload.get("formatter_id") or binding.binding_id)
            by_path[f"formatters/{formatter_id}.json"] = payload
    for tool in plan.tools:
        by_path[tool.manifest_path] = tool.manifest.model_dump(mode="json")
    drafts: list[PackageFileDraft] = []
    for spec in plan.files:
        if spec.generation_mode != "system_generated":
            continue
        content = by_path.get(spec.path)
        if content is None:
            raise ValueError(f"missing system-generated content for {spec.path}")
        drafts.append(
            PackageFileDraft(
                path=spec.path,
                content=content if isinstance(content, str) else json.dumps(content, ensure_ascii=False, indent=2),
                file_type=spec.file_type,
                purpose=f"materialize {spec.contract_source}",
                source_kind=spec.source_kind,
                source_id=spec.source_id,
            )
        )
    return drafts


def _emit_package_tool_events(state: FactoryPackageState) -> dict[str, Any]:
    plan = dict(state.get("package_generation") or {})
    emitted_ids = set(str(item) for item in plan.get("_emitted_tool_event_ids", []) or [])
    new_events: list[dict[str, Any]] = []
    for message in state.get("messages", []) or []:
        if not isinstance(message, ToolMessage):
            continue
        tool_call_id = str(getattr(message, "tool_call_id", "") or "")
        if not tool_call_id or tool_call_id in emitted_ids:
            continue
        emitted_ids.add(tool_call_id)
        new_events.append(
            {
                "event_type": "tool_call_completed",
                "tool_call_id": tool_call_id,
                "tool_name": str(getattr(message, "name", "") or ""),
                "message": {
                    "type": "ToolMessage",
                    "name": str(getattr(message, "name", "") or ""),
                    "tool_call_id": tool_call_id,
                    "content": str(message.content),
                },
                "source": "package_react_internal",
            }
        )
    if new_events:
        _emit_tool_activity_events(new_events)
    return {"package_generation": {**plan, "_emitted_tool_event_ids": sorted(emitted_ids)}}


def _complete_tool_blocks(state: FactoryPackageState) -> list[Any]:
    messages = list(state.get("messages") or [])
    complete_blocks: list[list[Any]] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        tool_calls = getattr(message, "tool_calls", None) or []
        if not isinstance(message, AIMessage) or not tool_calls:
            index += 1
            continue
        wanted_ids = {str(tool_call.get("id") or "") for tool_call in tool_calls}
        found_ids: set[str] = set()
        block: list[Any] = [message]
        cursor = index + 1
        while cursor < len(messages) and found_ids != wanted_ids:
            candidate = messages[cursor]
            if isinstance(candidate, AIMessage) and getattr(candidate, "tool_calls", None):
                break
            if isinstance(candidate, ToolMessage):
                tool_call_id = str(getattr(candidate, "tool_call_id", "") or "")
                if tool_call_id in wanted_ids:
                    found_ids.add(tool_call_id)
                    block.append(candidate)
            cursor += 1
        if found_ids == wanted_ids:
            complete_blocks.append(block)
        index += 1
    selected: list[Any] = []
    for block in reversed(complete_blocks):
        if selected and len(selected) + len(block) > 12:
            break
        selected = block + selected
    return selected


def _tool_observations(messages: list[Any]) -> list[dict[str, str]]:
    observations: list[dict[str, str]] = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        observations.append(
            {
                "tool_call_id": str(getattr(message, "tool_call_id", "") or ""),
                "tool_name": str(getattr(message, "name", "") or ""),
                "content": _trim_text(str(message.content), 1200),
            }
        )
    return observations


def _package_failed(report: PackageValidationReport, message: str) -> dict[str, Any]:
    package_root = Path(report.package_root) if report.package_root else _package_root("default")
    report_path = package_root / "package_report.json"
    try:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass
    return {
        "current_stage": STAGE_ID,
        "status": "failed",
        "graph_control": {"action": "end"},
        "package_generation": {
            "status": "failed",
            "package_root": report.package_root,
            "report_path": str(report_path),
            "validation_report": report.model_dump(mode="json"),
        },
        "errors": [{"where": STAGE_ID, "message": f"{message}: {'; '.join(report.validation_errors)}"}],
        "stage_log": [{"stage_id": STAGE_ID, "status": "failed", "message": message}],
    }


def _fail(message: str) -> dict[str, Any]:
    return model_error_patch(STAGE_ID, message)


def _safe_relative_path(path: str) -> PurePosixPath:
    if not path or not path.strip():
        raise ValueError("path is empty")
    candidate = PurePosixPath(path)
    if candidate.is_absolute():
        raise ValueError("absolute paths are not allowed")
    if any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError("path traversal or empty path segments are not allowed")
    return candidate


def _package_root(factory_run_id: str) -> Path:
    return factory_artifact_path("packages", factory_run_id or "default")


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _trim_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}..."


def _delta_patch(final_state: FactoryPackageState, *, original_stage_log_count: int) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for key in ("current_stage", "status", "graph_control", "package_generation", "errors"):
        if key in final_state:
            patch[key] = _public_package_plan(final_state[key]) if key == "package_generation" else final_state[key]
    patch["stage_log"] = list(final_state.get("stage_log", []))[original_stage_log_count:]
    return patch


def _emit_tool_activity_events(events: list[dict[str, Any]]) -> None:
    try:
        writer = get_stream_writer()
        writer({"type": "tool_activity", "payload": {"events": events}})
    except Exception:
        return


def _public_package_plan(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    return {key: item for key, item in value.items() if not str(key).startswith("_")}
