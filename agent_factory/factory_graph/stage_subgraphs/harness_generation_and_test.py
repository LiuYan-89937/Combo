from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from agent_factory.factory_graph.model_call import (
    FactoryModelCallError,
    call_structured_model,
    prompt_values,
)
from agent_factory.factory_graph.sandbox_runtime import (
    SandboxRuntimeError,
    runtime_for_backend,
)
from agent_factory.factory_graph.schemas import (
    HarnessContractDecision,
    HarnessReportError,
    HarnessValidationReport,
    HostInteractionContract,
    RuntimeEnvironmentContract,
    SandboxDependencyPlan,
)
from agent_factory.factory_graph.state import FactoryGraphState
from agent_factory.models import get_main_model, get_main_model_settings
from agent_factory.prompts import PromptId, get_prompt, output_json_schema


STAGE_ID = "harness_generation_and_test"
HARNESS_ROOT = ".agentfactory/harness"
HARNESS_REPORT_VERSION = "harness_report.v0"
HARNESS_REACT_MODEL_NODE = "harness_react_model"
HARNESS_TOOL_APPROVAL_NODE = "harness_tool_approval"
HARNESS_TOOLS_NODE = "harness_tools"
MAX_HARNESS_REVISION_ROUNDS = 3
HARNESS_TOOLS = []


def build_harness_generation_and_test_subgraph():
    graph = StateGraph(FactoryGraphState)
    graph.add_node("initialize_harness_context", _initialize_harness_context)
    graph.add_node(HARNESS_REACT_MODEL_NODE, _harness_react_model)
    graph.add_node("emit_harness_tool_events", _emit_harness_tool_events)
    graph.add_node("finalize_harness_contracts", _finalize_harness_contracts)
    graph.add_node("validate_harness_contracts", _validate_harness_contracts)
    graph.add_node("prepare_sandbox_runtime", _prepare_sandbox_runtime)
    graph.add_node("execute_harness_plan", _execute_harness_plan)
    graph.add_node("validate_harness_results", _validate_harness_results)
    graph.add_node("publish_harness_report", _publish_harness_report)
    graph.add_edge(START, "initialize_harness_context")
    graph.add_edge("initialize_harness_context", HARNESS_REACT_MODEL_NODE)
    graph.add_conditional_edges(
        HARNESS_REACT_MODEL_NODE,
        _route_after_harness_model,
        {"finalize_harness_contracts": "finalize_harness_contracts", END: END},
    )
    graph.add_conditional_edges(
        "finalize_harness_contracts",
        _route_after_harness_decision,
        {"validate_harness_contracts": "validate_harness_contracts", "publish_harness_report": "publish_harness_report", END: END},
    )
    graph.add_conditional_edges(
        "validate_harness_contracts",
        _route_after_contract_validation,
        {
            "prepare_sandbox_runtime": "prepare_sandbox_runtime",
            HARNESS_REACT_MODEL_NODE: HARNESS_REACT_MODEL_NODE,
            "publish_harness_report": "publish_harness_report",
            END: END,
        },
    )
    graph.add_conditional_edges(
        "prepare_sandbox_runtime",
        _route_after_sandbox_prepare,
        {"execute_harness_plan": "execute_harness_plan", "publish_harness_report": "publish_harness_report"},
    )
    graph.add_edge("execute_harness_plan", "validate_harness_results")
    graph.add_conditional_edges(
        "validate_harness_results",
        _route_after_harness_results,
        {
            HARNESS_REACT_MODEL_NODE: HARNESS_REACT_MODEL_NODE,
            "publish_harness_report": "publish_harness_report",
        },
    )
    graph.add_edge("publish_harness_report", END)
    return graph.compile()


def run_harness_generation_and_test_subgraph(state: FactoryGraphState) -> dict[str, Any]:
    original_stage_log_count = len(state.get("stage_log", []))
    working_state: FactoryGraphState = {**state, "messages": []}
    final_state = build_harness_generation_and_test_subgraph().invoke(working_state)
    return _delta_patch(final_state, original_stage_log_count=original_stage_log_count)


def _initialize_harness_context(state: FactoryGraphState) -> dict[str, Any]:
    factory_run_id = str(state.get("factory_run_id") or "default")
    harness_root = _harness_root(factory_run_id)
    package_root = _package_root(state, factory_run_id)
    protected_ids = sorted(set(state.get("protected_tool_ids") or []) | set(get_factory_protected_tool_ids()))
    return {
        "current_stage": STAGE_ID,
        "protected_tool_ids": protected_ids,
        "harness_generation": {
            "status": "collecting",
            "harness_root": str(harness_root),
            "package_root": str(package_root),
            "report_path": str(harness_root / "harness_report.json"),
            "artifacts_root": str(harness_root / "artifacts"),
        },
    }


def _harness_react_model(state: FactoryGraphState) -> dict[str, Any]:
    model = get_main_model()
    settings = get_main_model_settings()
    if model is None:
        return _harness_failed("main model is not configured")
    harness = dict(state.get("harness_generation") or {})
    revision_attempt = int(state.get("harness_revision_attempt") or 0) + 1
    try:
        prompt_value = get_prompt(PromptId.HARNESS_REACT).invoke(
            prompt_values(
                STAGE_ID,
                {
                    "assembly_spec": _json_text(state.get("assembly_spec") or {}),
                    "package_materialization_plan": _json_text(state.get("package_materialization_plan") or {}),
                    "package_generation": _json_text(state.get("package_generation") or {}),
                    "resource_condition_plan": _json_text(state.get("resource_condition_plan") or {}),
                    "package_root": harness.get("package_root") or str(_package_root(state, str(state.get("factory_run_id") or "default"))),
                    "harness_validation_observation": _json_text(state.get("harness_validation_observation") or {}),
                    "sandbox_execution_observation": _json_text(harness.get("sandbox_execution_observation") or {}),
                    "messages": _complete_tool_blocks(state),
                },
            )
        )
        bound_model = model.bind_tools(HARNESS_TOOLS) if HARNESS_TOOLS else model
        if settings.max_tokens is not None:
            bound_model = bound_model.bind(max_tokens=settings.max_tokens)
        response = bound_model.invoke(prompt_value)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=str(getattr(response, "content", response)))
        return {"messages": [response], "harness_revision_attempt": revision_attempt}
    except Exception as exc:
        return _harness_failed(f"{type(exc).__name__}: {exc}")


def _finalize_harness_contracts(state: FactoryGraphState) -> dict[str, Any]:
    messages = state.get("messages") or []
    if not messages or not isinstance(messages[-1], AIMessage):
        return _harness_failed("harness react model did not produce an AI message")
    harness = dict(state.get("harness_generation") or {})
    try:
        decision = call_structured_model(
            stage_id=STAGE_ID,
            prompt_id=PromptId.HARNESS_CONTRACT_DECISION,
            output_model=HarnessContractDecision,
            values={
                "assembly_spec": _json_text(state.get("assembly_spec") or {}),
                "package_materialization_plan": _json_text(state.get("package_materialization_plan") or {}),
                "package_generation": _json_text(state.get("package_generation") or {}),
                "resource_condition_plan": _json_text(state.get("resource_condition_plan") or {}),
                "package_root": harness.get("package_root") or str(_package_root(state, str(state.get("factory_run_id") or "default"))),
                "tool_observations": _json_text(_tool_observations(messages)),
                "harness_validation_observation": _json_text(state.get("harness_validation_observation") or {}),
                "sandbox_execution_observation": _json_text(harness.get("sandbox_execution_observation") or {}),
                "raw_model_output": str(messages[-1].content or ""),
                "output_json_schema": output_json_schema(HarnessContractDecision),
            },
        )
    except FactoryModelCallError as exc:
        return _harness_failed(f"invalid harness contract decision: {exc}")
    if decision.action == "blocked":
        return _terminal_report_patch(state, "blocked", _error("harness.contract", "blocked", decision.blocked_reason or "Harness contract generation blocked."))
    if decision.action == "failed":
        return _terminal_report_patch(state, "failed", _error("harness.contract", "failed", decision.blocked_reason or "Harness contract generation failed."))
    return {
        "harness_generation": {
            **harness,
            "status": "collecting",
            "contract_decision": decision.model_dump(mode="json"),
        }
    }


def _validate_harness_contracts(state: FactoryGraphState) -> dict[str, Any]:
    harness = dict(state.get("harness_generation") or {})
    decision = HarnessContractDecision.model_validate(harness.get("contract_decision") or {})
    errors = _contract_errors(decision, state)
    if errors:
        observation = {
            "attempt": int(state.get("harness_revision_attempt") or 1),
            "status": "invalid",
            "errors": [item.model_dump(mode="json") for item in errors],
            "allowed_fix_scope": "Only fix runtime_environment, host_interaction, dependency_plan, and execution_plan contracts.",
        }
        if int(state.get("harness_revision_attempt") or 1) >= MAX_HARNESS_REVISION_ROUNDS:
            return _terminal_report_patch(state, "failed", *errors)
        return {
            "harness_generation": {
                **harness,
                "contract_validation": {"status": "invalid", "errors": [item.model_dump(mode="json") for item in errors]},
            },
            "harness_validation_observation": observation,
        }
    return {
        "harness_generation": {
            **harness,
            "contract_validation": {"status": "valid", "errors": []},
        },
        "harness_validation_observation": {},
    }


def _prepare_sandbox_runtime(state: FactoryGraphState) -> dict[str, Any]:
    harness = dict(state.get("harness_generation") or {})
    decision = HarnessContractDecision.model_validate(harness.get("contract_decision") or {})
    assert decision.runtime_environment and decision.host_interaction and decision.dependency_plan
    factory_run_id = str(state.get("factory_run_id") or "default")
    harness_root = _harness_root(factory_run_id)
    package_root = _package_root(state, factory_run_id)
    resources_path = _package_resources_path(package_root)
    artifacts_root = harness_root / "artifacts"
    _write_contract_files(
        harness_root=harness_root,
        runtime_environment=decision.runtime_environment,
        host_interaction=decision.host_interaction,
        dependency_plan=decision.dependency_plan,
        execution_plan=decision.execution_plan,
    )
    runtime = runtime_for_backend(decision.runtime_environment.backend)
    try:
        prepared = runtime.prepare(
            runtime_environment=decision.runtime_environment,
            host_interaction=decision.host_interaction,
            dependency_plan=decision.dependency_plan,
            package_root=package_root,
            resources_path=resources_path,
            artifacts_root=artifacts_root,
        )
    except SandboxRuntimeError as exc:
        return _terminal_report_patch(state, "blocked", exc.to_report_error())
    return {
        "harness_generation": {
            **harness,
            "prepared_sandbox": prepared.model_dump(mode="json"),
        }
    }


def _execute_harness_plan(state: FactoryGraphState) -> dict[str, Any]:
    harness = dict(state.get("harness_generation") or {})
    decision = HarnessContractDecision.model_validate(harness.get("contract_decision") or {})
    if not decision.runtime_environment or not decision.execution_plan:
        return _terminal_report_patch(state, "failed", _error("harness.execution", "missing_contract", "Missing runtime environment or execution plan."))
    runtime = runtime_for_backend(decision.runtime_environment.backend)
    try:
        prepared = runtime.prepare(
            runtime_environment=decision.runtime_environment,
            host_interaction=decision.host_interaction or HostInteractionContract(),
            dependency_plan=decision.dependency_plan or SandboxDependencyPlan(),
            package_root=_package_root(state, str(state.get("factory_run_id") or "default")),
            resources_path=_package_resources_path(_package_root(state, str(state.get("factory_run_id") or "default"))),
            artifacts_root=_harness_root(str(state.get("factory_run_id") or "default")) / "artifacts",
        )
        result = runtime.run(sandbox=prepared, plan=decision.execution_plan)
        artifacts = runtime.collect_artifacts(sandbox=prepared)
        runtime.cleanup(sandbox=prepared)
    except SandboxRuntimeError as exc:
        return _terminal_report_patch(state, "blocked", exc.to_report_error())
    return {
        "harness_generation": {
            **harness,
            "execution_result": result.model_dump(mode="json"),
            "artifact_manifest": [item.model_dump(mode="json") for item in artifacts],
        }
    }


def _validate_harness_results(state: FactoryGraphState) -> dict[str, Any]:
    harness = dict(state.get("harness_generation") or {})
    result = dict(harness.get("execution_result") or {})
    errors = [HarnessReportError.model_validate(item) for item in result.get("errors", [])]
    status = "passed" if result.get("status") == "passed" and not errors else "failed"
    report = _report_from_state(state, status=status, errors=errors)
    observation = _sandbox_execution_observation(state, report)
    if status == "failed" and _execution_can_revise(errors) and int(state.get("harness_revision_attempt") or 1) < MAX_HARNESS_REVISION_ROUNDS:
        return {
            "harness_generation": {
                **harness,
                "validation_report": report.model_dump(mode="json"),
                "sandbox_execution_observation": observation,
            },
            "harness_validation_observation": observation,
            "harness_report": {},
        }
    return {
        "harness_generation": {
            **harness,
            "validation_report": report.model_dump(mode="json"),
            "sandbox_execution_observation": observation,
        },
        "harness_report": report.model_dump(mode="json"),
    }


def _publish_harness_report(state: FactoryGraphState) -> dict[str, Any]:
    harness = dict(state.get("harness_generation") or {})
    report = HarnessValidationReport.model_validate(
        harness.get("validation_report") or state.get("harness_report") or _report_from_state(state, status="failed").model_dump(mode="json")
    )
    harness_root = _harness_root(str(state.get("factory_run_id") or "default"))
    report_path = harness_root / "harness_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")
    terminal = report.status in {"failed", "blocked"}
    return {
        "current_stage": STAGE_ID,
        "status": "failed" if terminal else "running",
        "graph_control": {"action": "end"} if terminal else {},
        "harness_generation": {
            **harness,
            "status": report.status,
            "report_path": str(report_path),
            "validation_report": report.model_dump(mode="json"),
        },
        "harness_report": report.model_dump(mode="json"),
        "errors": [item.model_dump(mode="json") for item in report.errors] if terminal else [],
        "stage_log": [
            {
                "stage_id": STAGE_ID,
                "status": report.status,
                "message": "harness_generation_and_test produced sandbox validation report.",
            }
        ],
    }


def _route_after_harness_model(state: FactoryGraphState) -> str:
    if state.get("status") == "failed" or state.get("graph_control", {}).get("action") == "end":
        return END
    messages = state.get("messages") or []
    if HARNESS_TOOLS and messages and getattr(messages[-1], "tool_calls", None):
        return HARNESS_TOOL_APPROVAL_NODE
    return "finalize_harness_contracts"


def _route_after_harness_decision(state: FactoryGraphState) -> str:
    if state.get("harness_report"):
        return "publish_harness_report"
    if state.get("status") == "failed" or state.get("graph_control", {}).get("action") == "end":
        return END
    return "validate_harness_contracts"


def _route_after_contract_validation(state: FactoryGraphState) -> str:
    if state.get("harness_report"):
        return "publish_harness_report"
    if state.get("status") == "failed" or state.get("graph_control", {}).get("action") == "end":
        return "publish_harness_report" if state.get("harness_report") else END
    if state.get("harness_validation_observation"):
        return HARNESS_REACT_MODEL_NODE
    validation = dict(dict(state.get("harness_generation") or {}).get("contract_validation") or {})
    if validation.get("status") == "valid":
        return "prepare_sandbox_runtime"
    return END


def _route_after_sandbox_prepare(state: FactoryGraphState) -> str:
    if state.get("harness_report"):
        return "publish_harness_report"
    return "execute_harness_plan"


def _route_after_harness_results(state: FactoryGraphState) -> str:
    if state.get("harness_report"):
        return "publish_harness_report"
    if state.get("harness_validation_observation"):
        return HARNESS_REACT_MODEL_NODE
    return "publish_harness_report"


def _contract_errors(decision: HarnessContractDecision, state: FactoryGraphState) -> list[HarnessReportError]:
    errors: list[HarnessReportError] = []
    if decision.runtime_environment is None:
        errors.append(_error("harness.contract", "missing_runtime_environment", "RuntimeEnvironmentContract is required."))
    if decision.host_interaction is None:
        errors.append(_error("harness.contract", "missing_host_interaction", "HostInteractionContract is required."))
    if decision.dependency_plan is None:
        errors.append(_error("harness.contract", "missing_dependency_plan", "SandboxDependencyPlan is required."))
    if decision.execution_plan is None:
        errors.append(_error("harness.contract", "missing_execution_plan", "HarnessExecutionPlan is required."))
    if errors:
        return errors
    assert decision.runtime_environment and decision.host_interaction
    package_root = _package_root(state, str(state.get("factory_run_id") or "default"))
    resources_path = _package_resources_path(package_root)
    resources = _resource_values(state)
    all_mounts = [*decision.host_interaction.mounts, *decision.host_interaction.volumes]
    errors.extend(_required_mount_errors(all_mounts, package_root=package_root, resources_path=resources_path))
    for mount in all_mounts:
        errors.extend(_mount_errors(mount, resources))
    services = decision.host_interaction.services
    dependency_plan = decision.dependency_plan or SandboxDependencyPlan()
    dependency_needs_network = bool(dependency_plan.python_requirements or dependency_plan.system_packages)
    if services and decision.runtime_environment.network_policy.mode != "declared_services":
        errors.append(_error("sandbox.network", "network_policy_invalid", "Declared services require network_policy.mode=declared_services."))
    if not services and not dependency_needs_network and decision.runtime_environment.network_policy.mode != "none":
        errors.append(_error("sandbox.network", "network_policy_invalid", "Network must default to none when no services or dependency installs are declared."))
    if dependency_needs_network and decision.runtime_environment.network_policy.mode == "declared_services" and not decision.runtime_environment.network_policy.allowed_hosts:
        errors.append(_error("sandbox.network", "network_policy_invalid", "Dependency installation with network access must declare allowed_hosts."))
    for service in services:
        endpoint = service.endpoint.strip().lower()
        if service.kind == "host_port" and (endpoint.startswith("localhost") or endpoint.startswith("127.0.0.1")):
            errors.append(_error("sandbox.service", "invalid_host_endpoint", "Host services must use host.docker.internal from inside Docker.", {"service_id": service.service_id}))
    forbidden_env = [key for key in decision.runtime_environment.env_policy.injected if _looks_like_factory_env(key)]
    if forbidden_env:
        errors.append(_error("sandbox.env", "factory_env_leak", "Factory model/runtime env vars cannot be injected into generated agent runtime.", {"keys": forbidden_env}))
    if decision.runtime_environment.backend != "docker":
        errors.append(_error("sandbox.backend", "backend_not_enabled", "Only docker backend is executable in this implementation; other backends must be explicit future work."))
    return errors


def _required_mount_errors(mounts: list[Any], *, package_root: Path, resources_path: Path) -> list[HarnessReportError]:
    required = {
        "/package": ("read_only", str(package_root)),
        "/resources": ("read_only", str(resources_path.parent)),
        "/artifacts": ("read_write", None),
        "/workdir": ("read_write", None),
    }
    errors: list[HarnessReportError] = []
    by_container = {mount.container_path: mount for mount in mounts}
    for container_path, (access, expected_host) in required.items():
        mount = by_container.get(container_path)
        if mount is None:
            errors.append(_error("sandbox.mount", "missing_required_mount", f"Missing required mount {container_path}."))
            continue
        if mount.access != access:
            errors.append(_error("sandbox.mount", "invalid_mount_access", f"{container_path} must be {access}."))
        if expected_host and Path(mount.host_path) != Path(expected_host):
            errors.append(_error("sandbox.mount", "invalid_mount_source", f"{container_path} must mount {expected_host}."))
    return errors


def _mount_errors(mount: Any, resources: dict[str, Any]) -> list[HarnessReportError]:
    errors: list[HarnessReportError] = []
    container_path = mount.container_path.strip()
    if not _allowed_container_path(container_path):
        errors.append(_error("sandbox.mount", "invalid_container_path", "Container path is outside the allowed sandbox namespace.", {"container_path": container_path}))
    host_path = Path(mount.host_path).expanduser()
    if mount.authorization_source != "system_required":
        if _dangerous_host_path(host_path):
            errors.append(_error("sandbox.mount", "invalid_mount", "Host path is too broad or unsafe to mount.", {"host_path": str(host_path)}))
        if mount.authorization_source == "resources" and mount.resource_id not in resources:
            errors.append(_error("sandbox.mount", "missing_resource_authorization", "Mount resource_id must exist in stage 6 resources or be explicitly user_authorized.", {"resource_id": mount.resource_id}))
        if not container_path.startswith(f"/volumes/{mount.resource_id}"):
            errors.append(_error("sandbox.mount", "invalid_volume_path", "Business host resources must be mounted under /volumes/<resource_id>.", {"container_path": container_path, "resource_id": mount.resource_id}))
    return errors


def _terminal_report_patch(state: FactoryGraphState, status: str, *errors: HarnessReportError) -> dict[str, Any]:
    report = _report_from_state(state, status=status, errors=list(errors))
    return {
        "harness_generation": {
            **dict(state.get("harness_generation") or {}),
            "status": status,
            "validation_report": report.model_dump(mode="json"),
        },
        "harness_report": report.model_dump(mode="json"),
    }


def _sandbox_execution_observation(state: FactoryGraphState, report: HarnessValidationReport) -> dict[str, Any]:
    return {
        "attempt": int(state.get("harness_revision_attempt") or 1),
        "status": report.status,
        "sandbox_backend": report.sandbox_backend,
        "errors": [item.model_dump(mode="json") for item in report.errors],
        "dependency_results": report.dependency_results,
        "tool_test_results": report.tool_test_results,
        "stdout_tail": report.stdout[-4000:],
        "stderr_tail": report.stderr[-4000:],
        "allowed_fix_scope": (
            "Only revise stage 9 contracts: runtime_environment, host_interaction, "
            "dependency_plan, and execution_plan. Do not modify AgentPackage/tool code."
        ),
    }


def _execution_can_revise(errors: list[HarnessReportError]) -> bool:
    fixable_reasons = {
        "dependency_missing",
        "dependency_failed",
        "system_dependency_install_failed",
        "python_dependency_install_failed",
        "invalid_resources",
        "invalid_plan",
    }
    return bool(errors) and all(error.why in fixable_reasons for error in errors)


def _report_from_state(
    state: FactoryGraphState,
    *,
    status: str,
    errors: list[HarnessReportError] | None = None,
) -> HarnessValidationReport:
    harness = dict(state.get("harness_generation") or {})
    decision_data = dict(harness.get("contract_decision") or {})
    backend = (decision_data.get("runtime_environment") or {}).get("backend") or "docker"
    result = dict(harness.get("execution_result") or {})
    return HarnessValidationReport(
        status=status,  # type: ignore[arg-type]
        factory_run_id=str(state.get("factory_run_id") or "default"),
        package_root=str(harness.get("package_root") or _package_root(state, str(state.get("factory_run_id") or "default"))),
        sandbox_backend=backend,
        contract_validation=dict(harness.get("contract_validation") or {}),
        dependency_results=list(result.get("dependency_results") or []),
        scenario_results=list(result.get("scenario_results") or []),
        tool_test_results=list(result.get("tool_test_results") or []),
        stdout=str(result.get("stdout") or ""),
        stderr=str(result.get("stderr") or ""),
        exit_code=result.get("exit_code"),
        artifact_manifest=list(harness.get("artifact_manifest") or []),
        errors=errors or [],
        repair_hints=_repair_hints(errors or []),
    )


def _write_contract_files(
    *,
    harness_root: Path,
    runtime_environment: RuntimeEnvironmentContract,
    host_interaction: HostInteractionContract,
    dependency_plan: SandboxDependencyPlan,
    execution_plan: Any,
) -> None:
    harness_root.mkdir(parents=True, exist_ok=True)
    (harness_root / "runtime_environment_contract.json").write_text(
        json.dumps(runtime_environment.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (harness_root / "host_interaction_contract.json").write_text(
        json.dumps(host_interaction.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (harness_root / "sandbox_dependency_plan.json").write_text(
        json.dumps(dependency_plan.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if execution_plan is not None:
        (harness_root / "harness_execution_plan.json").write_text(
            json.dumps(execution_plan.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _emit_harness_tool_events(state: FactoryGraphState) -> dict[str, Any]:
    harness = dict(state.get("harness_generation") or {})
    emitted_ids = set(str(item) for item in harness.get("_emitted_tool_event_ids", []) or [])
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
                "source": "harness_react_internal",
            }
        )
    if new_events:
        _emit_tool_activity_events(new_events)
    return {"harness_generation": {**harness, "_emitted_tool_event_ids": sorted(emitted_ids)}}


def _emit_tool_activity_events(events: list[dict[str, Any]]) -> None:
    try:
        writer = get_stream_writer()
    except Exception:
        return
    for event in events:
        writer({"harness_tool_event": event})


def _complete_tool_blocks(state: FactoryGraphState) -> list[Any]:
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
        if isinstance(message, ToolMessage):
            observations.append(
                {
                    "tool_name": str(getattr(message, "name", "") or ""),
                    "tool_call_id": str(getattr(message, "tool_call_id", "") or ""),
                    "content": str(message.content),
                }
            )
    return observations[-20:]


def _allowed_container_path(path: str) -> bool:
    return path in {"/package", "/resources", "/artifacts", "/workdir"} or path.startswith("/volumes/")


def _dangerous_host_path(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except Exception:
        resolved = path.absolute()
    dangerous = {Path("/").resolve(), Path("/Users").resolve(), Path.home().resolve(), Path.cwd().resolve()}
    return any(resolved == item for item in dangerous)


def _resource_values(state: FactoryGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    resources = dict(plan.get("resources") or {})
    if resources:
        return resources
    package_root = _package_root(state, str(state.get("factory_run_id") or "default"))
    resources_path = _package_resources_path(package_root)
    if resources_path.is_file():
        try:
            payload = json.loads(resources_path.read_text(encoding="utf-8"))
            return dict(payload.get("resources") or {})
        except Exception:
            return {}
    return {}


def _looks_like_factory_env(key: str) -> bool:
    upper = key.upper()
    return upper.startswith("AGENTFACTORY_") or upper in {"OPENAI_API_KEY", "OPENAI_BASE_URL", "MAIN_MODEL", "TASK_MODEL"}


def _package_root(state: FactoryGraphState, factory_run_id: str) -> Path:
    package = dict(state.get("package_generation") or {})
    root = package.get("package_root") or f".agentfactory/packages/{factory_run_id}"
    return Path(str(root))


def _package_resources_path(package_root: Path) -> Path:
    return package_root / "resources.json"


def _harness_root(factory_run_id: str) -> Path:
    return Path(HARNESS_ROOT) / factory_run_id


def _error(where: str, why: str, message: str, evidence: dict[str, Any] | None = None) -> HarnessReportError:
    return HarnessReportError(where=where, why=why, message=message, evidence=evidence or {})


def _repair_hints(errors: list[HarnessReportError]) -> list[str]:
    hints: list[str] = []
    for error in errors:
        if error.why == "docker_not_available":
            hints.append("Install Docker or choose an explicit local runtime backend after implementing it.")
        elif error.why == "invalid_mount":
            hints.append("Narrow host mounts to explicit resource paths and avoid broad host directories.")
        elif error.why == "invalid_host_endpoint":
            hints.append("Use host.docker.internal for host services accessed from Docker.")
        elif error.why in {"tool_failed", "tool_compile_failed"}:
            hints.append("Send package tool code and harness report to repair_or_finalize.")
        elif error.why in {"dependency_missing", "dependency_failed", "python_dependency_install_failed"}:
            hints.append("Revise SandboxDependencyPlan and rerun sandbox validation.")
    return list(dict.fromkeys(hints))[:16]


def _harness_failed(message: str) -> dict[str, Any]:
    return {
        "current_stage": STAGE_ID,
        "status": "failed",
        "graph_control": {"action": "end"},
        "errors": [{"where": STAGE_ID, "message": message}],
    }


def _delta_patch(final_state: FactoryGraphState, *, original_stage_log_count: int) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for key in (
        "current_stage",
        "status",
        "graph_control",
        "harness_generation",
        "harness_validation_observation",
        "harness_revision_attempt",
        "harness_report",
        "errors",
    ):
        if key in final_state:
            patch[key] = final_state[key]
    stage_log = list(final_state.get("stage_log") or [])
    patch["stage_log"] = stage_log[original_stage_log_count:]
    return patch


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _safe_relative_path(path: str) -> PurePosixPath:
    posix = PurePosixPath(path)
    if posix.is_absolute() or ".." in posix.parts:
        raise ValueError("path must be relative and stay inside package root")
    return posix
