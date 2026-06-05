from __future__ import annotations

from agent_factory.create_agent.models import PackageValidationReport, TodoList, TodoStatus
from agent_factory.create_agent.scaffold_tool import CREATE_AGENT_SCAFFOLD_TOOL_ID


def validation_event_from_tool_calls(tool_calls: list[dict[str, object]]) -> str:
    tool_names = {str(call.get("name") or "") for call in tool_calls}
    if "create_agent_control" in tool_names:
        return "control"
    if "create_agent_validate" in tool_names:
        return "explicit_validation"
    if tool_names & {"write", "edit", "multi_edit", CREATE_AGENT_SCAFFOLD_TOOL_ID}:
        return "package_change"
    if "create_agent_todo" in tool_names:
        return "todo"
    return "none"


def apply_validation_progress(todo: TodoList, report: PackageValidationReport) -> TodoList:
    todo = _apply_validation_passes(todo, report)
    if report.status != "passed":
        return todo.upsert_repair_items(report.issues)
    return todo


def _apply_validation_passes(todo: TodoList, report: PackageValidationReport) -> TodoList:
    passed_ids = _validator_passed_todo_ids(report)
    if not passed_ids:
        return todo
    items = []
    changed = False
    for item in todo.items:
        if item.todo_id not in passed_ids or item.status == TodoStatus.done:
            items.append(item)
            continue
        details = dict(item.details or {})
        evidence = list(details.get("evidence") or [])
        evidence.append(f"Validated by create_agent_validate: {report.validation_scope} | {report.summary}")
        details["evidence"] = evidence[-12:]
        items.append(item.model_copy(update={"status": TodoStatus.done, "details": details}))
        changed = True
    return todo.model_copy(update={"items": items}) if changed else todo


def _validator_passed_todo_ids(report: PackageValidationReport) -> set[str]:
    if report.status == "passed":
        if report.validation_scope == "full_static":
            # Only full_static (which now includes semantic + smoke test) marks all
            return {
                "package_manifest",
                "runtime_contracts",
                "assembly_and_patterns",
                "state_resources_render",
                "tools_nodes_extensions",
                "validate_agent_package",
            }
        if report.validation_scope == "assembly_compile":
            return {"package_manifest", "runtime_contracts", "assembly_and_patterns"}
        if report.validation_scope == "runtime_contract_build":
            return {"package_manifest", "runtime_contracts"}
        if report.validation_scope == "package_shape":
            return {"package_manifest"}
    return set()
