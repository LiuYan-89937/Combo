from __future__ import annotations

import ast
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agent_factory.model import LLMRequest, MessageBuilder
from agent_factory.specs import AgentPackagePrimitives, JsonSchema


class GeneratedToolTestCase(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    name: str
    input_data: dict[str, Any] = Field(default_factory=dict)
    expected_contains: dict[str, Any] = Field(default_factory=dict)


class GeneratedToolCodeDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    tool_id: str
    python_source: str
    input_schema: JsonSchema = Field(default_factory=lambda: {"type": "object"})
    output_schema: JsonSchema = Field(default_factory=lambda: {"type": "object"})
    test_cases: list[GeneratedToolTestCase] = Field(default_factory=list)
    risk_notes: list[str] = Field(default_factory=list)


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
    requirement: str | None = None,
    requirement_analysis: dict[str, Any] | None = None,
) -> LLMRequest:
    schema = GeneratedToolCodeDraft.model_json_schema()
    few_shots = [
        item.model_dump(mode="json")
        for item in primitives.instructions.few_shots
    ]
    return (
        MessageBuilder.start()
        .system(
            "You generate safe, deterministic local Python tool implementations for AgentPackage drafts. "
            "Return only JSON matching the provided schema. The Python code must not access network, env, "
            "shell, filesystem outside runtime input, or secrets. Implement the actual domain behavior "
            "described by the requirement and tool draft; do not return a generic placeholder."
        )
        .user(
            "Generate a local mock/read-only tool implementation with real deterministic business logic.\n\n"
            f"Original requirement:\n{requirement or ''}\n\n"
            "Requirement analysis:\n"
            f"{json.dumps(requirement_analysis or {}, ensure_ascii=False, indent=2)}\n\n"
            f"Agent persona: {primitives.instructions.persona}\n"
            f"Agent goal: {primitives.instructions.goal}\n"
            f"Agent boundaries: {json.dumps(primitives.instructions.boundaries, ensure_ascii=False)}\n"
            f"Agent principles: {json.dumps(primitives.instructions.principles, ensure_ascii=False)}\n"
            f"Agent few-shot examples: {json.dumps(few_shots, ensure_ascii=False)}\n\n"
            f"Tool draft:\n{json.dumps(draft, ensure_ascii=False, indent=2)}\n\n"
            "The python_source must define input_schema(), output_schema(), and run(input_data, context=None). "
            "run() must return a dict with status='completed' for successful low-risk mock execution.\n"
            "test_cases must verify the core business logic, not only status/tool_id. Include positive, "
            "negative, and edge examples when the tool performs calculation or validation."
        )
        .request(
            response_format="json_schema",
            json_schema=schema,
            json_schema_name="GeneratedToolCodeDraft",
            json_schema_strict=True,
            metadata={"tool_id": str(draft.get("tool_id") or "")},
        )
    )


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


def fallback_tool_code(draft: dict[str, Any]) -> GeneratedToolCodeDraft:
    tool_id = str(draft.get("tool_id") or "generated_tool")
    risk_level = str(draft.get("risk_level") or "low")
    approval_required = bool(draft.get("approval_required"))
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
    else:
        source = _generic_tool_source(tool_id, risk_level, approval_required)
        test_cases = [
            GeneratedToolTestCase(
                name="generic_tool_returns_completed_contract",
                input_data={"sample": "value"},
                expected_contains={"status": "completed", "tool_id": tool_id},
            )
        ]
    return GeneratedToolCodeDraft(
        tool_id=tool_id,
        python_source=source,
        input_schema={"type": "object", "additionalProperties": True},
        output_schema={"type": "object", "additionalProperties": True},
        test_cases=test_cases,
        risk_notes=["deterministic local mock implementation"],
    )


def required_tool_test_cases(draft: dict[str, Any]) -> list[GeneratedToolTestCase]:
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


def is_strange_number_tool(draft: dict[str, Any]) -> bool:
    text = " ".join(
        str(draft.get(key) or "")
        for key in ("tool_id", "toolset_id", "description")
    ).lower()
    return "strange" in text or "奇异" in text
