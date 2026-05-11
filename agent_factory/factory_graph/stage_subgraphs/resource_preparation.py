from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent_factory.factory_graph.schemas import (
    RequiredResourceKey,
    RequiredResourceKeySetOutput,
    ResourceCompletionAnswer,
    ResourceNormalizationOutput,
    ResourceProbePlanOutput,
    ResourceProbeRequest,
)
from agent_factory.factory_graph.state import FactoryGraphState
from agent_factory.factory_graph.tools.filesystem import list_path, path_exists, read_file
from agent_factory.factory_graph.tools.search import search_files, search_text
from agent_factory.factory_graph.tools.shell import current_working_directory, read_environment, which_command
from agent_factory.models import get_main_model, get_main_model_settings
from agent_factory.prompts import PromptId, get_prompt, output_json_schema


ALLOWED_PROBE_TOOL_IDS: tuple[str, ...] = (
    "file_read",
    "file_list",
    "file_exists",
    "search_files",
    "search_text",
    "shell_env",
    "shell_which",
    "shell_cwd",
)
RESOURCE_FILE_VERSION = "factory_resources.v0"
RESOURCE_ROOT = ".agentfactory/resources"


def build_resource_preparation_subgraph():
    graph = StateGraph(FactoryGraphState)
    graph.add_node("initialize_resource_context", _initialize_resource_context)
    graph.add_node("infer_required_resource_keys", _infer_required_resource_keys)
    graph.add_node("probe_resource_values", _probe_resource_values)
    graph.add_node("collect_probe_results", _collect_probe_results)
    graph.add_node("normalize_resource_values", _normalize_resource_values)
    graph.add_node("interrupt_for_missing_resources", _interrupt_for_missing_resources)
    graph.add_node("merge_resource_answers", _merge_resource_answers)
    graph.add_node("validate_resource_completion", _validate_resource_completion)
    graph.add_node("write_resource_file", _write_resource_file)
    graph.add_edge(START, "initialize_resource_context")
    graph.add_edge("initialize_resource_context", "infer_required_resource_keys")
    graph.add_edge("infer_required_resource_keys", "probe_resource_values")
    graph.add_edge("probe_resource_values", "collect_probe_results")
    graph.add_edge("collect_probe_results", "normalize_resource_values")
    graph.add_edge("normalize_resource_values", "validate_resource_completion")
    graph.add_conditional_edges(
        "validate_resource_completion",
        _route_after_validation,
        {
            "interrupt_for_missing_resources": "interrupt_for_missing_resources",
            "write_resource_file": "write_resource_file",
            END: END,
        },
    )
    graph.add_edge("interrupt_for_missing_resources", "merge_resource_answers")
    graph.add_edge("merge_resource_answers", "normalize_resource_values")
    graph.add_edge("write_resource_file", END)
    return graph.compile()


def run_resource_preparation_subgraph(state: FactoryGraphState) -> dict[str, Any]:
    original_stage_log_count = len(state.get("stage_log", []))
    final_state = build_resource_preparation_subgraph().invoke(state)
    return _delta_patch(final_state, original_stage_log_count=original_stage_log_count)


def _initialize_resource_context(state: FactoryGraphState) -> dict[str, Any]:
    factory_run_id = str(state.get("factory_run_id") or "")
    resource_file_path = _resource_file_path(factory_run_id)
    plan = dict(state.get("resource_condition_plan") or {})
    resources = dict(plan.get("resources") or {})
    return {
        "current_stage": "resource_and_condition_planning",
        "resource_condition_plan": {
            **plan,
            "status": str(plan.get("status") or "collecting"),
            "resources": resources,
            "resource_file_path": str(resource_file_path),
            "probe_evidence": list(plan.get("probe_evidence") or []),
        },
    }


def _infer_required_resource_keys(state: FactoryGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    existing_keys = list(plan.get("required_resource_keys") or [])
    if existing_keys:
        return {"resource_condition_plan": plan}
    inferred = _call_structured_model(
        prompt_id=PromptId.RESOURCE_KEY_INFERENCE,
        output_model=RequiredResourceKeySetOutput,
        values={
            "refined_plan_text": state.get("refined_plan_text") or "",
            "tool_capability_plan": _json_text(state.get("tool_capability_plan") or {}),
            "output_json_schema": output_json_schema(RequiredResourceKeySetOutput),
        },
        fallback=_fallback_required_resource_keys(state),
    )
    valid_keys = _valid_required_keys(inferred.keys, state)
    return {
        "resource_condition_plan": {
            **plan,
            "required_resource_keys": [item.model_dump(mode="json") for item in valid_keys],
            "assumptions": inferred.assumptions,
        }
    }


def _probe_resource_values(state: FactoryGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    resources = dict(plan.get("resources") or {})
    missing_keys = _missing_required_keys(plan)
    if not missing_keys:
        return {"resource_condition_plan": {**plan, "pending_probes": []}}
    probe_plan = _call_structured_model(
        prompt_id=PromptId.RESOURCE_PROBE_PLANNING,
        output_model=ResourceProbePlanOutput,
        values={
            "required_resource_keys": _json_text([item.model_dump(mode="json") for item in missing_keys]),
            "resources": _json_text(resources),
            "allowed_probe_tool_ids": _json_text(list(ALLOWED_PROBE_TOOL_IDS)),
            "output_json_schema": output_json_schema(ResourceProbePlanOutput),
        },
        fallback=ResourceProbePlanOutput(probes=[], assumptions=["model unavailable; no probes planned"]),
    )
    probes = [
        probe.model_dump(mode="json")
        for probe in probe_plan.probes
        if _valid_probe_request(probe, missing_keys)
    ]
    return {"resource_condition_plan": {**plan, "pending_probes": probes}}


def _collect_probe_results(state: FactoryGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    resources = dict(plan.get("resources") or {})
    evidence = list(plan.get("probe_evidence") or [])
    pending_probes = [
        ResourceProbeRequest.model_validate(item)
        for item in plan.get("pending_probes", []) or []
    ]
    for probe in pending_probes:
        result = _execute_probe(probe)
        evidence_item = {
            "key": probe.key,
            "tool_name": probe.tool_name,
            "arguments": probe.arguments,
            "reason": probe.reason,
            "result": result,
        }
        evidence.append(evidence_item)
        inferred_value = _resource_value_from_probe(probe, result)
        if inferred_value is not None:
            resources[probe.key] = inferred_value
    next_plan = {**plan, "resources": resources, "probe_evidence": evidence, "pending_probes": []}
    return {"resource_condition_plan": _with_missing_keys(next_plan)}


def _normalize_resource_values(state: FactoryGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    required_keys = [
        RequiredResourceKey.model_validate(item)
        for item in plan.get("required_resource_keys", []) or []
    ]
    if not required_keys:
        return {"resource_condition_plan": _with_missing_keys(plan)}
    current_resources = dict(plan.get("resources") or {})
    normalized = _call_structured_model(
        prompt_id=PromptId.RESOURCE_VALUE_NORMALIZATION,
        output_model=ResourceNormalizationOutput,
        values={
            "required_resource_keys": _json_text([item.model_dump(mode="json") for item in required_keys]),
            "current_resources": _json_text(current_resources),
            "probe_evidence": _json_text(plan.get("probe_evidence") or []),
            "tool_capability_plan": _json_text(state.get("tool_capability_plan") or {}),
            "output_json_schema": output_json_schema(ResourceNormalizationOutput),
        },
        fallback=ResourceNormalizationOutput(
            resources=current_resources,
            normalization_notes=["model unavailable; kept current resources unchanged"],
        ),
    )
    allowed_keys = {item.key for item in required_keys}
    merged_resources = _merge_normalized_resources(
        current_resources=current_resources,
        normalized_resources=normalized.resources,
        allowed_keys=allowed_keys,
    )
    normalization_notes = [
        str(item)
        for item in [
            *list(plan.get("normalization_notes") or []),
            *normalized.normalization_notes,
        ]
        if str(item).strip()
    ]
    next_plan = {
        **plan,
        "resources": merged_resources,
        "normalization_notes": normalization_notes,
    }
    return {"resource_condition_plan": _with_missing_keys(next_plan)}


def _interrupt_for_missing_resources(state: FactoryGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    missing_keys = list(plan.get("missing_keys") or [])
    answer = interrupt(
        {
            "type": "resource_completion",
            "missing_keys": missing_keys,
            "current_resources": dict(plan.get("resources") or {}),
            "probe_evidence": list(plan.get("probe_evidence") or []),
            "resource_file_path": plan.get("resource_file_path"),
        }
    )
    return {"resource_condition_plan": {**plan, "resource_answer": answer}}


def _merge_resource_answers(state: FactoryGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    resources = dict(plan.get("resources") or {})
    answer = ResourceCompletionAnswer.model_validate(plan.get("resource_answer") or {})
    blocked_keys: list[str] = list(plan.get("blocked_keys") or [])
    for item in answer.items:
        if item.decision == "provide_value":
            value = str(item.value or "").strip()
            if value:
                resources[item.key] = value
        elif item.decision == "runtime_provided":
            resources[item.key] = f"${{RUNTIME_PROVIDED:{item.key}}}"
        elif item.decision == "block":
            blocked_keys.append(item.key)
    next_plan = {
        **plan,
        "resources": resources,
        "blocked_keys": sorted(set(blocked_keys)),
        "resource_answer": None,
    }
    return {"resource_condition_plan": _with_missing_keys(next_plan)}


def _validate_resource_completion(state: FactoryGraphState) -> dict[str, Any]:
    plan = _with_missing_keys(dict(state.get("resource_condition_plan") or {}))
    blocked_keys = list(plan.get("blocked_keys") or [])
    missing_keys = list(plan.get("missing_keys") or [])
    if blocked_keys:
        return {
            "status": "blocked",
            "graph_control": {"action": "end"},
            "resource_condition_plan": {**plan, "status": "blocked"},
            "stage_log": [
                {
                    "stage_id": "resource_and_condition_planning",
                    "status": "blocked",
                    "message": "resource preparation blocked by user decision.",
                }
            ],
        }
    if missing_keys:
        return {"resource_condition_plan": {**plan, "status": "collecting"}}
    return {"resource_condition_plan": {**plan, "status": "complete"}}


def _write_resource_file(state: FactoryGraphState) -> dict[str, Any]:
    plan = dict(state.get("resource_condition_plan") or {})
    resource_file_path = Path(str(plan.get("resource_file_path") or _resource_file_path(str(state.get("factory_run_id") or ""))))
    resource_file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": RESOURCE_FILE_VERSION,
        "resources": dict(plan.get("resources") or {}),
    }
    resource_file_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "current_stage": "resource_and_condition_planning",
        "status": "running",
        "resource_file_path": str(resource_file_path),
        "resource_condition_plan": {
            **plan,
            "status": "complete",
            "resource_file_path": str(resource_file_path),
        },
        "stage_log": [
            {
                "stage_id": "resource_and_condition_planning",
                "status": "complete",
                "message": "resource_and_condition_planning prepared resources file.",
            }
        ],
    }


def _route_after_validation(state: FactoryGraphState) -> str:
    plan = state.get("resource_condition_plan") or {}
    if plan.get("status") == "blocked":
        return END
    if plan.get("status") == "complete":
        return "write_resource_file"
    return "interrupt_for_missing_resources"


def _valid_required_keys(
    keys: list[RequiredResourceKey],
    state: FactoryGraphState,
) -> list[RequiredResourceKey]:
    capability_ids = _capability_ids(state)
    valid: list[RequiredResourceKey] = []
    seen: set[str] = set()
    for item in keys:
        key = item.key.strip()
        if not key or key in seen:
            continue
        used_by = [capability_id for capability_id in item.used_by_capability_ids if capability_id in capability_ids]
        if not used_by and item.used_by_capability_ids:
            continue
        seen.add(key)
        valid.append(item.model_copy(update={"key": key, "used_by_capability_ids": used_by}))
    return valid


def _valid_probe_request(probe: ResourceProbeRequest, missing_keys: list[RequiredResourceKey]) -> bool:
    missing_key_ids = {item.key for item in missing_keys}
    if probe.key not in missing_key_ids:
        return False
    if probe.tool_name not in ALLOWED_PROBE_TOOL_IDS:
        return False
    return isinstance(probe.arguments, dict)


def _execute_probe(probe: ResourceProbeRequest) -> dict[str, Any]:
    try:
        if probe.tool_name == "file_read":
            return read_file.invoke(probe.arguments)
        if probe.tool_name == "file_list":
            return list_path.invoke(probe.arguments)
        if probe.tool_name == "file_exists":
            return path_exists.invoke(probe.arguments)
        if probe.tool_name == "search_files":
            return search_files.invoke(probe.arguments)
        if probe.tool_name == "search_text":
            return search_text.invoke(probe.arguments)
        if probe.tool_name == "shell_env":
            return read_environment.invoke({**probe.arguments, "include_values": False})
        if probe.tool_name == "shell_which":
            return which_command.invoke(probe.arguments)
        if probe.tool_name == "shell_cwd":
            return current_working_directory.invoke(probe.arguments)
    except Exception as exc:
        return {"status": "error", "error": f"{exc.__class__.__name__}: {exc}"}
    return {"status": "unsupported_probe_tool"}


def _resource_value_from_probe(probe: ResourceProbeRequest, result: dict[str, Any]) -> object | None:
    if result.get("status") == "error":
        return None
    if probe.tool_name == "shell_cwd":
        return result.get("cwd")
    if probe.tool_name == "shell_which" and result.get("found"):
        return result.get("path")
    if probe.tool_name == "file_exists" and result.get("exists"):
        return result.get("path")
    if probe.tool_name == "shell_env":
        variables = result.get("variables")
        if isinstance(variables, dict):
            existing = [name for name, item in variables.items() if isinstance(item, dict) and item.get("exists")]
            if existing:
                return existing[0]
    return None


def _missing_required_keys(plan: dict[str, Any]) -> list[RequiredResourceKey]:
    resources = dict(plan.get("resources") or {})
    missing: list[RequiredResourceKey] = []
    for item in plan.get("required_resource_keys", []) or []:
        resource_key = RequiredResourceKey.model_validate(item)
        if resource_key.required and not _has_resource_value(resources, resource_key.key):
            missing.append(resource_key)
    return missing


def _with_missing_keys(plan: dict[str, Any]) -> dict[str, Any]:
    missing = _missing_required_keys(plan)
    return {
        **plan,
        "missing_keys": [item.model_dump(mode="json") for item in missing],
    }


def _has_resource_value(resources: dict[str, Any], key: str) -> bool:
    value = resources.get(key)
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def _merge_normalized_resources(
    *,
    current_resources: dict[str, Any],
    normalized_resources: dict[str, object],
    allowed_keys: set[str],
) -> dict[str, object]:
    merged: dict[str, object] = {
        key: value
        for key, value in current_resources.items()
        if key in allowed_keys and _has_non_empty_value(value)
    }
    for key, value in normalized_resources.items():
        if key in allowed_keys and _has_non_empty_value(value):
            merged[key] = value
    return merged


def _has_non_empty_value(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, (list, tuple, dict, set)) and not value:
        return False
    return True


def _fallback_required_resource_keys(state: FactoryGraphState) -> RequiredResourceKeySetOutput:
    tool_plan = dict(state.get("tool_capability_plan") or {})
    keys = [
        RequiredResourceKey(
            key=f"{_sanitize_key(str(capability.get('capability_id') or 'capability'))}_resource",
            description=f"{capability.get('name') or capability.get('capability_id')} 所需资源值。",
            required=True,
            used_by_capability_ids=[str(capability.get("capability_id") or "")],
            resolution_hint="请提供该工具能力后续生成和测试所需的资源值，或选择运行时提供/阻塞。",
        )
        for capability in tool_plan.get("tool_capabilities", []) or []
        if str(capability.get("implementation_status") or "") in {"needs_generation", "needs_binding", "unknown"}
    ]
    return RequiredResourceKeySetOutput(
        keys=keys,
        assumptions=["model unavailable; generated generic resource keys from tool capabilities"],
    )


def _capability_ids(state: FactoryGraphState) -> set[str]:
    tool_plan = dict(state.get("tool_capability_plan") or {})
    return {
        str(capability.get("capability_id") or "")
        for capability in tool_plan.get("tool_capabilities", []) or []
        if capability.get("capability_id")
    }


def _resource_file_path(factory_run_id: str) -> Path:
    run_id = factory_run_id or "default"
    return Path(RESOURCE_ROOT) / run_id / "factory_resources.json"


def _sanitize_key(value: str) -> str:
    chars = []
    for char in value.lower():
        chars.append(char if char.isalnum() else "_")
    return "_".join(part for part in "".join(chars).split("_") if part)


def _call_structured_model(*, prompt_id, output_model, values: dict[str, Any], fallback):
    model = get_main_model()
    settings = get_main_model_settings()
    if model is None:
        return fallback
    try:
        prompt_value = get_prompt(prompt_id).invoke(values)
        structured_model = model.with_structured_output(output_model, method="json_mode").with_config(
            tags=["nostream"]
        )
        if settings.max_tokens is not None:
            structured_model = structured_model.bind(max_tokens=settings.max_tokens)
        return structured_model.invoke(prompt_value)
    except Exception:
        return fallback


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
    ):
        if key in final_state:
            patch[key] = final_state[key]
    patch["stage_log"] = list(final_state.get("stage_log", []))[original_stage_log_count:]
    return patch
