"""Stage 6 resource and sandbox preparation subgraph."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from agent_factory.factory_graph.model_call import (
    FactoryModelCallError,
    STRUCTURED_OUTPUT_MAX_ATTEMPTS,
    call_structured_model,
    model_error_patch,
    prompt_values,
)
from agent_factory.factory_graph.schemas import (
    ResourcePreparationDecision,
    ResourcePreparationValidationResult,
    SandboxContract,
)
from agent_factory.factory_graph.state import FactoryGraphState
from agent_factory.models import get_main_model, get_main_model_settings
from agent_factory.paths import factory_artifact_path, project_root
from agent_factory.prompts import PromptId, output_json_schema
from agent_factory.tooling.langgraph_node import build_tool_node_runner
from agent_factory.tooling.registry import get_factory_tools, get_factory_tool_specs

STAGE_ID = "resource_and_condition_planning"

INITIALIZE_NODE = "initialize_resource_runtime_context"
RESOURCE_MODEL_NODE = "resource_react_model"
RESOURCE_TOOL_PROPOSAL_NODE = "emit_resource_tool_proposals"
RESOURCE_TOOLS_NODE = "factory_tool_node"
RESOURCE_TOOL_EVENT_NODE = "emit_resource_tool_events"
FINALIZE_NODE = "finalize_resource_preparation_decision"
VALIDATE_NODE = "validate_resource_and_sandbox_contract"
INTERRUPT_NODE = "interrupt_for_resource_input"
WRITE_NODE = "write_resource_outputs"
END_BLOCKED_NODE = "end_blocked"

RESOURCE_FILE_VERSION = "factory_resources.v0"
SANDBOX_CONTRACT_VERSION = "sandbox_contract.v0"
RESOURCE_REPORT_VERSION = "resource_preparation_report.v0"
DEFAULT_SANDBOX_IMAGE = "agentfactory-runtime-python:3.12"
RESOURCE_ALLOWED_TOOL_IDS = ("ls", "read", "glob", "grep", "bash", "bash_status", "bash_stop")
ALLOWED_CONTAINER_PREFIXES = ("/volumes", "/resources", "/package", "/artifacts", "/workdir")
MAX_RESOURCE_REVISION_ROUNDS = STRUCTURED_OUTPUT_MAX_ATTEMPTS


class ResourcePreparationGraphState(FactoryGraphState, total=False):
    """Internal state for the resource preparation subgraph."""

    messages: list[AnyMessage]
    resource_revision_attempt: int
    resource_validation_observation: dict[str, Any]


def run_resource_and_condition_planning_subgraph(state: FactoryGraphState) -> dict[str, Any]:
    """Run the Resource + Sandbox Preparation subgraph and return a stage patch."""

    graph = _build_graph()
    original_stage_log_count = len(state.get("stage_log") or [])
    working_state: ResourcePreparationGraphState = {
        **state,
        "messages": [],
        "resource_revision_attempt": int(state.get("resource_revision_attempt") or 0),
    }
    final_state = graph.invoke(working_state)
    return _delta_patch(final_state, original_stage_log_count=original_stage_log_count)


def _build_graph():
    builder: StateGraph[ResourcePreparationGraphState] = StateGraph(ResourcePreparationGraphState)
    builder.add_node(INITIALIZE_NODE, _initialize_resource_runtime_context)
    builder.add_node(RESOURCE_MODEL_NODE, _resource_react_model)
    builder.add_node(RESOURCE_TOOL_PROPOSAL_NODE, _emit_resource_tool_proposals)
    builder.add_node(
        RESOURCE_TOOLS_NODE,
        build_tool_node_runner(
            _resource_tools(),
            node_id=RESOURCE_TOOLS_NODE,
            name=RESOURCE_TOOLS_NODE,
        ),
    )
    builder.add_node(RESOURCE_TOOL_EVENT_NODE, _emit_resource_tool_events)
    builder.add_node(FINALIZE_NODE, _finalize_resource_preparation_decision)
    builder.add_node(VALIDATE_NODE, _validate_resource_and_sandbox_contract)
    builder.add_node(INTERRUPT_NODE, _interrupt_for_resource_input)
    builder.add_node(WRITE_NODE, _write_resource_outputs)
    builder.add_node(END_BLOCKED_NODE, _end_blocked)

    builder.add_edge(START, INITIALIZE_NODE)
    builder.add_edge(INITIALIZE_NODE, RESOURCE_MODEL_NODE)
    builder.add_conditional_edges(
        RESOURCE_MODEL_NODE,
        _route_after_resource_model,
        {
            RESOURCE_TOOL_PROPOSAL_NODE: RESOURCE_TOOL_PROPOSAL_NODE,
            FINALIZE_NODE: FINALIZE_NODE,
            END: END,
        },
    )
    builder.add_edge(RESOURCE_TOOL_PROPOSAL_NODE, RESOURCE_TOOLS_NODE)
    builder.add_edge(RESOURCE_TOOLS_NODE, RESOURCE_TOOL_EVENT_NODE)
    builder.add_edge(RESOURCE_TOOL_EVENT_NODE, RESOURCE_MODEL_NODE)
    builder.add_edge(FINALIZE_NODE, VALIDATE_NODE)
    builder.add_conditional_edges(
        VALIDATE_NODE,
        _route_after_validation,
        {
            RESOURCE_MODEL_NODE: RESOURCE_MODEL_NODE,
            INTERRUPT_NODE: INTERRUPT_NODE,
            WRITE_NODE: WRITE_NODE,
            END_BLOCKED_NODE: END_BLOCKED_NODE,
        },
    )
    builder.add_edge(INTERRUPT_NODE, RESOURCE_MODEL_NODE)
    builder.add_edge(WRITE_NODE, END)
    builder.add_edge(END_BLOCKED_NODE, END)
    return builder.compile()


def _resource_tools():
    return get_factory_tools(tool_ids=RESOURCE_ALLOWED_TOOL_IDS)


def _initialize_resource_runtime_context(state: ResourcePreparationGraphState) -> dict[str, Any]:
    paths = _resource_paths(state)
    existing = dict(state.get("resource_condition_plan") or {})
    plan = {
        "status": existing.get("status") or "collecting",
        "requirements": existing.get("requirements") or [],
        "check_results": existing.get("check_results") or [],
        "user_inputs": existing.get("user_inputs") or [],
        "resource_draft": existing.get("resource_draft") or {},
        "resources": existing.get("resources") or {},
        "sandbox_contract": existing.get("sandbox_contract") or _default_sandbox_contract(),
        "resource_file_path": paths["resource_file_path"],
        "sandbox_contract_path": paths["sandbox_contract_path"],
        "report_path": paths["report_path"],
    }
    return {
        "current_stage": STAGE_ID,
        "resource_file_path": paths["resource_file_path"],
        "sandbox_contract_path": paths["sandbox_contract_path"],
        "resource_preparation_report_path": paths["report_path"],
        "resource_condition_plan": plan,
    }


def _resource_react_model(state: ResourcePreparationGraphState) -> dict[str, Any]:
    model = get_main_model()
    if model is None:
        return _resource_failed_patch("main model is not configured")

    attempt = int(state.get("resource_revision_attempt") or 0) + 1
    if attempt > MAX_RESOURCE_REVISION_ROUNDS:
        return _resource_failed_patch("resource preparation exceeded maximum revision rounds")

    settings = get_main_model_settings()
    bound_model = model.bind_tools(_resource_tools())
    if settings.max_tokens is not None:
        bound_model = bound_model.bind(max_tokens=settings.max_tokens)
    prompt = _resource_react_messages(state)
    try:
        response = bound_model.invoke(
            prompt,
            config={"tags": [STAGE_ID], "metadata": {"stage_id": STAGE_ID}},
        )
    except Exception as exc:
        return model_error_patch(
            STAGE_ID,
            exc,
            message="resource preparation model call failed",
        ) | {
            "current_stage": STAGE_ID,
            "resource_revision_attempt": attempt,
            "resource_condition_plan": _merge_plan(
                state,
                status="failed",
                validation_result={"status": "failed", "errors": [str(exc)], "repair_hints": []},
            ),
            "graph_control": {"action": "end"},
        }

    if not isinstance(response, AIMessage):
        return _resource_failed_patch("resource preparation model did not return an AIMessage")

    return {
        "messages": [response],
        "resource_revision_attempt": attempt,
    }


def _route_after_resource_model(state: ResourcePreparationGraphState) -> str:
    if (state.get("graph_control") or {}).get("action") == "end":
        return END
    message = _last_ai_message(state.get("messages") or [])
    if message is not None and getattr(message, "tool_calls", None):
        return RESOURCE_TOOL_PROPOSAL_NODE
    return FINALIZE_NODE


def _emit_resource_tool_proposals(state: ResourcePreparationGraphState) -> dict[str, Any]:
    message = _last_ai_message(state.get("messages") or [])
    if message is None:
        return {}
    events = []
    for call in getattr(message, "tool_calls", None) or []:
        tool_name = str(call.get("name") or "")
        call_id = str(call.get("id") or "")
        args = call.get("args") if isinstance(call.get("args"), dict) else {}
        events.append(
            {
                "event_type": "tool_call_proposed",
                "node_id": STAGE_ID,
                "stage_id": STAGE_ID,
                "tool_id": tool_name,
                "tool_call_id": call_id,
                "status": "proposed",
                "arguments": args,
                "message": _argument_summary(args),
            }
        )
    _emit_custom_events(events)
    return {}


def _emit_resource_tool_events(state: ResourcePreparationGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    emitted = set(plan.get("_emitted_tool_event_ids") or [])
    events = []
    check_results = list(plan.get("check_results") or [])
    for message in state.get("messages") or []:
        if not isinstance(message, ToolMessage):
            continue
        call_id = str(message.tool_call_id or "")
        if call_id in emitted:
            continue
        tool_id = str(message.name or "")
        result = _coerce_json(message.content)
        summary = _tool_result_summary(result)
        result_record = {
            "tool_call_id": call_id,
            "tool_id": tool_id,
            "status": "completed",
            "result_summary": summary,
            "raw_result": result,
        }
        check_results.append(result_record)
        for event_type in ("tool_call_completed", "tool_observation_available"):
            events.append(
                {
                    "event_type": event_type,
                    "node_id": STAGE_ID,
                    "stage_id": STAGE_ID,
                    "tool_id": tool_id,
                    "tool_call_id": call_id,
                    "status": "completed",
                    "output": result,
                    "observation": result_record,
                    "message": summary,
                }
            )
        emitted.add(call_id)
    _emit_custom_events(events)
    plan["check_results"] = check_results
    plan["_emitted_tool_event_ids"] = sorted(emitted)
    return {"resource_condition_plan": plan}


def _finalize_resource_preparation_decision(state: ResourcePreparationGraphState) -> dict[str, Any]:
    message = _last_ai_message(state.get("messages") or [])
    if message is None:
        return _resource_failed_patch("resource preparation model produced no final answer")

    try:
        decision = call_structured_model(
            stage_id=STAGE_ID,
            prompt_id=PromptId.RESOURCE_PREPARATION_DECISION,
            output_model=ResourcePreparationDecision,
            values={
                "model_output": _message_text(message),
                "tool_observations": _tool_observations(state.get("messages") or []),
                "resource_condition_plan": state.get("resource_condition_plan") or {},
                "resource_user_inputs": (state.get("resource_condition_plan") or {}).get("user_inputs") or [],
                "output_json_schema": output_json_schema(ResourcePreparationDecision),
            },
        )
    except FactoryModelCallError as exc:
        return model_error_patch(STAGE_ID, exc, message="resource preparation decision failed") | {
            "resource_condition_plan": _merge_plan(
                state,
                status="failed",
                validation_result={"status": "failed", "errors": [str(exc)], "repair_hints": []},
            ),
            "graph_control": {"action": "end"},
        }

    decision_dict = decision.model_dump(mode="json")
    return {
        "resource_condition_plan": _merge_plan(
            state,
            status="collecting",
            requirements=decision_dict.get("requirements") or [],
            resource_draft=decision_dict.get("resource_draft") or {},
            sandbox_contract=decision_dict.get("sandbox_contract_draft") or {},
            preparation_decision=decision_dict,
        )
    }


def _validate_resource_and_sandbox_contract(state: ResourcePreparationGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    decision_data = plan.get("preparation_decision") or {}
    action = str(decision_data.get("action") or "")

    if action == "continue_checking":
        observation = {
            "status": "collecting",
            "message": "Continue checking requested by resource preparation decision.",
            "check_summary": decision_data.get("check_summary") or [],
        }
        return {
            "resource_validation_observation": observation,
            "resource_condition_plan": _merge_plan(
                state,
                status="collecting",
                validation_result={"status": "collecting", "errors": [], "repair_hints": []},
            ),
        }

    if action == "needs_user_input":
        validation = ResourcePreparationValidationResult(
            status="needs_input",
            validated_resources={},
            validated_sandbox_contract=None,
            errors=[],
            repair_hints=[],
        ).model_dump(mode="json")
        return {"resource_condition_plan": _merge_plan(state, status="collecting", validation_result=validation)}

    if action in {"blocked", "failed"}:
        status = "blocked" if action == "blocked" else "failed"
        message = decision_data.get("user_prompt") or f"resource preparation {status}"
        validation = ResourcePreparationValidationResult(
            status=status,
            validated_resources={},
            validated_sandbox_contract=None,
            errors=[str(message)],
            repair_hints=[],
        ).model_dump(mode="json")
        return {
            "resource_condition_plan": _merge_plan(state, status=status, validation_result=validation),
            "graph_control": {"action": "end"},
            "errors": _append_error(state, where=STAGE_ID, message=str(message)),
        }

    if action != "ready_for_validation":
        return _resource_failed_patch(f"unknown resource preparation action: {action}")

    validation = _validate_ready_decision(
        resource_draft=decision_data.get("resource_draft") or {},
        sandbox_contract_draft=decision_data.get("sandbox_contract_draft") or {},
        project_root=project_root(),
    )
    validation_dict = validation.model_dump(mode="json")
    if validation.status == "complete":
        return {
            "resource_condition_plan": _merge_plan(
                state,
                status="complete",
                resources=validation_dict.get("validated_resources") or {},
                sandbox_contract=validation_dict.get("validated_sandbox_contract") or {},
                validation_result=validation_dict,
            )
        }

    if validation.status == "blocked":
        return {
            "resource_condition_plan": _merge_plan(state, status="blocked", validation_result=validation_dict),
            "graph_control": {"action": "end"},
            "errors": _append_error(state, where=STAGE_ID, message="resource preparation blocked"),
        }

    if validation.status == "failed":
        return {
            "resource_condition_plan": _merge_plan(state, status="failed", validation_result=validation_dict),
            "graph_control": {"action": "end"},
            "errors": _append_error(state, where=STAGE_ID, message="resource preparation validation failed"),
        }

    if int(state.get("resource_revision_attempt") or 0) >= MAX_RESOURCE_REVISION_ROUNDS:
        failed = ResourcePreparationValidationResult(
            status="failed",
            validated_resources={},
            validated_sandbox_contract=None,
            errors=validation.errors + ["resource preparation exceeded maximum revision rounds"],
            repair_hints=validation.repair_hints,
        ).model_dump(mode="json")
        return {
            "resource_condition_plan": _merge_plan(state, status="failed", validation_result=failed),
            "graph_control": {"action": "end"},
            "errors": _append_error(state, where=STAGE_ID, message="resource preparation exceeded maximum revision rounds"),
        }

    return {
        "resource_validation_observation": validation_dict,
        "resource_condition_plan": _merge_plan(state, status="collecting", validation_result=validation_dict),
    }


def _route_after_validation(state: ResourcePreparationGraphState) -> str:
    plan = state.get("resource_condition_plan") or {}
    validation = plan.get("validation_result") or {}
    status = validation.get("status") or plan.get("status")
    if status == "complete":
        return WRITE_NODE
    if status == "needs_input":
        return INTERRUPT_NODE
    if status in {"blocked", "failed"}:
        return END_BLOCKED_NODE
    return RESOURCE_MODEL_NODE


def _interrupt_for_resource_input(state: ResourcePreparationGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    decision = plan.get("preparation_decision") or {}
    payload = {
        "type": "resource_input",
        "stage_id": STAGE_ID,
        "message": decision.get("user_prompt") or "请补充缺失资源、宿主机资源授权或 sandbox 访问说明。",
        "missing_requirements": decision.get("missing_requirements") or [],
        "check_summary": decision.get("check_summary") or [],
        "resource_draft": decision.get("resource_draft") or plan.get("resource_draft") or {},
        "sandbox_contract_draft": decision.get("sandbox_contract_draft") or plan.get("sandbox_contract") or {},
    }
    user_answer = interrupt(payload)
    input_text = _resource_input_text(user_answer)
    user_inputs = list(plan.get("user_inputs") or [])
    if input_text:
        user_inputs.append({"input_text": input_text})
    plan["user_inputs"] = user_inputs
    plan["status"] = "collecting"
    plan.pop("validation_result", None)
    return {
        "resource_condition_plan": plan,
        "resource_validation_observation": {},
    }


def _write_resource_outputs(state: ResourcePreparationGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    paths = _resource_paths(state)
    resource_path = Path(paths["resource_file_path"])
    sandbox_path = Path(paths["sandbox_contract_path"])
    report_path = Path(paths["report_path"])
    resource_path.parent.mkdir(parents=True, exist_ok=True)

    resources = dict(plan.get("resources") or {})
    sandbox_contract = dict(plan.get("sandbox_contract") or {})
    report = {
        "version": RESOURCE_REPORT_VERSION,
        "status": "complete",
        "requirements": plan.get("requirements") or [],
        "check_results": plan.get("check_results") or [],
        "user_inputs": plan.get("user_inputs") or [],
        "resource_draft": plan.get("resource_draft") or {},
        "resources": resources,
        "sandbox_contract": sandbox_contract,
        "validation_result": plan.get("validation_result") or {},
        "resource_file_path": paths["resource_file_path"],
        "sandbox_contract_path": paths["sandbox_contract_path"],
    }
    _write_json(resource_path, {"version": RESOURCE_FILE_VERSION, "resources": resources})
    _write_json(sandbox_path, {"version": SANDBOX_CONTRACT_VERSION, **sandbox_contract})
    _write_json(report_path, report)

    stage_log = list(state.get("stage_log") or [])
    stage_log.append(
        {
            "stage_id": STAGE_ID,
            "status": "complete",
            "message": "resource_and_condition_planning prepared verified sandbox resources.",
        }
    )
    return {
        "current_stage": STAGE_ID,
        "resource_file_path": paths["resource_file_path"],
        "sandbox_contract_path": paths["sandbox_contract_path"],
        "resource_preparation_report_path": paths["report_path"],
        "resource_condition_plan": {
            **plan,
            "status": "complete",
            "resources": resources,
            "sandbox_contract": sandbox_contract,
            "resource_file_path": paths["resource_file_path"],
            "sandbox_contract_path": paths["sandbox_contract_path"],
            "report_path": paths["report_path"],
        },
        "stage_log": stage_log,
    }


def _end_blocked(state: ResourcePreparationGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    status = str(plan.get("status") or "failed")
    paths = _resource_paths(state)
    report_path = Path(paths["report_path"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "version": RESOURCE_REPORT_VERSION,
        "status": status,
        "requirements": plan.get("requirements") or [],
        "check_results": plan.get("check_results") or [],
        "user_inputs": plan.get("user_inputs") or [],
        "resource_draft": plan.get("resource_draft") or {},
        "sandbox_contract": plan.get("sandbox_contract") or {},
        "validation_result": plan.get("validation_result") or {},
    }
    _write_json(report_path, report)
    stage_log = list(state.get("stage_log") or [])
    stage_log.append(
        {
            "stage_id": STAGE_ID,
            "status": status,
            "message": f"resource_and_condition_planning {status}.",
        }
    )
    return {
        "current_stage": STAGE_ID,
        "status": status,
        "graph_control": {"action": "end"},
        "resource_condition_plan": {**plan, "status": status, "report_path": paths["report_path"]},
        "resource_preparation_report_path": paths["report_path"],
        "stage_log": stage_log,
    }


def _validate_ready_decision(
    *,
    resource_draft: dict[str, Any],
    sandbox_contract_draft: dict[str, Any],
    project_root: Path,
) -> ResourcePreparationValidationResult:
    errors: list[str] = []
    hints: list[str] = []
    blocked_errors: list[str] = []

    try:
        contract = SandboxContract.model_validate(sandbox_contract_draft or _default_sandbox_contract())
    except Exception as exc:
        return ResourcePreparationValidationResult(
            status="needs_input",
            validated_resources={},
            validated_sandbox_contract=None,
            errors=[f"invalid sandbox contract: {exc}"],
            repair_hints=["Rewrite sandbox_contract_draft to match SandboxContract."],
        )

    if contract.backend != "docker":
        errors.append("sandbox backend must be docker")
        hints.append("Use Docker as the sandbox backend for this stage.")

    if contract.workdir != "/workdir":
        errors.append("sandbox workdir must be /workdir")
        hints.append("Set workdir to /workdir.")

    blocked_errors.extend(_docker_blocking_errors(contract.image))
    if not blocked_errors:
        image_error = _docker_image_error(contract.image)
        if image_error:
            errors.append(image_error)
            hints.append("Use an already available Docker image or ask the user to prepare the image.")

    errors.extend(_resource_value_errors(resource_draft))
    errors.extend(_sandbox_contract_static_errors(contract, project_root=project_root))

    if blocked_errors:
        return ResourcePreparationValidationResult(
            status="blocked",
            validated_resources={},
            validated_sandbox_contract=contract.model_dump(mode="json"),
            errors=blocked_errors,
            repair_hints=["Install/start Docker or make the Docker daemon available, then rerun this stage."],
        )

    if errors:
        return ResourcePreparationValidationResult(
            status="needs_input",
            validated_resources={},
            validated_sandbox_contract=contract.model_dump(mode="json"),
            errors=errors,
            repair_hints=hints,
        )

    return ResourcePreparationValidationResult(
        status="complete",
        validated_resources=resource_draft,
        validated_sandbox_contract=contract.model_dump(mode="json"),
        errors=[],
        repair_hints=[],
    )


def _docker_blocking_errors(image: str) -> list[str]:
    if not shutil.which("docker"):
        return ["docker_not_available: Docker CLI was not found"]
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except Exception as exc:
        return [f"docker_daemon_unavailable: {exc}"]
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        return [f"docker_daemon_unavailable: {message}"]
    return []


def _docker_image_error(image: str) -> str | None:
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except Exception as exc:
        return f"docker_image_unavailable: {exc}"
    if result.returncode == 0:
        return None
    message = (result.stderr or result.stdout or "").strip()
    return f"docker_image_unavailable: image {image!r} is not available locally. {message}"


def _resource_value_errors(resources: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for path, value in _flatten_values(resources):
        if isinstance(value, str):
            stripped = value.strip()
            if _contains_host_loopback(stripped):
                errors.append(f"resource {path} uses host loopback endpoint; convert it to sandbox endpoint")
            if _looks_like_disallowed_host_path(stripped):
                errors.append(f"resource {path} contains a host absolute path; convert it to a sandbox path")
    return errors


def _sandbox_contract_static_errors(contract: SandboxContract, *, project_root: Path) -> list[str]:
    errors: list[str] = []
    if contract.services and contract.network_policy.mode == "none":
        errors.append("sandbox network_policy.mode cannot be none when services are declared")
    for mount in contract.mounts:
        if not _allowed_container_path(mount.container_path):
            errors.append(f"mount {mount.resource_id} container_path must be under allowed sandbox prefixes")
        host_error = _host_path_error(mount.host_path, project_root=project_root)
        if host_error:
            errors.append(f"mount {mount.resource_id} {host_error}")
    for volume in contract.volumes:
        if not _allowed_container_path(volume.container_path):
            errors.append(f"volume {volume.resource_id} container_path must be under allowed sandbox prefixes")
        host_error = _host_path_error(volume.host_path, project_root=project_root)
        if host_error:
            errors.append(f"volume {volume.resource_id} {host_error}")
    for service in contract.services:
        if _contains_host_loopback(service.endpoint):
            errors.append(f"service {service.service_id} endpoint must use sandbox-accessible host endpoint")
    return errors


def _resource_react_messages(state: ResourcePreparationGraphState) -> list[AnyMessage]:
    prompt_value = get_prompt(PromptId.RESOURCE_REACT).invoke(
        prompt_values(
            STAGE_ID,
            {
                "requirement_brief": state.get("requirement_brief") or {},
                "refined_plan_text": state.get("refined_plan_text") or "",
                "graph_behavior_plan": state.get("graph_behavior_plan") or {},
                "node_strategy_plan": state.get("node_strategy_plan") or {},
                "tool_capability_plan": state.get("tool_capability_plan") or {},
                "resource_condition_plan": state.get("resource_condition_plan") or {},
                "resource_validation_observation": state.get("resource_validation_observation") or {},
                "resource_user_inputs": (state.get("resource_condition_plan") or {}).get("user_inputs") or [],
                "allowed_tools": [
                    spec.model_dump(mode="json") for spec in get_factory_tool_specs(tool_ids=RESOURCE_ALLOWED_TOOL_IDS)
                ],
                "messages": _complete_tool_blocks(state.get("messages") or []),
            },
        ),
    )
    return prompt_value.to_messages()


def _complete_tool_blocks(messages: list[AnyMessage]) -> list[AnyMessage]:
    complete: list[AnyMessage] = []
    pending_ids: set[str] = set()
    for message in messages:
        if isinstance(message, AIMessage):
            tool_calls = getattr(message, "tool_calls", None) or []
            ids = {str(call.get("id") or "") for call in tool_calls if call.get("id")}
            if ids:
                pending_ids.update(ids)
                complete.append(message)
            else:
                complete.append(message)
            continue
        if isinstance(message, ToolMessage):
            call_id = str(message.tool_call_id or "")
            if call_id in pending_ids:
                pending_ids.discard(call_id)
                complete.append(message)
            continue
        complete.append(message)
    if pending_ids:
        filtered: list[AnyMessage] = []
        for message in complete:
            if isinstance(message, AIMessage):
                ids = {str(call.get("id") or "") for call in getattr(message, "tool_calls", None) or []}
                if ids & pending_ids:
                    continue
            filtered.append(message)
        return filtered
    return complete


def _merge_plan(state: ResourcePreparationGraphState, **updates: Any) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    plan.update({key: value for key, value in updates.items() if value is not None})
    return plan


def _resource_failed_patch(message: str) -> dict[str, Any]:
    return {
        "current_stage": STAGE_ID,
        "status": "failed",
        "graph_control": {"action": "end"},
        "resource_condition_plan": {
            "status": "failed",
            "requirements": [],
            "check_results": [],
            "user_inputs": [],
            "resource_draft": {},
            "resources": {},
            "sandbox_contract": {},
            "validation_result": {"status": "failed", "errors": [message], "repair_hints": []},
        },
        "errors": [{"where": STAGE_ID, "message": message}],
    }


def _delta_patch(state: ResourcePreparationGraphState, *, original_stage_log_count: int) -> dict[str, Any]:
    keys = (
        "current_stage",
        "status",
        "graph_control",
        "resource_file_path",
        "sandbox_contract_path",
        "resource_preparation_report_path",
        "resource_condition_plan",
        "resource_revision_attempt",
        "resource_validation_observation",
        "errors",
    )
    patch = {key: state[key] for key in keys if key in state}
    stage_log = list(state.get("stage_log") or [])
    if len(stage_log) > original_stage_log_count:
        patch["stage_log"] = stage_log[original_stage_log_count:]
    return patch


def _resource_paths(state: ResourcePreparationGraphState | FactoryGraphState) -> dict[str, str]:
    run_id = str(state.get("factory_run_id") or "default")
    base = factory_artifact_path("resources", run_id)
    return {
        "resource_file_path": str(base / "factory_resources.json"),
        "sandbox_contract_path": str(base / "sandbox_contract.json"),
        "report_path": str(base / "resource_preparation_report.json"),
    }


def _default_sandbox_contract() -> dict[str, Any]:
    return {
        "backend": "docker",
        "image": DEFAULT_SANDBOX_IMAGE,
        "workdir": "/workdir",
        "network_policy": {"mode": "default_allow"},
        "mounts": [],
        "services": [],
        "secrets": [],
        "env": {},
        "volumes": [],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _last_ai_message(messages: list[AnyMessage]) -> AIMessage | None:
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            return message
    return None


def _message_text(message: AIMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def _tool_observations(messages: list[AnyMessage]) -> list[dict[str, Any]]:
    observations = []
    for message in messages:
        if isinstance(message, ToolMessage):
            observations.append(
                {
                    "tool_call_id": message.tool_call_id,
                    "tool_id": message.name,
                    "result": _coerce_json(message.content),
                }
            )
    return observations


def _coerce_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.JSONDecoder().decode(value)
    except Exception:
        return value


def _tool_result_summary(value: Any) -> str:
    if isinstance(value, dict):
        if "status" in value:
            return str(value.get("status"))
        return _argument_summary(value)
    if isinstance(value, list):
        return f"{len(value)} item(s)"
    return str(value)[:240]


def _argument_summary(arguments: dict[str, Any]) -> str:
    text = json.dumps(arguments, ensure_ascii=False)
    return text if len(text) <= 240 else text[:237] + "..."


def _resource_input_text(answer: Any) -> str:
    if isinstance(answer, Command):
        answer = answer.resume
    if isinstance(answer, dict):
        for key in ("input_text", "text", "message", "value"):
            value = answer.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return json.dumps(answer, ensure_ascii=False)
    if isinstance(answer, str):
        return answer.strip()
    return ""


def _append_error(state: ResourcePreparationGraphState, *, where: str, message: str) -> list[dict[str, Any]]:
    errors = list(state.get("errors") or [])
    errors.append({"where": where, "message": message})
    return errors


def _emit_custom_events(events: list[dict[str, Any]]) -> None:
    if not events:
        return
    try:
        from langgraph.config import get_stream_writer

        writer = get_stream_writer()
    except Exception:
        return
    writer({"type": "tool_activity", "payload": {"events": events}})


def _flatten_values(value: Any, prefix: str = "$"):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield from _flatten_values(nested, f"{prefix}.{key}")
        return
    if isinstance(value, list):
        for index, nested in enumerate(value):
            yield from _flatten_values(nested, f"{prefix}[{index}]")
        return
    yield prefix, value


def _contains_host_loopback(value: str) -> bool:
    lowered = value.lower()
    return "127.0.0.1" in lowered or "localhost" in lowered


def _looks_like_disallowed_host_path(value: str) -> bool:
    if not value.startswith("/"):
        return False
    return not _allowed_container_path(value)


def _allowed_container_path(path: str) -> bool:
    if not path.startswith("/"):
        return False
    pure = PurePosixPath(path)
    normalized = "/" + "/".join(part for part in pure.parts if part not in {"/", "."})
    return normalized in ALLOWED_CONTAINER_PREFIXES or any(
        normalized.startswith(prefix + "/") for prefix in ALLOWED_CONTAINER_PREFIXES
    )


def _host_path_error(path: str, *, project_root: Path) -> str | None:
    if not path:
        return "host_path is required"
    try:
        resolved = Path(path).expanduser().resolve()
    except Exception as exc:
        return f"host_path cannot be resolved: {exc}"
    home = Path.home().resolve()
    dangerous = {Path("/").resolve(), home, project_root.resolve()}
    if resolved in dangerous:
        return f"host_path {resolved} is too broad"
    if str(resolved) == "/Users":
        return "host_path /Users is too broad"
    if not resolved.exists():
        return f"host_path {resolved} does not exist"
    return None
