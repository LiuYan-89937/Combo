from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from agent_factory.factory_graph.model_call import (
    FactoryModelCallError,
    call_structured_model,
    model_error_patch,
    prompt_values,
)
from agent_factory.factory_graph.schemas import (
    ResourceReactDecision,
    ResourceRequirement,
    ResourceRequirementSetOutput,
    ResourceUserInput,
    ResourceValidationResult,
)
from agent_factory.factory_graph.state import FactoryGraphState
from agent_factory.factory_graph.tool_approval import approve_tool_calls, route_after_tool_approval
from agent_factory.factory_graph.tools.filesystem import list_path, path_exists, read_file
from agent_factory.factory_graph.tools.search import search_files, search_text
from agent_factory.factory_graph.tools.shell import (
    current_working_directory,
    read_environment,
    run_command,
    which_command,
)
from agent_factory.models import get_main_model, get_main_model_settings
from agent_factory.prompts import PromptId, get_prompt, output_json_schema


RESOURCE_FILE_VERSION = "factory_resources.v0"
RESOURCE_ROOT = ".agentfactory/resources"
STAGE_ID = "resource_and_condition_planning"
RESOURCE_REACT_MODEL_NODE = "resource_react_model"
RESOURCE_TOOL_APPROVAL_NODE = "resource_tool_approval"
RESOURCE_TOOLS_NODE = "resource_tools"
RESOURCE_CHECK_TOOLS = [
    read_file,
    list_path,
    path_exists,
    search_files,
    search_text,
    read_environment,
    which_command,
    current_working_directory,
    run_command,
]


def build_resource_preparation_subgraph():
    graph = StateGraph(FactoryGraphState)
    graph.add_node("initialize_resource_context", _initialize_resource_context)
    graph.add_node("infer_resource_requirements", _infer_resource_requirements)
    graph.add_node(RESOURCE_REACT_MODEL_NODE, _resource_react_model)
    graph.add_node(RESOURCE_TOOL_APPROVAL_NODE, approve_tool_calls)
    graph.add_node(RESOURCE_TOOLS_NODE, ToolNode(RESOURCE_CHECK_TOOLS, name=RESOURCE_TOOLS_NODE))
    graph.add_node("parse_resource_react_output", _parse_resource_react_output)
    graph.add_node("interrupt_for_resource_input", _interrupt_for_resource_input)
    graph.add_node("merge_user_resource_input", _merge_user_resource_input)
    graph.add_node("validate_resource_values", _validate_resource_values)
    graph.add_node("write_resource_file", _write_resource_file)
    graph.add_edge(START, "initialize_resource_context")
    graph.add_edge("initialize_resource_context", "infer_resource_requirements")
    graph.add_conditional_edges(
        "infer_resource_requirements",
        _route_after_model_failure,
        {"continue": RESOURCE_REACT_MODEL_NODE, END: END},
    )
    graph.add_conditional_edges(
        RESOURCE_REACT_MODEL_NODE,
        _route_after_resource_model,
        {
            RESOURCE_TOOL_APPROVAL_NODE: RESOURCE_TOOL_APPROVAL_NODE,
            "parse_resource_react_output": "parse_resource_react_output",
            END: END,
        },
    )
    graph.add_conditional_edges(
        RESOURCE_TOOL_APPROVAL_NODE,
        _route_after_resource_tool_approval,
        {
            RESOURCE_TOOLS_NODE: RESOURCE_TOOLS_NODE,
            RESOURCE_REACT_MODEL_NODE: RESOURCE_REACT_MODEL_NODE,
        },
    )
    graph.add_edge(RESOURCE_TOOLS_NODE, RESOURCE_REACT_MODEL_NODE)
    graph.add_conditional_edges(
        "parse_resource_react_output",
        _route_after_react_decision,
        {
            RESOURCE_REACT_MODEL_NODE: RESOURCE_REACT_MODEL_NODE,
            "interrupt_for_resource_input": "interrupt_for_resource_input",
            "validate_resource_values": "validate_resource_values",
            END: END,
        },
    )
    graph.add_edge("interrupt_for_resource_input", "merge_user_resource_input")
    graph.add_edge("merge_user_resource_input", RESOURCE_REACT_MODEL_NODE)
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
    original_message_count = len(state.get("messages", []))
    final_state = build_resource_preparation_subgraph().invoke(state)
    return _delta_patch(
        final_state,
        original_stage_log_count=original_stage_log_count,
        original_message_count=original_message_count,
    )


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


def _resource_react_model(state: FactoryGraphState) -> dict[str, Any]:
    model = get_main_model()
    settings = get_main_model_settings()
    if model is None:
        return _fail("main model is not configured")
    plan = dict(state.get("resource_condition_plan") or {})
    try:
        prompt_value = get_prompt(PromptId.RESOURCE_REACT).invoke(
            prompt_values(
                STAGE_ID,
                {
                    "resource_requirements": _json_text(plan.get("requirements") or []),
                    "user_inputs": _json_text(plan.get("user_inputs") or []),
                    "resource_draft": _json_text(plan.get("resource_draft") or {}),
                    "tool_capability_plan": _json_text(state.get("tool_capability_plan") or {}),
                    "output_json_schema": output_json_schema(ResourceReactDecision),
                    "messages": _resource_react_messages(state),
                },
            )
        )
        bound_model = model.bind_tools(RESOURCE_CHECK_TOOLS).with_config(tags=["nostream"])
        if settings.max_tokens is not None:
            bound_model = bound_model.bind(max_tokens=settings.max_tokens)
        response = bound_model.invoke(prompt_value)
        if not isinstance(response, AIMessage):
            response = AIMessage(content=str(getattr(response, "content", response)))
        return {"messages": [response]}
    except Exception as exc:
        return _fail(f"{type(exc).__name__}: {exc}")


def _parse_resource_react_output(state: FactoryGraphState) -> dict[str, Any]:
    messages = state.get("messages") or []
    if not messages or not isinstance(messages[-1], AIMessage):
        return _fail("resource react model did not produce an AI message")
    try:
        decision = ResourceReactDecision.model_validate(_json_from_text(str(messages[-1].content or "")))
    except Exception as exc:
        return _fail(f"invalid resource react decision: {type(exc).__name__}: {exc}")
    plan = dict(state.get("resource_condition_plan") or {})
    check_results = _check_results_from_messages(messages, decision)
    return {
        "resource_condition_plan": {
            **plan,
            "react_decision": decision.model_dump(mode="json"),
            "requirements": [item.model_dump(mode="json") for item in decision.requirements] or list(plan.get("requirements") or []),
            "check_results": check_results,
            "resource_draft": decision.resource_draft,
            "status": _status_from_decision(decision),
        },
        **({"graph_control": {"action": "end"}} if decision.action in {"blocked", "failed"} else {}),
    }


def _interrupt_for_resource_input(state: FactoryGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    decision = dict(plan.get("react_decision") or {})
    answer = interrupt(
        {
            "type": "resource_input",
            "resource_file_path": plan.get("resource_file_path"),
            "requirements": _requirements_by_ids(plan, decision.get("missing_requirements") or []),
            "check_results": list(plan.get("check_results") or []),
            "readiness_analysis": {
                "resource_value_hints": {},
                "reasons": {},
                "user_prompt": decision.get("user_prompt") or "请直接输入缺失资源信息。",
            },
            "resource_draft": dict(plan.get("resource_draft") or {}),
            "message": decision.get("user_prompt") or "请直接输入缺失资源信息；也可以说明运行时提供或暂时阻塞。",
        }
    )
    return {"resource_condition_plan": {**plan, "resource_input_answer": answer}}


def _merge_user_resource_input(state: FactoryGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    answer = dict(plan.get("resource_input_answer") or {})
    input_text = str(answer.get("input_text") or "").strip()
    requirement_ids = answer.get("requirement_ids") or dict(plan.get("react_decision") or {}).get("missing_requirements") or []
    user_inputs = list(plan.get("user_inputs") or [])
    for requirement_id in requirement_ids:
        if input_text:
            user_inputs.append(
                ResourceUserInput(requirement_id=str(requirement_id), input_text=input_text).model_dump(mode="json")
            )
    return {
        "resource_condition_plan": {
            **plan,
            "status": "collecting",
            "user_inputs": user_inputs,
            "resource_input_answer": {},
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
    payload = {"version": RESOURCE_FILE_VERSION, "resources": dict(plan.get("resources") or {})}
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


def _route_after_model_failure(state: FactoryGraphState) -> str:
    if state.get("status") == "failed" or state.get("graph_control", {}).get("action") == "end":
        return END
    return "continue"


def _route_after_resource_model(state: FactoryGraphState) -> str:
    if state.get("status") == "failed" or state.get("graph_control", {}).get("action") == "end":
        return END
    messages = state.get("messages") or []
    if messages and getattr(messages[-1], "tool_calls", None):
        return RESOURCE_TOOL_APPROVAL_NODE
    return "parse_resource_react_output"


def _route_after_resource_tool_approval(state: FactoryGraphState) -> str:
    return route_after_tool_approval(
        state,
        approved=RESOURCE_TOOLS_NODE,
        denied=RESOURCE_REACT_MODEL_NODE,
    )


def _route_after_react_decision(state: FactoryGraphState) -> str:
    plan = state.get("resource_condition_plan") or {}
    status = plan.get("status")
    if status == "collecting":
        return RESOURCE_REACT_MODEL_NODE
    if status == "needs_input":
        return "interrupt_for_resource_input"
    if status == "resources_ready":
        return "validate_resource_values"
    return END


def _route_after_validation(state: FactoryGraphState) -> str:
    plan = state.get("resource_condition_plan") or {}
    status = plan.get("status")
    if status == "complete":
        return "write_resource_file"
    if status == "needs_input":
        return "interrupt_for_resource_input"
    return END


def _valid_requirements(requirements: list[ResourceRequirement], state: FactoryGraphState) -> list[ResourceRequirement]:
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


def _resource_react_messages(state: FactoryGraphState) -> list[Any]:
    messages = list(state.get("messages") or [])
    tail: list[Any] = []
    for message in reversed(messages):
        if isinstance(message, ToolMessage):
            tail.append(message)
            continue
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            tail.append(message)
            continue
        if len(tail) >= 12:
            break
    return list(reversed(tail))


def _check_results_from_messages(messages: list[Any], decision: ResourceReactDecision) -> list[dict[str, Any]]:
    by_tool_call_id = {
        str(item.get("tool_call_id") or item.get("action_id") or ""): dict(item)
        for item in decision.check_results_summary
        if isinstance(item, dict)
    }
    results: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        tool_call_id = str(getattr(message, "tool_call_id", "") or "")
        summary = by_tool_call_id.get(tool_call_id, {})
        results.append(
            {
                "action_id": tool_call_id,
                "requirement_id": str(summary.get("requirement_id") or ""),
                "tool_name": str(getattr(message, "name", "") or summary.get("tool_name") or ""),
                "status": str(summary.get("status") or "completed"),
                "result_summary": str(summary.get("result_summary") or _trim_text(str(message.content), 240)),
                "raw_result": {"content": str(message.content)},
            }
        )
    return results


def _validate_resource_draft(plan: dict[str, Any]) -> ResourceValidationResult:
    decision = ResourceReactDecision.model_validate(plan.get("react_decision") or {})
    if decision.action == "blocked":
        return ResourceValidationResult(status="blocked", invalid_resources={"resource": "blocked by react decision"})
    if decision.action == "failed":
        return ResourceValidationResult(status="failed", invalid_resources={"resource": "failed by react decision"})
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
    return ResourceValidationResult(status="complete", validated_resources=validated)


def _status_from_decision(decision: ResourceReactDecision) -> str:
    if decision.action == "continue_checking":
        return "collecting"
    if decision.action == "needs_user_input":
        return "needs_input"
    if decision.action == "resources_ready":
        return "resources_ready"
    return decision.action


def _requirements_by_ids(plan: dict[str, Any], requirement_ids: list[str]) -> list[dict[str, Any]]:
    wanted = set(requirement_ids)
    if not wanted:
        return list(plan.get("requirements") or [])
    return [
        item for item in plan.get("requirements", []) or []
        if str(item.get("requirement_id") or "") in wanted
    ]


def _json_from_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end >= start:
        stripped = stripped[start:end + 1]
    return json.loads(stripped)


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


def _has_resource_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, (list, tuple, dict, set)) and not value:
        return False
    return True


def _trim_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}..."


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _delta_patch(
    final_state: FactoryGraphState,
    *,
    original_stage_log_count: int,
    original_message_count: int,
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
    new_messages = list(final_state.get("messages", []))[original_message_count:]
    if new_messages:
        patch["messages"] = new_messages
    patch["stage_log"] = list(final_state.get("stage_log", []))[original_stage_log_count:]
    return patch
