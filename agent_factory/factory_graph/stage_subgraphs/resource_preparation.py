from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent_factory.factory_graph.model_call import (
    FactoryModelCallError,
    call_structured_model,
    model_error_patch,
)
from agent_factory.factory_graph.schemas import (
    ResourceCheckAction,
    ResourceCheckPlan,
    ResourceCheckPlanOutput,
    ResourceCheckResult,
    ResourceReadinessAnalysis,
    ResourceRequirement,
    ResourceRequirementSetOutput,
    ResourceRewriteOutput,
    ResourceUserInput,
    ResourceValidationResult,
)
from agent_factory.factory_graph.state import FactoryGraphState
from agent_factory.factory_graph.tools.filesystem import list_path, path_exists, read_file
from agent_factory.factory_graph.tools.search import search_files, search_text
from agent_factory.factory_graph.tools.shell import (
    current_working_directory,
    read_environment,
    run_command,
    which_command,
)
from agent_factory.prompts import PromptId, output_json_schema


RESOURCE_FILE_VERSION = "factory_resources.v0"
RESOURCE_ROOT = ".agentfactory/resources"
STAGE_ID = "resource_and_condition_planning"
ALLOWED_CHECK_TOOL_IDS: tuple[str, ...] = (
    "file_read",
    "file_list",
    "file_exists",
    "search_files",
    "search_text",
    "shell_env",
    "shell_which",
    "shell_cwd",
    "shell_run",
)


def build_resource_preparation_subgraph():
    graph = StateGraph(FactoryGraphState)
    graph.add_node("initialize_resource_context", _initialize_resource_context)
    graph.add_node("infer_resource_requirements", _infer_resource_requirements)
    graph.add_node("build_resource_check_plan", _build_resource_check_plan)
    graph.add_node("execute_resource_checks", _execute_resource_checks)
    graph.add_node("analyze_resource_readiness", _analyze_resource_readiness)
    graph.add_node("interrupt_for_resource_input", _interrupt_for_resource_input)
    graph.add_node("merge_user_resource_input", _merge_user_resource_input)
    graph.add_node("rewrite_resource_values", _rewrite_resource_values)
    graph.add_node("validate_resource_values", _validate_resource_values)
    graph.add_node("write_resource_file", _write_resource_file)
    graph.add_edge(START, "initialize_resource_context")
    graph.add_edge("initialize_resource_context", "infer_resource_requirements")
    graph.add_conditional_edges(
        "infer_resource_requirements",
        _route_after_model_node,
        {"continue": "build_resource_check_plan", END: END},
    )
    graph.add_conditional_edges(
        "build_resource_check_plan",
        _route_after_model_node,
        {"continue": "execute_resource_checks", END: END},
    )
    graph.add_edge("execute_resource_checks", "analyze_resource_readiness")
    graph.add_conditional_edges(
        "analyze_resource_readiness",
        _route_after_readiness,
        {
            "rewrite_resource_values": "rewrite_resource_values",
            "interrupt_for_resource_input": "interrupt_for_resource_input",
            END: END,
        },
    )
    graph.add_edge("interrupt_for_resource_input", "merge_user_resource_input")
    graph.add_edge("merge_user_resource_input", "rewrite_resource_values")
    graph.add_conditional_edges(
        "rewrite_resource_values",
        _route_after_model_node,
        {"continue": "validate_resource_values", END: END},
    )
    graph.add_conditional_edges(
        "validate_resource_values",
        _route_after_validation,
        {
            "write_resource_file": "write_resource_file",
            "interrupt_for_resource_input": "interrupt_for_resource_input",
            END: END,
        },
    )
    graph.add_edge("write_resource_file", END)
    return graph.compile()


def run_resource_preparation_subgraph(state: FactoryGraphState) -> dict[str, Any]:
    original_stage_log_count = len(state.get("stage_log", []))
    final_state = build_resource_preparation_subgraph().invoke(state)
    return _delta_patch(final_state, original_stage_log_count=original_stage_log_count)


def _initialize_resource_context(state: FactoryGraphState) -> dict[str, Any]:
    factory_run_id = str(state.get("factory_run_id") or "")
    plan = dict(state.get("resource_condition_plan") or {})
    return {
        "current_stage": STAGE_ID,
        "resource_condition_plan": {
            **plan,
            "status": str(plan.get("status") or "collecting"),
            "resource_file_path": str(_resource_file_path(factory_run_id)),
            "requirements": list(plan.get("requirements") or []),
            "check_plans": list(plan.get("check_plans") or []),
            "check_results": list(plan.get("check_results") or []),
            "user_inputs": list(plan.get("user_inputs") or []),
            "resource_draft": dict(plan.get("resource_draft") or {}),
            "resources": dict(plan.get("resources") or {}),
        },
    }


def _infer_resource_requirements(state: FactoryGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    if plan.get("requirements"):
        return {"resource_condition_plan": plan}
    try:
        result = call_structured_model(
            stage_id=STAGE_ID,
            prompt_id=PromptId.RESOURCE_REQUIREMENT_INFERENCE,
            output_model=ResourceRequirementSetOutput,
            values={
                "refined_plan_text": state.get("refined_plan_text") or "",
                "tool_capability_plan": _json_text(state.get("tool_capability_plan") or {}),
                "output_json_schema": output_json_schema(ResourceRequirementSetOutput),
            },
        )
    except FactoryModelCallError as exc:
        return _fail(str(exc))
    requirements = _valid_requirements(result.requirements, state)
    return {
        "resource_condition_plan": {
            **plan,
            "status": "collecting",
            "requirements": [item.model_dump(mode="json") for item in requirements],
            "requirement_assumptions": result.assumptions,
        }
    }


def _build_resource_check_plan(state: FactoryGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    if plan.get("check_plans"):
        return {"resource_condition_plan": plan}
    try:
        result = call_structured_model(
            stage_id=STAGE_ID,
            prompt_id=PromptId.RESOURCE_CHECK_PLAN,
            output_model=ResourceCheckPlanOutput,
            values={
                "resource_requirements": _json_text(plan.get("requirements") or []),
                "resource_draft": _json_text(plan.get("resource_draft") or {}),
                "allowed_check_tool_ids": _json_text(list(ALLOWED_CHECK_TOOL_IDS)),
                "output_json_schema": output_json_schema(ResourceCheckPlanOutput),
            },
        )
    except FactoryModelCallError as exc:
        return _fail(str(exc))
    plans = _valid_check_plans(result.plans, plan)
    return {
        "resource_condition_plan": {
            **plan,
            "check_plans": [item.model_dump(mode="json") for item in plans],
            "check_plan_assumptions": result.assumptions,
        }
    }


def _execute_resource_checks(state: FactoryGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    existing_action_ids = {
        str(item.get("action_id") or "")
        for item in plan.get("check_results", []) or []
    }
    results = list(plan.get("check_results") or [])
    for check_plan in plan.get("check_plans", []) or []:
        parsed_plan = ResourceCheckPlan.model_validate(check_plan)
        for action in parsed_plan.checks:
            if action.action_id in existing_action_ids:
                continue
            result = _execute_check_action(action)
            results.append(result.model_dump(mode="json"))
            existing_action_ids.add(action.action_id)
    return {
        "resource_condition_plan": {
            **plan,
            "check_results": results,
        }
    }


def _analyze_resource_readiness(state: FactoryGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    try:
        analysis = call_structured_model(
            stage_id=STAGE_ID,
            prompt_id=PromptId.RESOURCE_READINESS_ANALYSIS,
            output_model=ResourceReadinessAnalysis,
            values={
                "resource_requirements": _json_text(plan.get("requirements") or []),
                "check_results": _json_text(plan.get("check_results") or []),
                "resource_draft": _json_text(plan.get("resource_draft") or {}),
                "user_inputs": _json_text(plan.get("user_inputs") or []),
                "output_json_schema": output_json_schema(ResourceReadinessAnalysis),
            },
        )
    except FactoryModelCallError as exc:
        return _fail(str(exc))
    analysis = _valid_readiness_analysis(analysis, plan)
    status = _status_from_readiness(analysis)
    return {
        "resource_condition_plan": {
            **plan,
            "readiness_analysis": analysis.model_dump(mode="json"),
            "status": status,
        },
        **({"graph_control": {"action": "end"}} if status == "blocked" else {}),
    }


def _interrupt_for_resource_input(state: FactoryGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    answer = interrupt(
        {
            "type": "resource_input",
            "resource_file_path": plan.get("resource_file_path"),
            "requirements": _requirements_needing_input(plan),
            "check_results": list(plan.get("check_results") or []),
            "readiness_analysis": dict(plan.get("readiness_analysis") or {}),
            "resource_draft": dict(plan.get("resource_draft") or {}),
            "message": "请直接输入缺失资源信息；也可以说明运行时提供或暂时阻塞。",
        }
    )
    return {"resource_condition_plan": {**plan, "resource_input_answer": answer}}


def _merge_user_resource_input(state: FactoryGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    answer = dict(plan.get("resource_input_answer") or {})
    input_text = str(answer.get("input_text") or "").strip()
    requirement_ids = answer.get("requirement_ids") or _requirement_ids_needing_input(plan)
    user_inputs = list(plan.get("user_inputs") or [])
    for requirement_id in requirement_ids:
        if input_text:
            user_inputs.append(
                ResourceUserInput(
                    requirement_id=str(requirement_id),
                    input_text=input_text,
                ).model_dump(mode="json")
            )
    return {
        "resource_condition_plan": {
            **plan,
            "user_inputs": user_inputs,
            "resource_input_answer": {},
        }
    }


def _rewrite_resource_values(state: FactoryGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    try:
        rewrite = call_structured_model(
            stage_id=STAGE_ID,
            prompt_id=PromptId.RESOURCE_REWRITE,
            output_model=ResourceRewriteOutput,
            values={
                "resource_requirements": _json_text(plan.get("requirements") or []),
                "check_results": _json_text(plan.get("check_results") or []),
                "user_inputs": _json_text(plan.get("user_inputs") or []),
                "resource_draft": _json_text(plan.get("resource_draft") or {}),
                "tool_capability_plan": _json_text(state.get("tool_capability_plan") or {}),
                "output_json_schema": output_json_schema(ResourceRewriteOutput),
            },
        )
    except FactoryModelCallError as exc:
        return _fail(str(exc))
    rewrite = _valid_rewrite_output(rewrite, plan)
    return {
        "resource_condition_plan": {
            **plan,
            "resource_draft": rewrite.resources,
            "resource_rewrite": rewrite.model_dump(mode="json"),
        }
    }


def _validate_resource_values(state: FactoryGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    validation = _validate_resource_draft(plan)
    return {
        "resource_condition_plan": {
            **plan,
            "validation_result": validation.model_dump(mode="json"),
            "resources": validation.validated_resources if validation.status == "complete" else {},
            "status": validation.status,
        },
        **({"graph_control": {"action": "end"}} if validation.status in {"blocked", "failed"} else {}),
    }


def _write_resource_file(state: FactoryGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    resource_file_path = Path(str(plan.get("resource_file_path") or _resource_file_path(str(state.get("factory_run_id") or ""))))
    resource_file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": RESOURCE_FILE_VERSION,
        "resources": dict(plan.get("resources") or {}),
    }
    resource_file_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "current_stage": STAGE_ID,
        "status": "running",
        "resource_file_path": str(resource_file_path),
        "resource_condition_plan": {
            **plan,
            "status": "complete",
            "resource_file_path": str(resource_file_path),
        },
        "stage_log": [
            {
                "stage_id": STAGE_ID,
                "status": "complete",
                "message": "resource_and_condition_planning prepared verified resources file.",
            }
        ],
    }


def _route_after_model_node(state: FactoryGraphState) -> str:
    if state.get("status") == "failed" or state.get("graph_control", {}).get("action") == "end":
        return END
    return "continue"


def _route_after_readiness(state: FactoryGraphState) -> str:
    plan = state.get("resource_condition_plan") or {}
    if state.get("status") == "failed" or plan.get("status") in {"blocked", "failed"}:
        return END
    if plan.get("status") == "needs_input":
        return "interrupt_for_resource_input"
    return "rewrite_resource_values"


def _route_after_validation(state: FactoryGraphState) -> str:
    plan = state.get("resource_condition_plan") or {}
    status = plan.get("status")
    if status == "complete":
        return "write_resource_file"
    if status == "needs_input":
        return "interrupt_for_resource_input"
    return END


def _valid_requirements(
    requirements: list[ResourceRequirement],
    state: FactoryGraphState,
) -> list[ResourceRequirement]:
    capability_ids = _capability_ids(state)
    valid: list[ResourceRequirement] = []
    seen: set[str] = set()
    for item in requirements:
        requirement_id = item.requirement_id.strip()
        if not requirement_id or requirement_id in seen:
            continue
        used_by = [capability_id for capability_id in item.used_by_capability_ids if capability_id in capability_ids]
        if not used_by and item.used_by_capability_ids:
            continue
        seen.add(requirement_id)
        valid.append(item.model_copy(update={"requirement_id": requirement_id, "used_by_capability_ids": used_by}))
    return valid


def _valid_check_plans(plans: list[ResourceCheckPlan], plan_state: dict[str, Any]) -> list[ResourceCheckPlan]:
    requirement_ids = {str(item.get("requirement_id") or "") for item in plan_state.get("requirements", []) or []}
    valid_plans: list[ResourceCheckPlan] = []
    seen_actions: set[str] = set()
    for plan in plans:
        if plan.requirement_id not in requirement_ids:
            continue
        checks: list[ResourceCheckAction] = []
        for action in plan.checks:
            if action.requirement_id != plan.requirement_id:
                continue
            if action.tool_name not in ALLOWED_CHECK_TOOL_IDS:
                continue
            if action.action_id in seen_actions:
                continue
            seen_actions.add(action.action_id)
            checks.append(action)
        valid_plans.append(plan.model_copy(update={"checks": checks}))
    return valid_plans


def _valid_readiness_analysis(
    analysis: ResourceReadinessAnalysis,
    plan: dict[str, Any],
) -> ResourceReadinessAnalysis:
    requirement_ids = {str(item.get("requirement_id") or "") for item in plan.get("requirements", []) or []}
    return analysis.model_copy(
        update={
            "satisfied_requirements": _valid_ids(analysis.satisfied_requirements, requirement_ids),
            "missing_requirements": _valid_ids(analysis.missing_requirements, requirement_ids),
            "uncertain_requirements": _valid_ids(analysis.uncertain_requirements, requirement_ids),
            "blocked_requirements": _valid_ids(analysis.blocked_requirements, requirement_ids),
            "resource_value_hints": {
                key: value for key, value in analysis.resource_value_hints.items() if key in requirement_ids
            },
            "reasons": {key: value for key, value in analysis.reasons.items() if key in requirement_ids},
        }
    )


def _valid_rewrite_output(rewrite: ResourceRewriteOutput, plan: dict[str, Any]) -> ResourceRewriteOutput:
    requirement_ids = {str(item.get("requirement_id") or "") for item in plan.get("requirements", []) or []}
    resources = {
        key: value
        for key, value in rewrite.resources.items()
        if key in requirement_ids and _has_resource_value(value)
    }
    return rewrite.model_copy(
        update={
            "resources": resources,
            "unresolved_requirements": _valid_ids(rewrite.unresolved_requirements, requirement_ids),
            "runtime_provided_requirements": _valid_ids(rewrite.runtime_provided_requirements, requirement_ids),
            "blocked_requirements": _valid_ids(rewrite.blocked_requirements, requirement_ids),
        }
    )


def _execute_check_action(action: ResourceCheckAction) -> ResourceCheckResult:
    try:
        raw_result = _invoke_check_tool(action)
        return ResourceCheckResult(
            action_id=action.action_id,
            requirement_id=action.requirement_id,
            tool_name=action.tool_name,
            status="completed",
            result_summary=_summarize_tool_result(raw_result),
            raw_result=raw_result,
        )
    except Exception as exc:
        return ResourceCheckResult(
            action_id=action.action_id,
            requirement_id=action.requirement_id,
            tool_name=action.tool_name,
            status="error",
            result_summary=f"{type(exc).__name__}: {exc}",
            raw_result={"error": f"{type(exc).__name__}: {exc}"},
        )


def _invoke_check_tool(action: ResourceCheckAction) -> dict[str, Any]:
    args = dict(action.arguments)
    if action.tool_name == "file_read":
        return read_file.invoke(args)
    if action.tool_name == "file_list":
        return list_path.invoke(args)
    if action.tool_name == "file_exists":
        return path_exists.invoke(args)
    if action.tool_name == "search_files":
        return search_files.invoke(args)
    if action.tool_name == "search_text":
        return search_text.invoke(args)
    if action.tool_name == "shell_env":
        return read_environment.invoke({**args, "include_values": False})
    if action.tool_name == "shell_which":
        return which_command.invoke(args)
    if action.tool_name == "shell_cwd":
        return current_working_directory.invoke(args)
    if action.tool_name == "shell_run":
        return run_command.invoke({**args, "timeout_seconds": min(int(args.get("timeout_seconds") or 30), 30)})
    raise ValueError(f"unsupported check tool: {action.tool_name}")


def _validate_resource_draft(plan: dict[str, Any]) -> ResourceValidationResult:
    rewrite = dict(plan.get("resource_rewrite") or {})
    blocked = list(rewrite.get("blocked_requirements") or [])
    if blocked:
        return ResourceValidationResult(
            status="blocked",
            invalid_resources={str(item): "blocked by resource rewrite" for item in blocked},
        )
    requirements = [ResourceRequirement.model_validate(item) for item in plan.get("requirements", []) or []]
    resource_draft = dict(plan.get("resource_draft") or {})
    invalid: dict[str, str] = {}
    validated: dict[str, object] = {}
    for requirement in requirements:
        value = resource_draft.get(requirement.requirement_id)
        if requirement.required and not _has_resource_value(value):
            invalid[requirement.requirement_id] = "missing resource value"
            continue
        if _has_resource_value(value):
            validated[requirement.requirement_id] = value
    if invalid:
        return ResourceValidationResult(status="needs_input", validated_resources=validated, invalid_resources=invalid)
    return ResourceValidationResult(status="complete", validated_resources=validated, invalid_resources={})


def _status_from_readiness(analysis: ResourceReadinessAnalysis) -> str:
    if analysis.blocked_requirements:
        return "blocked"
    if analysis.missing_requirements or analysis.uncertain_requirements:
        return "needs_input"
    return "collecting"


def _requirements_needing_input(plan: dict[str, Any]) -> list[dict[str, Any]]:
    requirement_ids = set(_requirement_ids_needing_input(plan))
    return [
        item for item in plan.get("requirements", []) or []
        if str(item.get("requirement_id") or "") in requirement_ids
    ]


def _requirement_ids_needing_input(plan: dict[str, Any]) -> list[str]:
    analysis = dict(plan.get("readiness_analysis") or {})
    ids = [
        *list(analysis.get("missing_requirements") or []),
        *list(analysis.get("uncertain_requirements") or []),
    ]
    validation = dict(plan.get("validation_result") or {})
    ids.extend((validation.get("invalid_resources") or {}).keys())
    return _unique_strings(ids)


def _summarize_tool_result(result: dict[str, Any]) -> str:
    if "error" in result:
        return str(result.get("error"))[:240]
    for key in ("cwd", "path", "status", "exit_code"):
        if key in result and result.get(key) is not None:
            return f"{key}={result.get(key)}"
    for key in ("entries", "matches", "results"):
        value = result.get(key)
        if isinstance(value, list):
            suffix = " truncated" if result.get("truncated") else ""
            return f"{key}={len(value)}{suffix}"
    variables = result.get("variables")
    if isinstance(variables, dict):
        existing = [name for name, item in variables.items() if isinstance(item, dict) and item.get("exists")]
        return f"existing_env={', '.join(existing) if existing else '-'}"
    return str(result)[:240]


def _fail(message: str) -> dict[str, Any]:
    return model_error_patch(STAGE_ID, message)


def _capability_ids(state: FactoryGraphState) -> set[str]:
    tool_plan = dict(state.get("tool_capability_plan") or {})
    return {
        str(capability.get("capability_id") or "")
        for capability in tool_plan.get("tool_capabilities", []) or []
        if capability.get("capability_id")
    }


def _resource_file_path(factory_run_id: str) -> Path:
    return Path(RESOURCE_ROOT) / (factory_run_id or "default") / "factory_resources.json"


def _valid_ids(values: list[str], allowed: set[str]) -> list[str]:
    return [value for value in values if value in allowed]


def _unique_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _has_resource_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, (list, tuple, dict, set)) and not value:
        return False
    return True


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _delta_patch(
    final_state: FactoryGraphState,
    *,
    original_stage_log_count: int,
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    for key in (
        "current_stage",
        "status",
        "graph_control",
        "resource_condition_plan",
        "resource_file_path",
        "errors",
    ):
        if key in final_state:
            patch[key] = final_state[key]
    patch["stage_log"] = list(final_state.get("stage_log", []))[original_stage_log_count:]
    return patch
