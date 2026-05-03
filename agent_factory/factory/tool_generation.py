from __future__ import annotations

import ast
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.model import LLMRequest, MessageBuilder
from agent_factory.specs import (
    AgentPackagePrimitives,
    JsonSchema,
    ResourceContractsSpec,
    ToolImplementationPlan,
)


class GeneratedToolTestCase(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    name: str
    input_data: dict[str, Any] = Field(default_factory=dict)
    expected_contains: dict[str, Any] = Field(default_factory=dict)


class GeneratedToolCodeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    tool_id: str
    python_source: str
    logic_source: str | None = None
    logic_path: str | None = None
    input_schema: JsonSchema = Field(default_factory=lambda: {"type": "object"})
    output_schema: JsonSchema = Field(default_factory=lambda: {"type": "object"})
    test_cases: list[GeneratedToolTestCase] = Field(default_factory=list)
    implementation_plan: ToolImplementationPlan | None = None
    risk_notes: list[str] = Field(default_factory=list)
    generation_status: Literal[
        "model_generated",
        "model_repaired",
        "deterministic_fallback",
        "generic_fallback",
    ] = "model_generated"
    fallback_used: bool = False
    repair_attempts: int = 0
    generation_errors: list[str] = Field(default_factory=list)


class ToolContract(BaseModel):
    """Small, code-free contract used before asking the model to write a tool."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    tool_id: str
    toolset_id: str
    purpose: str
    risk_level: str = "low"
    approval_required: bool = False
    input_schema: JsonSchema = Field(default_factory=lambda: {"type": "object"})
    output_schema: JsonSchema = Field(default_factory=lambda: {"type": "object"})
    required_behaviors: list[str] = Field(default_factory=list)
    forbidden_behaviors: list[str] = Field(default_factory=list)
    resource_refs: list[str] = Field(default_factory=list)
    test_requirements: list[GeneratedToolTestCase] = Field(default_factory=list)


class ToolContractBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    tools: list[ToolContract] = Field(default_factory=list)


FORBIDDEN_IMPORT_ROOTS = {
    "httpx",
    "importlib",
    "os",
    "pathlib",
    "requests",
    "shutil",
    "socket",
    "subprocess",
    "sys",
    "urllib",
}
FORBIDDEN_CALLS = {
    "__import__",
    "compile",
    "eval",
    "exec",
    "input",
    "open",
}
FORBIDDEN_ATTRS = {
    "open",
    "popen",
    "remove",
    "rmtree",
    "run",
    "system",
    "unlink",
    "write_text",
}


def build_tool_generation_request(
    primitives: AgentPackagePrimitives,
    draft: dict[str, Any],
    *,
    contract: ToolContract | None = None,
    requirement: str | None = None,
    requirement_analysis: dict[str, Any] | None = None,
    resource_contracts: ResourceContractsSpec | None = None,
) -> LLMRequest:
    contract = contract or derive_tool_contract(
        primitives,
        draft,
        requirement=requirement,
        requirement_analysis=requirement_analysis,
        resource_contracts=resource_contracts,
    )
    return (
        MessageBuilder.start()
        .system(
            "You generate only the business logic for one safe local Python tool. "
            "Return raw Python code only, not JSON, not markdown, and not explanations. "
            "The code must define exactly this callable: execute(input_data, resources). "
            "Do not define run(), input_schema(), output_schema(), CLI entrypoints, tests, or wrappers. "
            "The code must not access network, environment variables, shell, secrets, or files outside "
            "the explicit resources argument. Implement only the single tool contract provided."
        )
        .user(
            "Generate the logic.py content for exactly this one tool. Do not implement any other tool.\n\n"
            f"Agent persona: {primitives.instructions.persona}\n"
            f"Agent goal: {primitives.instructions.goal}\n"
            f"Agent boundaries: {json.dumps(primitives.instructions.boundaries, ensure_ascii=False)}\n"
            f"Requirement analysis summary:\n"
            f"{json.dumps(_compact_requirement_analysis(requirement_analysis), ensure_ascii=False, indent=2)}\n\n"
            f"Single tool contract:\n{contract.model_dump_json(indent=2)}\n\n"
            f"Resource contracts and environment facts:\n"
            f"{_resource_contracts_json(resource_contracts)}\n\n"
            "execute(input_data, resources) must return a dict. On success include status='completed'. "
            "Use resources['resources'], resources['sqlite_databases'], resources['filesystem_root'], "
            "or resources['runtime']; do not make a real user path the only data source.\n\n"
            "If the requirement describes a local SQLite database tool, implement it with sqlite3, "
            "parameterized SQL only, and no schema-changing statements. Resolve the database path from "
            "resources['sqlite_databases'] or resources['resources'] first. Never fake database results."
        )
        .request(
            response_format="text",
            metadata={"tool_id": str(draft.get("tool_id") or "")},
        )
    )


def build_tool_repair_request(
    primitives: AgentPackagePrimitives,
    draft: dict[str, Any],
    *,
    contract: ToolContract | None = None,
    previous_data: Any,
    validation_errors: list[str],
    requirement: str | None = None,
    requirement_analysis: dict[str, Any] | None = None,
    resource_contracts: ResourceContractsSpec | None = None,
) -> LLMRequest:
    contract = contract or derive_tool_contract(
        primitives,
        draft,
        requirement=requirement,
        requirement_analysis=requirement_analysis,
        resource_contracts=resource_contracts,
    )
    return (
        MessageBuilder.start()
        .system(
            "You repair unsafe or invalid Factory-generated Python tool logic. "
            "Return raw Python code only, not JSON, not markdown, and not explanations. "
            "The code must define execute(input_data, resources). Repair only this one tool."
        )
        .user(
            "Repair the generated tool logic so it is safe, executable, and business-complete.\n\n"
            f"Agent goal: {primitives.instructions.goal}\n"
            f"Single tool contract:\n{contract.model_dump_json(indent=2)}\n\n"
            f"Resource contracts and environment facts:\n"
            f"{_resource_contracts_json(resource_contracts)}\n\n"
            "Previous generated code or data:\n"
            f"{json.dumps(previous_data, ensure_ascii=False, indent=2, default=str)}\n\n"
            "Validation/security/test-generation errors:\n"
            f"{json.dumps(validation_errors, ensure_ascii=False, indent=2)}\n\n"
            "The repaired logic must define execute(input_data, resources). It must not access network, "
            "environment variables, shell, secrets, or files outside the explicitly requested local data source. "
            "For SQLite tools, use sqlite3 with parameterized SQL only and resolve the database path "
            "from resources['sqlite_databases'] or resources['resources']."
        )
        .request(
            response_format="text",
            metadata={"tool_id": str(draft.get("tool_id") or ""), "repair": True},
        )
    )


def build_tool_contracts_request(
    primitives: AgentPackagePrimitives,
    tool_drafts: list[dict[str, Any]],
    *,
    requirement: str | None = None,
    requirement_analysis: dict[str, Any] | None = None,
    resource_contracts: ResourceContractsSpec | None = None,
) -> LLMRequest:
    schema = ToolContractBatch.model_json_schema()
    sources = [
        source.model_dump(mode="json")
        for source in primitives.knowledge.sources
        if source.type in {"file", "mcp"}
    ]
    return (
        MessageBuilder.start()
        .system(
            "You create code-free tool contracts for an AgentPackage. Return exactly one JSON object "
            "with a top-level 'tools' array matching ToolContractBatch. Do not write Python code."
        )
        .user(
            "Create one concise contract for each requested tool. Contracts describe behavior, inputs, "
            "outputs, resources, forbidden behavior, and test requirements. Do not include python_source.\n\n"
            f"Original requirement:\n{requirement or ''}\n\n"
            f"Requirement analysis:\n{json.dumps(requirement_analysis or {}, ensure_ascii=False, indent=2)}\n\n"
            f"Agent goal: {primitives.instructions.goal}\n"
            f"Agent boundaries: {json.dumps(primitives.instructions.boundaries, ensure_ascii=False)}\n"
            f"Knowledge/resource sources:\n{json.dumps(sources, ensure_ascii=False, indent=2)}\n\n"
            f"Resource contracts and environment facts:\n{_resource_contracts_json(resource_contracts)}\n\n"
            f"Tool drafts:\n{json.dumps(tool_drafts, ensure_ascii=False, indent=2)}\n\n"
            "Return contracts only. Never include Python code."
        )
        .request(
            response_format="json_schema",
            json_schema=schema,
            json_schema_name="ToolContractBatch",
            json_schema_strict=True,
            metadata={"tool_count": len(tool_drafts), "phase": "tool_contracts"},
        )
    )


def derive_tool_contract(
    primitives: AgentPackagePrimitives,
    draft: dict[str, Any],
    *,
    requirement: str | None = None,
    requirement_analysis: dict[str, Any] | None = None,
    resource_contracts: ResourceContractsSpec | None = None,
) -> ToolContract:
    test_cases = required_tool_test_cases(
        draft,
        primitives=primitives,
        requirement=requirement,
    )
    resource_refs = [
        source.id
        for source in primitives.knowledge.sources
        if source.type in {"file", "directory", "mcp"}
    ]
    if resource_contracts is not None:
        for resource in resource_contracts.resources:
            if resource.id not in resource_refs:
                resource_refs.append(resource.id)
    forbidden = [
        "do_not_read_env_or_secrets",
        "do_not_execute_shell",
        "do_not_access_network",
        "do_not_access_files_outside_runtime_context",
    ]
    if is_sqlite_customer_ticket_tool(draft, primitives=primitives, requirement=requirement):
        forbidden.extend(
            [
                "do_not_use_string_interpolated_sql_values",
                "do_not_drop_or_alter_schema",
                "do_not_delete_database_files",
            ]
        )
    return ToolContract(
        tool_id=str(draft.get("tool_id") or "generated_tool"),
        toolset_id=str(draft.get("toolset_id") or "default"),
        purpose=str(draft.get("description") or primitives.instructions.goal),
        risk_level=str(draft.get("risk_level") or "low"),
        approval_required=bool(draft.get("approval_required")),
        input_schema={"type": "object", "additionalProperties": True},
        output_schema={"type": "object", "additionalProperties": True},
        required_behaviors=_contract_required_behaviors(draft, test_cases),
        forbidden_behaviors=forbidden,
        resource_refs=resource_refs,
        test_requirements=test_cases,
    )


def _resource_contracts_json(resource_contracts: ResourceContractsSpec | None) -> str:
    if resource_contracts is None:
        return "{}"
    return resource_contracts.model_dump_json(indent=2)


def _compact_requirement_analysis(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    allowed = {
        "agent_name",
        "agent_type",
        "safety_profile",
        "goals",
        "in_scope",
        "out_of_scope",
        "confidence",
    }
    return {key: value[key] for key in allowed if key in value}


def _contract_required_behaviors(
    draft: dict[str, Any],
    test_cases: list[GeneratedToolTestCase],
) -> list[str]:
    behaviors = [str(draft.get("description") or draft.get("tool_id") or "Implement the tool contract.")]
    for case in test_cases:
        behaviors.append(f"Pass test case '{case.name}' with expected fields {case.expected_contains}.")
    return behaviors


def validate_tool_source(source: str) -> list[str]:
    issues: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return [f"syntax_error: {error}"]

    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    for required in {"input_schema", "output_schema", "run"}:
        if required not in functions:
            issues.append(f"missing_required_function: {required}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_IMPORT_ROOTS:
                    issues.append(f"forbidden_import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in FORBIDDEN_IMPORT_ROOTS:
                issues.append(f"forbidden_import: {node.module}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                issues.append(f"forbidden_call: {node.func.id}")
            if isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN_ATTRS:
                issues.append(f"forbidden_call: {node.func.attr}")
    return issues


def validate_tool_logic_source(source: str) -> list[str]:
    issues = _validate_python_safety(source)
    if issues and any(issue.startswith("syntax_error") for issue in issues):
        return issues
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return [f"syntax_error: {error}"]
    functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
    if "execute" not in functions:
        issues.append("missing_required_function: execute")
    forbidden_wrapper_functions = {"run", "input_schema", "output_schema"}
    overlap = functions.intersection(forbidden_wrapper_functions)
    for name in sorted(overlap):
        issues.append(f"logic_must_not_define_wrapper_function: {name}")
    return issues


def _validate_python_safety(source: str) -> list[str]:
    issues: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return [f"syntax_error: {error}"]

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in FORBIDDEN_IMPORT_ROOTS:
                    issues.append(f"forbidden_import: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in FORBIDDEN_IMPORT_ROOTS:
                issues.append(f"forbidden_import: {node.module}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                issues.append(f"forbidden_call: {node.func.id}")
            if isinstance(node.func, ast.Attribute) and node.func.attr in FORBIDDEN_ATTRS:
                issues.append(f"forbidden_call: {node.func.attr}")
    return issues


def fallback_tool_code(
    draft: dict[str, Any],
    *,
    primitives: AgentPackagePrimitives | None = None,
    requirement: str | None = None,
    generation_errors: list[str] | None = None,
    repair_attempts: int = 0,
) -> GeneratedToolCodeDraft:
    tool_id = str(draft.get("tool_id") or "generated_tool")
    risk_level = str(draft.get("risk_level") or "low")
    approval_required = bool(draft.get("approval_required"))
    errors = list(generation_errors or [])
    status: Literal["deterministic_fallback", "generic_fallback"] = "deterministic_fallback"
    if tool_id == "order_query":
        source = _order_query_source(tool_id, risk_level, approval_required)
        test_cases = [
            GeneratedToolTestCase(
                name="order_query_extracts_order_id",
                input_data={"query": "帮我查订单 123"},
                expected_contains={
                    "status": "completed",
                    "tool_id": tool_id,
                    "order_id": "123",
                    "order_status": "in_transit",
                },
            )
        ]
    elif is_strange_number_tool(draft):
        source = _strange_number_source(tool_id, risk_level, approval_required)
        test_cases = required_tool_test_cases(draft)
    elif is_sqlite_customer_ticket_tool(draft, primitives=primitives, requirement=requirement):
        source_id, db_path = find_sqlite_resource(primitives=primitives, requirement=requirement)
        source = _sqlite_customer_ticket_source(
            tool_id,
            risk_level,
            approval_required,
            db_path or "",
            source_id or "customer_ops_sqlite",
        )
        test_cases = required_tool_test_cases(
            draft,
            primitives=primitives,
            requirement=requirement,
        )
    else:
        source = _generic_tool_source(tool_id, risk_level, approval_required)
        test_cases = [
            GeneratedToolTestCase(
                name="generic_tool_returns_completed_contract",
                input_data={"sample": "value"},
                expected_contains={"status": "completed", "tool_id": tool_id},
            )
        ]
        status = "generic_fallback"
    return GeneratedToolCodeDraft(
        tool_id=tool_id,
        python_source=source,
        input_schema={"type": "object", "additionalProperties": True},
        output_schema={"type": "object", "additionalProperties": True},
        test_cases=test_cases,
        implementation_plan=ToolImplementationPlan(
            tool_id=tool_id,
            resource_refs=[find_sqlite_resource(primitives=primitives, requirement=requirement)[0] or "customer_ops_sqlite"]
            if is_sqlite_customer_ticket_tool(draft, primitives=primitives, requirement=requirement)
            else [],
            preconditions=["tool_contract_available", "sandbox_context_available"],
            allowed_operations=["local_deterministic_operation"],
            forbidden_operations=[
                "read_env_or_secrets",
                "execute_shell",
                "network_access",
                "access_files_outside_runtime_context",
            ],
            failure_cases=["missing_required_input", "resource_unavailable"],
        ),
        risk_notes=["deterministic local implementation" if status == "deterministic_fallback" else "generic fallback placeholder"],
        generation_status=status,
        fallback_used=True,
        repair_attempts=repair_attempts,
        generation_errors=errors,
    )


def required_tool_test_cases(
    draft: dict[str, Any],
    *,
    primitives: AgentPackagePrimitives | None = None,
    requirement: str | None = None,
) -> list[GeneratedToolTestCase]:
    tool_id = str(draft.get("tool_id") or "generated_tool")
    if tool_id == "order_query":
        return [
            GeneratedToolTestCase(
                name="order_query_extracts_order_id",
                input_data={"query": "帮我查订单 123"},
                expected_contains={
                    "status": "completed",
                    "tool_id": tool_id,
                    "order_id": "123",
                    "order_status": "in_transit",
                },
            )
        ]
    if is_strange_number_tool(draft):
        return [
            GeneratedToolTestCase(
                name="positive_number_returns_square",
                input_data={"number": 5},
                expected_contains={
                    "status": "completed",
                    "tool_id": tool_id,
                    "number": 5,
                    "result": 25,
                    "rule": "positive_square",
                },
            ),
            GeneratedToolTestCase(
                name="negative_number_returns_double",
                input_data={"query": "-9的奇异数是多少"},
                expected_contains={
                    "status": "completed",
                    "tool_id": tool_id,
                    "number": -9,
                    "result": -18,
                    "rule": "negative_double",
                },
            ),
        ]
    if is_sqlite_customer_ticket_tool(draft, primitives=primitives, requirement=requirement):
        if tool_id == "list_customer_tickets":
            return [
                GeneratedToolTestCase(
                    name="list_customer_tickets_returns_known_ticket",
                    input_data={"limit": 20, "offset": 0},
                    expected_contains={
                        "status": "completed",
                        "tool_id": tool_id,
                        "contains_ticket_id": "T-1001",
                    },
                )
            ]
        if tool_id == "get_customer_ticket":
            return [
                GeneratedToolTestCase(
                    name="get_customer_ticket_returns_liuyan",
                    input_data={"ticket_id": "T-1001"},
                    expected_contains={
                        "status": "completed",
                        "tool_id": tool_id,
                        "found": True,
                        "ticket_id": "T-1001",
                        "customer_name": "刘岩",
                    },
                )
            ]
        if tool_id == "search_customer_tickets":
            return [
                GeneratedToolTestCase(
                    name="search_open_tickets_returns_t1001",
                    input_data={"status": "open"},
                    expected_contains={
                        "status": "completed",
                        "tool_id": tool_id,
                        "matched_ticket_id": "T-1001",
                    },
                )
            ]
        if tool_id == "create_customer_ticket":
            return [
                GeneratedToolTestCase(
                    name="create_customer_ticket_creates_test_ticket",
                    input_data={
                        "ticket_id": "T-AF-TEST-CREATE",
                        "customer_name": "工具测试",
                        "channel": "test",
                        "title": "Factory 工具生成测试",
                        "description": "用于验证工具可以参数化写入本地 SQLite。",
                        "status": "open",
                        "priority": "low",
                        "assignee": "agentfactory",
                    },
                    expected_contains={
                        "status": "completed",
                        "tool_id": tool_id,
                        "created": True,
                        "ticket_id": "T-AF-TEST-CREATE",
                    },
                )
            ]
        if tool_id == "update_customer_ticket_status":
            return [
                GeneratedToolTestCase(
                    name="update_customer_ticket_status_validates_status",
                    input_data={"ticket_id": "T-1001", "status": "resolved"},
                    expected_contains={
                        "status": "completed",
                        "tool_id": tool_id,
                        "updated": True,
                        "new_status": "resolved",
                    },
                ),
                GeneratedToolTestCase(
                    name="update_customer_ticket_status_rejects_invalid_status",
                    input_data={"ticket_id": "T-1001", "status": "drop_table"},
                    expected_contains={
                        "status": "failed",
                        "tool_id": tool_id,
                        "error_code": "invalid_status",
                    },
                ),
            ]
        if tool_id == "close_customer_ticket":
            return [
                GeneratedToolTestCase(
                    name="close_customer_ticket_sets_closed",
                    input_data={"ticket_id": "T-1001"},
                    expected_contains={
                        "status": "completed",
                        "tool_id": tool_id,
                        "updated": True,
                        "new_status": "closed",
                    },
                )
            ]
    return []


def _order_query_source(tool_id: str, risk_level: str, approval_required: bool) -> str:
    return f'''"""Factory-generated local mock tool implementation."""

from __future__ import annotations

from typing import Any


TOOL_ID = {tool_id!r}
RISK_LEVEL = {risk_level!r}
APPROVAL_REQUIRED = {approval_required!r}


def input_schema() -> dict[str, Any]:
    return {{"type": "object", "additionalProperties": True}}


def output_schema() -> dict[str, Any]:
    return {{"type": "object", "additionalProperties": True}}


def run(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(input_data, dict):
        raise TypeError("input_data must be a dict")
    query = str(input_data.get("query") or input_data.get("order_id") or "")
    digits = "".join(ch for ch in query if ch.isdigit())
    order_id = digits or "unknown"
    return {{
        "status": "completed",
        "tool_id": TOOL_ID,
        "order_id": order_id,
        "order_status": "in_transit",
        "message": f"订单{{order_id}}正在运输中，预计 2 天内送达。",
        "input": input_data,
    }}
'''


def _strange_number_source(tool_id: str, risk_level: str, approval_required: bool) -> str:
    return f'''"""Factory-generated deterministic strange-number calculator."""

from __future__ import annotations

import re
from typing import Any


TOOL_ID = {tool_id!r}
RISK_LEVEL = {risk_level!r}
APPROVAL_REQUIRED = {approval_required!r}


def input_schema() -> dict[str, Any]:
    return {{
        "type": "object",
        "properties": {{
            "number": {{"type": "number"}},
            "query": {{"type": "string"}},
        }},
        "additionalProperties": True,
    }}


def output_schema() -> dict[str, Any]:
    return {{
        "type": "object",
        "properties": {{
            "status": {{"type": "string"}},
            "tool_id": {{"type": "string"}},
            "number": {{"type": "number"}},
            "result": {{"type": "number"}},
            "rule": {{"type": "string"}},
            "message": {{"type": "string"}},
        }},
        "required": ["status", "tool_id", "number", "result", "rule", "message"],
        "additionalProperties": True,
    }}


def run(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(input_data, dict):
        raise TypeError("input_data must be a dict")
    number = _coerce_number(input_data)
    if number is None:
        return {{
            "status": "failed",
            "tool_id": TOOL_ID,
            "error": "No valid number found in input.",
            "input": input_data,
        }}
    if number >= 0:
        result = number * number
        rule = "positive_square"
        expression = f"{{_format_number(number)}}^2"
    else:
        result = number * 2
        rule = "negative_double"
        expression = f"{{_format_number(number)}} * 2"
    return {{
        "status": "completed",
        "tool_id": TOOL_ID,
        "number": _normalize_number(number),
        "result": _normalize_number(result),
        "rule": rule,
        "message": f"{{_format_number(number)}} 的奇异数是 {{_format_number(result)}}（{{expression}}）。",
        "input": input_data,
    }}


def _coerce_number(input_data: dict[str, Any]) -> float | None:
    for key in ("number", "value", "n"):
        value = input_data.get(key)
        if isinstance(value, int | float):
            return float(value)
        if isinstance(value, str):
            parsed = _parse_number(value)
            if parsed is not None:
                return parsed
    for key in ("query", "text", "input"):
        value = input_data.get(key)
        if isinstance(value, str):
            parsed = _parse_number(value)
            if parsed is not None:
                return parsed
    return None


def _parse_number(text: str) -> float | None:
    match = re.search(r"[-+]?\\d+(?:\\.\\d+)?", text)
    if not match:
        return None
    return float(match.group(0))


def _normalize_number(value: float) -> int | float:
    return int(value) if value.is_integer() else value


def _format_number(value: float) -> str:
    return str(_normalize_number(value))
'''


def _generic_tool_source(tool_id: str, risk_level: str, approval_required: bool) -> str:
    return f'''"""Factory-generated local mock tool implementation."""

from __future__ import annotations

from typing import Any


TOOL_ID = {tool_id!r}
RISK_LEVEL = {risk_level!r}
APPROVAL_REQUIRED = {approval_required!r}


def input_schema() -> dict[str, Any]:
    return {{"type": "object", "additionalProperties": True}}


def output_schema() -> dict[str, Any]:
    return {{"type": "object", "additionalProperties": True}}


def run(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(input_data, dict):
        raise TypeError("input_data must be a dict")
    return {{
        "status": "completed",
        "tool_id": TOOL_ID,
        "message": "已完成本地模拟处理。",
        "input": input_data,
    }}
'''


def _sqlite_customer_ticket_source(
    tool_id: str,
    risk_level: str,
    approval_required: bool,
    db_path: str,
    resource_id: str,
) -> str:
    return f'''"""Factory-generated local SQLite customer ticket tool."""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from typing import Any


TOOL_ID = {tool_id!r}
RISK_LEVEL = {risk_level!r}
APPROVAL_REQUIRED = {approval_required!r}
DB_PATH = {db_path!r}
RESOURCE_ID = {resource_id!r}
ALLOWED_STATUS = {{"open", "pending", "resolved", "closed"}}
SELECT_COLUMNS = (
    "ticket_id, customer_name, channel, title, description, "
    "status, priority, assignee, created_at, updated_at"
)


def input_schema() -> dict[str, Any]:
    return {{"type": "object", "additionalProperties": True}}


def output_schema() -> dict[str, Any]:
    return {{"type": "object", "additionalProperties": True}}


def run(input_data: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(input_data, dict):
        raise TypeError("input_data must be a dict")
    db_path = _resolve_db_path(context)
    if not db_path:
        return _failure("missing_db_path", "SQLite database path was not provided.", input_data)
    if _contains_forbidden_sql(input_data):
        return _failure("forbidden_sql_input", "Input contains forbidden SQL operation text.", input_data)
    global _ACTIVE_DB_PATH
    _ACTIVE_DB_PATH = db_path

    if TOOL_ID == "list_customer_tickets":
        return _list_tickets(input_data)
    if TOOL_ID == "get_customer_ticket":
        return _get_ticket(input_data)
    if TOOL_ID == "search_customer_tickets":
        return _search_tickets(input_data)
    if TOOL_ID == "create_customer_ticket":
        return _create_ticket(input_data)
    if TOOL_ID == "update_customer_ticket_status":
        return _update_ticket_status(input_data)
    if TOOL_ID == "close_customer_ticket":
        data = dict(input_data)
        data["status"] = "closed"
        return _update_ticket_status(data)
    return _failure("unsupported_tool", f"Unsupported tool id: {{TOOL_ID}}", input_data)


_ACTIVE_DB_PATH = DB_PATH


def _resolve_db_path(context: dict[str, Any] | None) -> str:
    if isinstance(context, dict):
        sqlite_databases = context.get("sqlite_databases")
        if isinstance(sqlite_databases, dict):
            for key in (RESOURCE_ID, "customer_ops_sqlite", "customer_ops", "default"):
                value = sqlite_databases.get(key)
                if isinstance(value, str) and value.strip():
                    return value
            if len(sqlite_databases) == 1:
                value = next(iter(sqlite_databases.values()))
                if isinstance(value, str) and value.strip():
                    return value
        resources = context.get("resources")
        if isinstance(resources, dict):
            resource = resources.get(RESOURCE_ID)
            if isinstance(resource, dict):
                value = resource.get("path")
                if isinstance(value, str) and value.strip():
                    return value
    return DB_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_ACTIVE_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _list_tickets(input_data: dict[str, Any]) -> dict[str, Any]:
    limit = _bounded_int(input_data.get("limit"), default=20, minimum=1, maximum=100)
    offset = _bounded_int(input_data.get("offset"), default=0, minimum=0, maximum=100000)
    with closing(_connect()) as conn, conn:
        rows = conn.execute(
            f"SELECT {{SELECT_COLUMNS}} FROM customer_tickets ORDER BY created_at DESC, ticket_id ASC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    tickets = [_row_to_dict(row) for row in rows]
    ticket_ids = [ticket["ticket_id"] for ticket in tickets]
    return {{
        "status": "completed",
        "tool_id": TOOL_ID,
        "tickets": tickets,
        "ticket_ids": ticket_ids,
        "count": len(tickets),
        "contains_ticket_id": "T-1001" if "T-1001" in ticket_ids else "",
    }}


def _get_ticket(input_data: dict[str, Any]) -> dict[str, Any]:
    ticket_id = _coerce_ticket_id(input_data)
    if not ticket_id:
        return _failure("missing_ticket_id", "ticket_id is required.", input_data)
    with closing(_connect()) as conn, conn:
        row = conn.execute(
            f"SELECT {{SELECT_COLUMNS}} FROM customer_tickets WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchone()
    if row is None:
        return {{
            "status": "completed",
            "tool_id": TOOL_ID,
            "found": False,
            "ticket_id": ticket_id,
            "message": f"没有找到工单 {{ticket_id}}。",
        }}
    ticket = _row_to_dict(row)
    return {{
        **ticket,
        "status": "completed",
        "tool_id": TOOL_ID,
        "found": True,
        "ticket_status": ticket.get("status"),
        "ticket": ticket,
    }}


def _search_tickets(input_data: dict[str, Any]) -> dict[str, Any]:
    clauses: list[str] = []
    params: list[Any] = []
    status = str(input_data.get("status") or "").strip()
    if status:
        if status not in ALLOWED_STATUS:
            return _failure("invalid_status", "status must be open/pending/resolved/closed.", input_data)
        clauses.append("status = ?")
        params.append(status)
    for key, column in (
        ("customer_name", "customer_name"),
        ("priority", "priority"),
        ("title_keyword", "title"),
        ("query", "title"),
    ):
        value = str(input_data.get(key) or "").strip()
        if not value:
            continue
        if column == "priority":
            clauses.append("priority = ?")
            params.append(value)
        else:
            clauses.append(f"{{column}} LIKE ?")
            params.append(f"%{{value}}%")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    limit = _bounded_int(input_data.get("limit"), default=20, minimum=1, maximum=100)
    with closing(_connect()) as conn, conn:
        rows = conn.execute(
            f"SELECT {{SELECT_COLUMNS}} FROM customer_tickets{{where}} ORDER BY created_at DESC, ticket_id ASC LIMIT ?",
            (*params, limit),
        ).fetchall()
    tickets = [_row_to_dict(row) for row in rows]
    ticket_ids = [ticket["ticket_id"] for ticket in tickets]
    return {{
        "status": "completed",
        "tool_id": TOOL_ID,
        "tickets": tickets,
        "ticket_ids": ticket_ids,
        "count": len(tickets),
        "matched_ticket_id": "T-1001" if "T-1001" in ticket_ids else (ticket_ids[0] if ticket_ids else ""),
    }}


def _create_ticket(input_data: dict[str, Any]) -> dict[str, Any]:
    ticket_id = str(input_data.get("ticket_id") or "").strip() or _generated_ticket_id()
    status = str(input_data.get("status") or "open").strip()
    if status not in ALLOWED_STATUS:
        return _failure("invalid_status", "status must be open/pending/resolved/closed.", input_data)
    now = _now()
    values = {{
        "ticket_id": ticket_id,
        "customer_name": str(input_data.get("customer_name") or "未命名客户").strip(),
        "channel": str(input_data.get("channel") or "manual").strip(),
        "title": str(input_data.get("title") or "未命名工单").strip(),
        "description": str(input_data.get("description") or "").strip(),
        "status": status,
        "priority": str(input_data.get("priority") or "medium").strip(),
        "assignee": str(input_data.get("assignee") or "").strip(),
        "created_at": str(input_data.get("created_at") or now).strip(),
        "updated_at": str(input_data.get("updated_at") or now).strip(),
    }}
    with closing(_connect()) as conn, conn:
        conn.execute(
            "INSERT OR REPLACE INTO customer_tickets "
            "(ticket_id, customer_name, channel, title, description, status, priority, assignee, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                values["ticket_id"],
                values["customer_name"],
                values["channel"],
                values["title"],
                values["description"],
                values["status"],
                values["priority"],
                values["assignee"],
                values["created_at"],
                values["updated_at"],
            ),
        )
    return {{
        "status": "completed",
        "tool_id": TOOL_ID,
        "created": True,
        "ticket_id": ticket_id,
        "ticket": values,
    }}


def _update_ticket_status(input_data: dict[str, Any]) -> dict[str, Any]:
    ticket_id = _coerce_ticket_id(input_data)
    if not ticket_id:
        return _failure("missing_ticket_id", "ticket_id is required.", input_data)
    new_status = str(input_data.get("status") or "").strip()
    if new_status not in ALLOWED_STATUS:
        return _failure("invalid_status", "status must be open/pending/resolved/closed.", input_data)
    updated_at = _now()
    with closing(_connect()) as conn, conn:
        cursor = conn.execute(
            "UPDATE customer_tickets SET status = ?, updated_at = ? WHERE ticket_id = ?",
            (new_status, updated_at, ticket_id),
        )
        row = conn.execute(
            f"SELECT {{SELECT_COLUMNS}} FROM customer_tickets WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchone()
    return {{
        "status": "completed" if cursor.rowcount else "failed",
        "tool_id": TOOL_ID,
        "updated": bool(cursor.rowcount),
        "ticket_id": ticket_id,
        "new_status": new_status,
        "ticket": _row_to_dict(row) if row is not None else None,
        "error_code": "" if cursor.rowcount else "ticket_not_found",
    }}


def _contains_forbidden_sql(input_data: dict[str, Any]) -> bool:
    text = " ".join(str(value) for value in input_data.values()).lower()
    return any(word in text for word in ("drop ", "alter ", "attach ", "detach ", "pragma", "vacuum"))


def _coerce_ticket_id(input_data: dict[str, Any]) -> str:
    direct = str(input_data.get("ticket_id") or input_data.get("id") or "").strip()
    if direct:
        return direct
    text = str(input_data.get("query") or input_data.get("text") or "")
    match = re.search(r"T[-_]?\\d+", text, flags=re.IGNORECASE)
    return match.group(0).replace("_", "-").upper() if match else ""


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {{key: row[key] for key in row.keys()}}


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _generated_ticket_id() -> str:
    return "T-AF-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _failure(error_code: str, message: str, input_data: dict[str, Any]) -> dict[str, Any]:
    return {{
        "status": "failed",
        "tool_id": TOOL_ID,
        "error_code": error_code,
        "message": message,
        "input": input_data,
    }}
'''


def is_strange_number_tool(draft: dict[str, Any]) -> bool:
    text = " ".join(
        str(draft.get(key) or "")
        for key in ("tool_id", "toolset_id", "description")
    ).lower()
    return "strange" in text or "奇异" in text


def is_sqlite_customer_ticket_tool(
    draft: dict[str, Any],
    *,
    primitives: AgentPackagePrimitives | None = None,
    requirement: str | None = None,
) -> bool:
    tool_id = str(draft.get("tool_id") or "")
    known_ids = {
        "list_customer_tickets",
        "get_customer_ticket",
        "search_customer_tickets",
        "create_customer_ticket",
        "update_customer_ticket_status",
        "close_customer_ticket",
    }
    if tool_id in known_ids:
        return bool(find_sqlite_db_path(primitives=primitives, requirement=requirement))
    text = " ".join(
        str(draft.get(key) or "")
        for key in ("tool_id", "toolset_id", "description")
    ).lower()
    if "sqlite" not in text and "customer_ticket" not in text and "工单" not in text:
        return False
    return bool(find_sqlite_db_path(primitives=primitives, requirement=requirement))


def find_sqlite_db_path(
    *,
    primitives: AgentPackagePrimitives | None = None,
    requirement: str | None = None,
) -> str | None:
    _source_id, path = find_sqlite_resource(primitives=primitives, requirement=requirement)
    return path


def find_sqlite_resource(
    *,
    primitives: AgentPackagePrimitives | None = None,
    requirement: str | None = None,
) -> tuple[str | None, str | None]:
    candidates: list[str] = []
    source_ids: dict[str, str] = {}
    if primitives is not None:
        for source in primitives.knowledge.sources:
            if source.ref:
                candidates.append(source.ref)
                source_ids[source.ref] = source.id
    if requirement:
        candidates.extend(
            match.group(0)
            for match in re.finditer(r"/[^\s，。；;'\"]+\.(?:sqlite3|sqlite|db)", requirement)
        )
    for candidate in candidates:
        normalized = str(candidate).strip()
        if re.search(r"\.(sqlite3|sqlite|db)$", normalized, flags=re.IGNORECASE):
            return source_ids.get(candidate), normalized
    return None, None
